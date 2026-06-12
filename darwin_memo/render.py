"""Budget-capped memory rendering for Claude Code auto memory.

    darwin-memo render STORE -o MEMORY.md --budget 25kb
    darwin-memo render STORE -o MEMORY.md --split-dir memory

Claude Code auto memory loads the first 200 lines / 25KB of MEMORY.md
at session start, whichever ceiling it hits first, and follows links to
topic files on demand. render projects a survival store into exactly
that shape: living entries ranked by balance, greedily packed under a
hard byte budget AND a hard line cap (``--max-lines``, default 200),
grouped by kind, each entry one tight block with a one-line provenance
annotation. The group whose leader holds the highest balance renders
first, so the most valuable content always sits in the first lines of
the file.

Two invariants the tests hold:

- The output NEVER exceeds the budget, in bytes or in lines. Admission
  is measured against the fully rebuilt document (header, group
  headings, shown count included), not estimated per entry, and a
  last-resort UTF-8-safe truncation guards even budgets too small for
  the header. The shown count only ever counts entries inside both
  ceilings, so nothing the header claims sits past what the host reads.
- Rendering is deterministic: same store, same arguments, byte-identical
  output. Ties in balance break on entry id and nothing here reads a
  clock.

Split mode (``--split-dir DIR``) turns MEMORY.md into a one-line-per-
topic index and writes one file per kind group into DIR, each packed
under a proportional share of the budget, so any single file the host
pulls stays bounded. A re-render deletes topic files for kinds with
nothing left to show, including when the whole store has died or gone
missing, so dead lessons never linger on the reading surface; the
index is always a complete map of the directory.

A missing store file or a store with zero living entries renders a
minimal honest file saying so. An unreadable store (empty, truncated,
locked, or not a store payload) raises ``ValueError`` naming the cause;
the CLI turns that into a one-line error with exit code 1 and leaves
the previous render untouched, never a traceback.
``register_render_command`` attaches the subparser so cli.py stays one
import plus one call.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from .store import MemoryStore, StoreLockedError
from .types import EntryKind, MemoryEntry

__all__ = [
    "DEFAULT_BUDGET",
    "DEFAULT_MAX_LINES",
    "parse_budget",
    "ranked_living",
    "register_render_command",
    "render_store",
]

DEFAULT_BUDGET = "25kb"  # what Claude Code auto memory actually loads
DEFAULT_MAX_LINES = 200  # the other ceiling: lines read at session start

_UNIT_BYTES = {"b": 1, "k": 1024, "kb": 1024, "m": 1024**2, "mb": 1024**2}
_BUDGET_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-z]*)\s*$", re.IGNORECASE)

_T = TypeVar("_T")


def parse_budget(spec: str) -> int:
    """Bytes from forms like ``25kb``, ``25KB``, ``8000``, ``1.5mb``.

    kb and mb are binary (1024-based), matching how the 25KB auto-memory
    ceiling is measured. A bare number is bytes.
    """
    match = _BUDGET_RE.match(spec)
    if match is None:
        raise ValueError(f"unparseable budget {spec!r}; use forms like 25kb or 8000")
    unit = match.group(2).lower() or "b"
    if unit not in _UNIT_BYTES:
        raise ValueError(f"unparseable budget {spec!r}; use forms like 25kb or 8000")
    budget = int(float(match.group(1)) * _UNIT_BYTES[unit])
    if budget <= 0:
        raise ValueError(f"budget must be positive, got {spec!r}")
    return budget


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _line_len(text: str) -> int:
    """Lines as a line-based reader counts them; a trailing newline ends
    the last line rather than starting an empty one."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _fit(text: str, budget: int, max_lines: int | None = None) -> str:
    """Last-resort guarantee: cut at a line boundary, then a UTF-8
    boundary, and never exceed either ceiling."""
    if max_lines is not None and _line_len(text) > max_lines:
        text = "".join(f"{line}\n" for line in text.split("\n")[:max_lines])
    if _byte_len(text) <= budget:
        return text
    return text.encode("utf-8")[:budget].decode("utf-8", errors="ignore")


# ----------------------------------------------------------------------
# Selection: rank, group, pack
# ----------------------------------------------------------------------


def ranked_living(store: MemoryStore) -> list[MemoryEntry]:
    """Living entries, highest balance first, ties broken by id."""
    living = [entry for entry in store.alive() if entry.alive]
    living.sort(key=lambda entry: (-entry.energy, entry.id))
    return living


def _grouped(entries: list[MemoryEntry]) -> list[tuple[str, list[MemoryEntry]]]:
    """Group by kind, groups led by their strongest member.

    Entries arrive ranked, so each group list stays balance-ordered and
    the group whose leader holds the highest balance sorts first: the
    top entry overall is always the first block in the document.
    """
    groups: dict[str, list[MemoryEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.kind.value, []).append(entry)
    return sorted(groups.items(), key=lambda kv: (-kv[1][0].energy, kv[0]))


def _entry_block(entry: MemoryEntry) -> str:
    """One tight block: the lesson text plus one provenance line."""
    settled = f"t{entry.last_used_cycle}" if entry.last_used_cycle >= 0 else "never"
    lesson = " ".join(entry.answer.split()) or "(empty)"
    return (
        f"- {lesson}\n"
        f"  (id {entry.id[:8]}, balance {entry.energy:.3f}, last settle {settled})\n"
    )


def _pack(
    candidates: list[_T],
    budget: int,
    build: Callable[[list[_T]], str],
    max_lines: int | None = None,
) -> tuple[list[_T], str]:
    """Greedy knapsack in rank order; the built document is the measure.

    Each candidate is admitted only if the fully rebuilt document still
    fits both ceilings, so the header, group headings, and the shown
    count are charged against the budget rather than estimated. An item
    too large to fit is skipped, and smaller lower-ranked items may
    still enter.
    """
    selected: list[_T] = []
    document = build(selected)
    for item in candidates:
        trial = build([*selected, item])
        if _byte_len(trial) <= budget and (
            max_lines is None or _line_len(trial) <= max_lines
        ):
            selected, document = [*selected, item], trial
    return selected, _fit(document, budget, max_lines)


# ----------------------------------------------------------------------
# Documents
# ----------------------------------------------------------------------


def _single_document(
    source: str,
    selected: list[MemoryEntry],
    living: int,
    budget: int,
    max_lines: int,
) -> str:
    lines = [
        f"<!-- rendered by darwin-memo from {source}: "
        f"{len(selected)} of {living} living entries shown, "
        f"budget {budget} bytes, {max_lines} lines -->\n"
    ]
    if living == 0:
        lines.append("\n(no living entries: nothing has earned its keep yet)\n")
    elif not selected:
        lines.append("\n(the budget is too small for any entry)\n")
    else:
        for label, members in _grouped(selected):
            lines.append(f"\n## {label}\n\n")
            lines.extend(_entry_block(entry) for entry in members)
    return "".join(lines)


def _topic_document(
    source: str, label: str, selected: list[MemoryEntry], count: int, share: int
) -> str:
    lines = [
        f"<!-- rendered by darwin-memo from {source}: topic {label}, "
        f"{len(selected)} of {count} entries shown, budget {share} bytes -->\n\n"
    ]
    lines.extend(_entry_block(entry) for entry in selected)
    return "".join(lines)


def _topic_builder(
    source: str, label: str, count: int, share: int
) -> Callable[[list[MemoryEntry]], str]:
    def build(selected: list[MemoryEntry]) -> str:
        return _topic_document(source, label, selected, count, share)

    return build


def _index_builder(
    source: str, living: int, budget: int, max_lines: int, out_dir: Path
) -> Callable[[list[dict[str, Any]]], str]:
    """One line per topic linking its file; the index obeys both ceilings.

    The header is rebuilt from the admitted set, so the topic and entry
    counts name exactly what the index links, never a dropped topic.
    """

    def build(admitted: list[dict[str, Any]]) -> str:
        shown = sum(int(topic["shown"]) for topic in admitted)
        lines = [
            f"<!-- rendered by darwin-memo from {source}: "
            f"index of {len(admitted)} topics, {shown} of {living} living entries, "
            f"budget {budget} bytes, {max_lines} lines -->\n\n"
        ]
        for topic in admitted:
            rel = Path(os.path.relpath(str(topic["path"]), out_dir)).as_posix()
            lines.append(
                f"- [{topic['topic']}]({rel}): {topic['shown']} of "
                f"{topic['entries']} entries, "
                f"top balance {float(topic['top_balance']):.3f}\n"
            )
        return "".join(lines)

    return build


def _clear_stale_topics(split_dir: Path, keep: set[str]) -> None:
    """Delete topic files for kinds with nothing to show this render.

    Without this, a kind whose last entry died would leave its previous
    topic file sitting in the live memory directory, unlinked from the
    index but still readable: dead lessons on the reading surface.
    """
    for kind in EntryKind:
        if kind.value not in keep:
            (split_dir / f"{kind.value}.md").unlink(missing_ok=True)


# ----------------------------------------------------------------------
# Entry points
# ----------------------------------------------------------------------


def render_store(
    store_path: Path,
    out_path: Path,
    budget: int,
    split_dir: Path | None = None,
    max_lines: int = DEFAULT_MAX_LINES,
) -> dict[str, Any]:
    """Render top-balance survivors under hard byte and line budgets.

    Returns a summary dict (shown, living, bytes, lines, out, topics)
    so the CLI and tests read the same accounting that was written.
    An unreadable store raises ``ValueError`` naming the cause and
    writes nothing, so the previous render stays in place.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    source = store_path.name
    if not store_path.exists():
        if split_dir is not None:
            _clear_stale_topics(split_dir, keep=set())
        text = _fit(
            f"<!-- rendered by darwin-memo from {source}: "
            "store not found, nothing to show -->\n",
            budget,
            max_lines,
        )
        out_path.write_text(text, encoding="utf-8")
        return {
            "out": str(out_path),
            "shown": 0,
            "living": 0,
            "bytes": _byte_len(text),
            "lines": _line_len(text),
            "topics": [],
        }
    try:
        candidates = ranked_living(MemoryStore.load(store_path))
    except (StoreLockedError, OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"cannot read store {store_path}: {exc}") from exc
    living = len(candidates)
    if split_dir is not None:
        if living > 0:
            return _render_split(
                source, candidates, out_path, budget, split_dir, max_lines
            )
        _clear_stale_topics(split_dir, keep=set())
    selected, document = _pack(
        candidates,
        budget,
        lambda chosen: _single_document(source, chosen, living, budget, max_lines),
        max_lines=max_lines,
    )
    out_path.write_text(document, encoding="utf-8")
    return {
        "out": str(out_path),
        "shown": len(selected),
        "living": living,
        "bytes": _byte_len(document),
        "lines": _line_len(document),
        "topics": [],
    }


def _render_split(
    source: str,
    candidates: list[MemoryEntry],
    out_path: Path,
    budget: int,
    split_dir: Path,
    max_lines: int,
) -> dict[str, Any]:
    """Index in out_path, one budget-aware topic file per kind in split_dir.

    Topic files are written only for topics whose index line was
    admitted, and stale kind files from earlier renders are deleted, so
    the directory holds exactly what the index links and the summary
    counts exactly what the host can reach.
    """
    split_dir.mkdir(parents=True, exist_ok=True)
    living = len(candidates)
    topics: list[dict[str, Any]] = []
    documents: dict[str, str] = {}
    for label, members in _grouped(candidates):
        share = max(1, budget * len(members) // living)
        selected, document = _pack(
            members, share, _topic_builder(source, label, len(members), share)
        )
        documents[label] = document
        topics.append(
            {
                "topic": label,
                "path": str(split_dir / f"{label}.md"),
                "shown": len(selected),
                "entries": len(members),
                "bytes": _byte_len(document),
                "budget": share,
                "top_balance": members[0].energy,
            }
        )
    admitted, index = _pack(
        topics,
        budget,
        _index_builder(source, living, budget, max_lines, out_path.parent),
        max_lines=max_lines,
    )
    for topic in admitted:
        Path(topic["path"]).write_text(documents[topic["topic"]], encoding="utf-8")
    _clear_stale_topics(split_dir, keep={str(topic["topic"]) for topic in admitted})
    out_path.write_text(index, encoding="utf-8")
    return {
        "out": str(out_path),
        "shown": sum(int(topic["shown"]) for topic in admitted),
        "living": living,
        "bytes": _byte_len(index),
        "lines": _line_len(index),
        "topics": admitted,
    }


def cmd_render(args: argparse.Namespace) -> int:
    try:
        budget = parse_budget(args.budget)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.max_lines < 1:
        print(
            f"error: max-lines must be positive, got {args.max_lines}",
            file=sys.stderr,
        )
        return 1
    try:
        summary = render_store(
            Path(args.memory).expanduser(),
            Path(args.out).expanduser(),
            budget,
            split_dir=Path(args.split_dir).expanduser() if args.split_dir else None,
            max_lines=args.max_lines,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"rendered {summary['shown']} of {summary['living']} living entries "
        f"({summary['bytes']} bytes, {summary['lines']} lines, budget {budget}) "
        f"-> {summary['out']}"
    )
    for topic in summary["topics"]:
        print(
            f"  {topic['topic']}: {topic['shown']} of {topic['entries']} entries "
            f"({topic['bytes']} bytes, budget {topic['budget']}) -> {topic['path']}"
        )
    return 0


def register_render_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Attach render, so cli.py stays one import plus one call."""
    render = sub.add_parser(
        "render", help="top-balance survivors as a budget-capped MEMORY.md"
    )
    render.add_argument("memory", help="store file to render from")
    render.add_argument(
        "-o", "--out", default="MEMORY.md", help="output file (default MEMORY.md)"
    )
    render.add_argument(
        "--budget",
        default=DEFAULT_BUDGET,
        help="hard byte cap: 25kb, 25KB, or 8000 (default 25kb)",
    )
    render.add_argument(
        "--max-lines",
        type=int,
        default=DEFAULT_MAX_LINES,
        help="hard line cap on the output file "
        f"(default {DEFAULT_MAX_LINES}, what Claude Code reads at session start)",
    )
    render.add_argument(
        "--split-dir",
        default=None,
        help="write one topic file per kind into DIR; the output becomes the index",
    )
    render.set_defaults(fn=cmd_render)
