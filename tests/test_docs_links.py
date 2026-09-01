"""The docs index says it links everything, so check that it does.

``docs/README.md`` opens with "This index is everything else". That sentence
was false: `custom-environments.md` did not exist yet, and `organic.md` and
`threat-model.md` existed and were linked from nowhere, so two pages a reader
needs were reachable only by listing the directory. A sentence asserting its
own completeness is an unenforced invariant, which is the failure mode this
repository keeps rediscovering. This is that sentence, enforced.

The second test is the cheaper and broader one: a relative link to a file that
does not exist. ``paper/reproduce.md`` pointed at ``paper/darwin-memo.md`` for
some time after nothing else did, and nothing noticed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
INDEX = DOCS / "README.md"

# Working notes that are deliberately not in the reader-facing index. Adding a
# directory here is a decision to publish something unindexed, which is why it
# is a list and not a pattern.
INTERNAL = {"research", "superpowers", "disclosure", "assets"}

_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _relative_links(text: str) -> list[str]:
    out = []
    for target in _LINK.findall(text):
        target = target.split("#", 1)[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        out.append(target)
    return out


def test_index_links_every_user_facing_page() -> None:
    linked = set(_relative_links(INDEX.read_text()))
    pages = {
        str(path.relative_to(DOCS))
        for path in DOCS.rglob("*.md")
        if path != INDEX and not (set(path.relative_to(DOCS).parts) & INTERNAL)
    }
    assert pages, "no docs found -- the walk is broken, not the index"
    missing = sorted(pages - linked)
    assert not missing, (
        f"docs/README.md says it is 'everything else' but does not link {missing}"
    )


@pytest.mark.parametrize(
    "source",
    sorted(
        [*DOCS.rglob("*.md"), ROOT / "README.md", ROOT / "CONTRIBUTING.md"],
        key=str,
    ),
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_every_relative_link_resolves(source: Path) -> None:
    """Mutation: point any link at a file that does not exist and this fails."""
    broken = [
        target
        for target in _relative_links(source.read_text())
        if not (source.parent / target).resolve().exists()
    ]
    assert not broken, f"{source.relative_to(ROOT)} links to missing {broken}"
