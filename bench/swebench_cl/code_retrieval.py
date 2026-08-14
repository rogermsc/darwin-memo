"""BM25 file retrieval over a repository at a pinned commit.

The blind pilot prompt (problem statement + lessons only) cannot resolve
real issues, because the model never sees the code it must patch. This
module supplies the missing context the faithful way: it fetches the
repository at the task's ``base_commit`` and ranks its source files
against the issue text with classic BM25, so the prompt carries the
files the issue is actually about. Stdlib only (urllib + tarfile + a
hand-rolled BM25), matching the rest of the harness's zero-dependency
stance.

Retrieval is blind by default: the gold patch is never read. The one
exception is the ORACLE CONTROL (``oracle_files`` + ``code_context(...,
prefer=)``), which reads the answer key on purpose to measure what the
arms would score if retrieval were solved. Any run using it is a
control, never a result, and records ``oracle_retrieval: true`` in its
config so a reader cannot mistake one for the other.

The fetch uses GitHub's archive endpoint
(``/{repo}/archive/{commit}.tar.gz``), which returns the exact tree at
any commit sha with no clone and no auth, and caches the extracted tree
by sha so a re-run never re-downloads.
"""

from __future__ import annotations

import math
import re
import tarfile
import urllib.request
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# BM25 constants (Robertson/Sparck-Jones defaults).
_K1 = 1.5
_B = 0.75

# Files we never rank: vendored, generated, or too large to be the unit
# of a fix. Kept deliberately small; the point is signal, not a linter.
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".tox",
    "build",
    "dist",
    "vendor",
    "third_party",
    ".eggs",
}
_MAX_FILE_BYTES = 200_000  # skip a file larger than this for ranking

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


def tokenize(text: str) -> list[str]:
    """Lowercase identifier tokens, with camelCase/snake_case sub-tokens.

    ``getFooBar`` and ``get_foo_bar`` both yield ``get foo bar`` (plus the
    whole token), so an issue that says "foo bar" matches either style.
    """
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        low = raw.lower()
        tokens.append(low)
        parts = [p.lower() for p in _CAMEL_RE.findall(raw) if len(p) > 1]
        if len(parts) > 1:
            tokens.extend(parts)
    return tokens


def fetch_repo_at_commit(repo: str, commit: str, cache_dir: Path) -> Path:
    """Download+extract ``repo`` at ``commit``, cached by sha. Returns root.

    ``repo`` is ``owner/name``. The archive extracts to a single
    top-level directory (``name-<commit>``); we return that directory.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    marker = cache_dir / f"{repo.replace('/', '__')}__{commit}"
    if marker.exists():
        roots = [p for p in marker.iterdir() if p.is_dir()]
        if roots:
            return roots[0]
    url = f"https://github.com/{repo}/archive/{commit}.tar.gz"
    tmp = cache_dir / f".{repo.replace('/', '__')}__{commit}.tar.gz"
    with urllib.request.urlopen(url, timeout=180) as response:
        tmp.write_bytes(response.read())
    marker.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tmp, "r:gz") as tar:
        # Defensive extraction: refuse any member that escapes the dir.
        members = [m for m in tar.getmembers() if not m.name.startswith(("/", ".."))]
        tar.extractall(marker, members=members, filter="data")
    tmp.unlink(missing_ok=True)
    roots = [p for p in marker.iterdir() if p.is_dir()]
    if not roots:
        raise RuntimeError(f"empty archive for {repo}@{commit}")
    return roots[0]


@dataclass
class _Doc:
    relpath: str
    text: str
    tokens: Counter[str]
    length: int


def _gather_py_files(root: Path) -> list[_Doc]:
    docs: list[_Doc] = []
    for path in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        toks = tokenize(text)
        if not toks:
            continue
        docs.append(_Doc(str(path.relative_to(root)), text, Counter(toks), len(toks)))
    return docs


def bm25_rank(docs: list[_Doc], query: str) -> list[tuple[_Doc, float]]:
    """Rank docs by BM25 against the query's unique terms (descending)."""
    if not docs:
        return []
    n = len(docs)
    avgdl = sum(d.length for d in docs) / n
    df: Counter[str] = Counter()
    for d in docs:
        df.update(d.tokens.keys())
    q_terms = set(tokenize(query))
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in q_terms if df[t]}
    scored: list[tuple[_Doc, float]] = []
    for d in docs:
        score = 0.0
        for t, t_idf in idf.items():
            f = d.tokens.get(t, 0)
            if not f:
                continue
            denom = f + _K1 * (1 - _B + _B * d.length / avgdl)
            score += t_idf * (f * (_K1 + 1)) / denom
        if score > 0:
            scored.append((d, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def oracle_files(gold_patch: str) -> list[str]:
    """The files the gold patch touches: perfect retrieval, by definition.

    Reads the ``--- a/`` lines of a unified diff, the same way
    ``poison._touched_files`` does. This is ground truth taken from the
    answer key, so it is only ever legitimate as a CONTROL: it says what
    the arms would score if retrieval were solved, which is the number
    the paper needs to separate "memory did not help" from "the model
    never saw the file".
    """
    return [
        line[6:].strip()
        for line in gold_patch.splitlines()
        if line.startswith("--- a/")
    ]


def code_context(
    repo: str,
    commit: str,
    query: str,
    cache_dir: Path,
    max_chars: int,
    max_files: int = 5,
    prefer: Sequence[str] = (),
) -> tuple[str, list[str], dict[str, str]]:
    """Return (prompt-ready file context, included relpaths, full originals).

    Greedy fill in BM25 order up to ``max_chars``; the last file is
    truncated to fit rather than dropped, so the budget is always used.
    The third return value maps each included path to its FULL original
    text (not the truncated prompt slice), which the edit applier needs
    to locate SEARCH blocks and to compute a correct diff.

    ``prefer`` promotes named relpaths to the front of the ranking,
    keeping BM25 order behind them. It exists for the oracle-retrieval
    control (see :func:`oracle_files`): the budget, the truncation, and
    the prompt shape stay identical, so the only thing that changes is
    WHICH files fill the budget. Passing it with anything derived from
    the gold patch makes the run a control and not a result.
    """
    if max_chars <= 0:
        return "", [], {}
    root = fetch_repo_at_commit(repo, commit, cache_dir)
    docs = _gather_py_files(root)
    ranked = bm25_rank(docs, query)
    if prefer:
        # Pull preferred docs from the FULL doc list, not from `ranked`:
        # bm25_rank drops every doc that scores zero, which is exactly
        # the case an oracle control exists to cover. Promoting within
        # the ranking would silently skip any gold file BM25 never
        # found, and the "oracle" would agree with BM25 by construction
        # on precisely the tasks where it is supposed to disagree.
        by_path = {doc.relpath: doc for doc in docs}
        head = [(by_path[p], float("inf")) for p in prefer if p in by_path]
        promoted = {doc.relpath for doc, _ in head}
        ranked = head + [pair for pair in ranked if pair[0].relpath not in promoted]
    blocks: list[str] = []
    included: list[str] = []
    originals: dict[str, str] = {}
    used = 0
    for doc, _score in ranked[:max_files]:
        if used >= max_chars:
            break
        header = f"### {doc.relpath}\n"
        remaining = max_chars - used - len(header)
        if remaining <= 200:  # not enough room for a meaningful slice
            break
        body = doc.text[:remaining]
        if len(doc.text) > len(body):
            body += "\n# ... (file truncated)\n"
        blocks.append(header + body)
        included.append(doc.relpath)
        originals[doc.relpath] = doc.text
        used += len(header) + len(body)
    return "\n\n".join(blocks), included, originals
