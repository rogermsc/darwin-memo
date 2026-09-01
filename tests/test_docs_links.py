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

The third is the same failure in ``docs/api.md``, which states its own rule --
"when this page and the code disagree, the code wins and the page has a bug" --
and had six of the package's 54 exported names missing when this was written.
A page that declares its own correctness and is not checked is the exact
pattern the first two tests exist for.
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


def test_api_reference_documents_every_exported_name() -> None:
    """``docs/api.md`` covers everything in ``darwin_memo.__all__``.

    The page says the code wins when they disagree, which makes the page a
    bug report rather than a contract unless something enforces it. Six names
    were missing when this was added: the two rent-priced environments and
    their tier helpers, ``advance_lifecycle``, and ``__version__``.

    Only this direction is checked. The page legitimately names things that
    are not exports -- CLI subcommands, MCP tools, exception behaviour -- so
    the reverse would be noise.
    """
    import darwin_memo

    doc = (DOCS / "api.md").read_text()
    exported = list(darwin_memo.__all__)
    assert len(exported) > 40, "__all__ shrank unexpectedly; is the walk right?"
    # Word boundaries, not substrings. A plain ``in`` check is satisfied by any
    # superstring, so documenting only ``RentedStorageEnv`` would silently
    # count as documenting ``StorageEnv`` -- and renaming a heading to
    # ``RentedTestSuiteEnvX`` would keep this green, which is how the first
    # version of this test passed a break aimed straight at it.
    missing = sorted(
        name
        for name in exported
        if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", doc)
    )
    assert not missing, f"exported but undocumented in docs/api.md: {missing}"
