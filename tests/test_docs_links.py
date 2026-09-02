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


# ---------------------------------------------------------------------------
# The README is the front door and the PyPI long description. Three counts in
# it had drifted from the code -- five baselines read as six, five bundled
# environments read as three, eight MCP tools read as seven -- because nothing
# compared them. These are cheap to state and were wrong for months.
# ---------------------------------------------------------------------------

README = ROOT / "README.md"

_WORD = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _stated(pattern: str) -> int:
    """The number the README claims, written as a word."""
    match = re.search(pattern, README.read_text())
    assert match, f"the README sentence matching {pattern!r} was reworded"
    return _WORD[match.group(1).lower()]


def test_readme_baseline_count_matches_the_arms_tuple() -> None:
    from bench.policies import ARMS

    baselines = [arm for arm in ARMS if not arm.startswith("survival")]
    assert _stated(r"benchmarked against (\w+) baselines") == len(baselines)


def test_readme_environment_count_matches_the_exports() -> None:
    import darwin_memo

    shipped = [name for name in darwin_memo.__all__ if name.endswith("Env")]
    assert len(shipped) == 5, shipped
    assert _stated(r"(\w+) environments ship") == len(shipped)


def test_readme_names_every_mcp_tool_the_server_registers() -> None:
    """Mutation: add a @server.tool() and this fails until the README lists it.

    ``memory_audit`` shipped and the README kept advertising seven tools.
    """
    server = (ROOT / "darwin_memo" / "mcp_server.py").read_text()
    registered = set(re.findall(r"@server\.tool\(\)\s*\n\s*def (memory_\w+)", server))
    assert len(registered) == 8, registered
    named = set(re.findall(r"memory_\w+", README.read_text()))
    missing = registered - named
    assert not missing, f"MCP tools the README does not name: {missing}"


def test_readme_links_the_load_bearing_docs() -> None:
    """A guide nothing links to is a guide nobody reads.

    ``docs/custom-environments.md`` is the one task the README itself calls
    the whole trick, and it was reachable only by listing the directory.
    """
    body = README.read_text()
    assert "docs/custom-environments.md" in body
    for guide in sorted((DOCS / "integrations").glob("*.md")):
        assert guide.name in body, f"README does not link integrations/{guide.name}"


def test_readme_has_no_relative_links_because_pypi_renders_it() -> None:
    """PyPI does not rewrite relative URLs, so they 404 on the project page.

    The hero GIF was a broken image above the fold on the primary
    distribution page of a project whose pitch is "watch it go extinct".
    """
    targets = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", README.read_text())
    assert targets, "the link parser found nothing -- it is broken, not the README"
    relative = [
        t for t in targets if not t.startswith(("http://", "https://", "#", "mailto:"))
    ]
    assert not relative, f"relative links break on PyPI: {relative}"


# ---------------------------------------------------------------------------
# The README's Python fences teach the actual entry points, and the README is
# the PyPI long description. docs/api.md is checked against __all__, but the
# README examples were not: renaming or removing an export -- QueryProtocol,
# Ledger, decision_polarity -- would rot the front-door snippet with nothing
# to catch it. This checks the two rots that actually happen: broken syntax,
# and a name imported from darwin_memo that no longer exists. It does not
# execute the fences -- they open illustrative files and use placeholder
# variables (passes_after, entry_id) by design -- so method-level renames on
# those objects are out of scope, which the api.md test covers by other means.
# ---------------------------------------------------------------------------

_PY_FENCE = re.compile(r"```python\n(.*?)```", re.S)


def test_readme_python_examples_compile_and_import_real_api() -> None:
    """Mutation: rename any darwin_memo export used in a README fence (or break
    a fence's syntax) and this fires. 16 exported names ride on these snippets.
    """
    import ast

    import darwin_memo

    fences = _PY_FENCE.findall(README.read_text())
    assert len(fences) >= 5, "the fence parser found too few -- it is broken"
    exported = set(darwin_memo.__all__)
    imported: set[str] = set()
    for i, code in enumerate(fences):
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:  # pragma: no cover - the assert reports it
            msg = f"README python fence {i} does not parse: {exc}"
            raise AssertionError(msg) from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "darwin_memo":
                for alias in node.names:
                    assert alias.name in exported, (
                        f"README fence {i} imports darwin_memo.{alias.name}, "
                        "which is not an export -- the front-door example is stale"
                    )
                    imported.add(alias.name)
    assert len(imported) >= 10, (
        f"only {len(imported)} darwin_memo names checked; the examples thinned "
        "out or the import walk missed them"
    )
