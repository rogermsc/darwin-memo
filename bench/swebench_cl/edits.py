"""Search/replace edits -> a correct unified diff.

One-shot diff generation fails for a knowable reason: a model cannot
reliably compute ``@@ -l,s +l,s @@`` hunk line numbers, so its diffs do
not apply. The fix used by practical code-editing agents is to let the
model express edits as exact old->new text blocks and to compute the
diff mechanically. We do that here: the model emits SEARCH/REPLACE
blocks against the BM25-retrieved files, we apply them to the file text
we already fetched, and ``difflib`` produces a diff with correct line
numbers and ``a/``/``b/`` prefixes that ``git apply`` accepts. The model
is only ever responsible for the part it is good at (the changed lines),
never for arithmetic it is bad at.

Format (one or more blocks), the path on the line before the fence:

    path/to/file.py
    <<<<<<< SEARCH
    exact original lines
    =======
    replacement lines
    >>>>>>> REPLACE
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from darwin_memo.llm import THINK_RE

EDIT_FORMAT_INSTRUCTIONS = (
    "Express your fix as one or more SEARCH/REPLACE blocks, and nothing "
    "else. Each block names a file path on its own line, then the exact "
    "original lines to find, then the replacement. Copy the SEARCH text "
    "VERBATIM from the files shown above (same indentation and spacing) so "
    "it can be located exactly. Use this format:\n\n"
    "path/to/file.py\n"
    "<<<<<<< SEARCH\n"
    "the exact existing lines\n"
    "=======\n"
    "the replacement lines\n"
    ">>>>>>> REPLACE\n\n"
    "You may emit several blocks, including across files. Do not output a "
    "diff or any prose other than an optional final 'REFLECTION:' line."
)

_BLOCK_RE = re.compile(
    r"^[ \t]*([^\n<>]+?)[ \t]*\n"  # the path line
    r"<{5,}\s*SEARCH[ \t]*\n"
    r"(.*?)\n?"
    r"={5,}[ \t]*\n"
    r"(.*?)\n?"
    r">{5,}\s*REPLACE",
    re.DOTALL | re.MULTILINE,
)


@dataclass(frozen=True)
class Edit:
    path: str
    search: str
    replace: str


def parse_edits(text: str) -> list[Edit]:
    """Extract SEARCH/REPLACE blocks from a model response."""
    text = THINK_RE.sub("", text)
    # Strip code fences if the model wrapped the whole thing in one.
    edits: list[Edit] = []
    for match in _BLOCK_RE.finditer(text):
        path = match.group(1).strip().strip("`").strip()
        # A fence language tag or stray backticks can ride the path line.
        path = path.split()[-1] if path else path
        edits.append(Edit(path=path, search=match.group(2), replace=match.group(3)))
    return edits


@dataclass
class ApplyResult:
    new_texts: dict[str, str]
    applied: int
    failed: int


def apply_edits(originals: dict[str, str], edits: list[Edit]) -> ApplyResult:
    """Apply edits to a working copy of the original file texts.

    A SEARCH that occurs exactly in the current working text (after any
    earlier edits to the same file) replaces its first occurrence.
    Anything else is counted as failed and skipped, never force-applied.

    A whitespace-tolerant retry lived here on the theory that models
    reproduce a block's shape reliably and its indentation unreliably.
    It fired zero times in 3,015 evaluated tasks, so the theory was
    wrong: failed edits fail because BM25 handed the model the wrong
    file, not because it mis-indented the right one. Removed rather than
    kept as decoration.
    """
    working = dict(originals)
    applied = failed = 0
    for edit in edits:
        text = working.get(edit.path)
        if text is None or edit.search not in text:
            failed += 1
            continue
        working[edit.path] = text.replace(edit.search, edit.replace, 1)
        applied += 1
    return ApplyResult(new_texts=working, applied=applied, failed=failed)


def make_diff(originals: dict[str, str], new_texts: dict[str, str]) -> str:
    """Unified git-style diff over files whose text changed."""
    chunks: list[str] = []
    for path in sorted(new_texts):
        old = originals.get(path, "")
        new = new_texts[path]
        if old == new:
            continue
        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        body = "".join(diff)
        if body and not body.endswith("\n"):
            body += "\n"
        chunks.append(body)
    return "".join(chunks)


def edits_to_patch(originals: dict[str, str], response: str) -> tuple[str, int, int]:
    """Parse, apply, diff: returns (patch, applied, failed)."""
    edits = parse_edits(response)
    result = apply_edits(originals, edits)
    patch = make_diff(originals, result.new_texts)
    return patch, result.applied, result.failed
