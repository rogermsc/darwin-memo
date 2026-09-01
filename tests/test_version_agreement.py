"""Every file that states the package version has to state the same one.

Four files carry it and they had drifted apart: ``CITATION.cff`` and both
``server.json`` fields said 0.5.1 while ``darwin_memo.__version__`` said
0.6.0. Nothing noticed, because ``mcp-publish.yml`` stamps ``server.json``
from the git tag before publishing and ``release.yml`` only compares the tag
against ``__version__`` -- so the checked-in values were free to rot, and the
citation metadata a reader actually reads was the stale one.

``docs/benchmarks.md`` is deliberately excluded. Its "darwin-memo 0.4.0" line
sits under *Setup* and records the version that produced those runs, which is
evidence provenance, not a version declaration. Bumping it to match would
falsify the record; it is supposed to disagree.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _declared() -> dict[str, list[str]]:
    """Every stated version, keyed by the file that states it."""
    init = (ROOT / "darwin_memo" / "__init__.py").read_text()
    cff = (ROOT / "CITATION.cff").read_text()
    server = json.loads((ROOT / "server.json").read_text())
    zenodo = json.loads((ROOT / ".zenodo.json").read_text())
    return {
        "darwin_memo/__init__.py": re.findall(r'^__version__ = "([^"]+)"', init, re.M),
        "CITATION.cff": re.findall(r"^version: (\S+)", cff, re.M),
        # Top level plus every package entry: the publisher stamps them all.
        "server.json": [server["version"]]
        + [pkg["version"] for pkg in server.get("packages", [])],
        ".zenodo.json": [zenodo["version"]],
    }


def test_every_file_states_one_agreed_version() -> None:
    """Mutation: change any single one of these and this fails."""
    declared = _declared()
    for source, versions in declared.items():
        assert versions, f"{source} states no version"
    found = {v for versions in declared.values() for v in versions}
    assert len(found) == 1, f"versions disagree: {declared}"


def test_the_stated_version_is_the_imported_one() -> None:
    """The files agree with the package that actually installs."""
    from darwin_memo import __version__

    assert set(_declared()["CITATION.cff"]) == {__version__}
