"""Attacks run against memory systems we did not write.

These are the answer to the standing objection that every other result in
the paper runs on an environment we built. That makes their provenance
matter more than anyone else's, not less: a result about somebody else's
curator is a result about a specific version of it.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def external_versions(*distributions: str) -> dict[str, str | None]:
    """Installed version of each named distribution, ``None`` if absent.

    Recorded into every report so a reader can tell which build of the
    target was attacked. The committed runs from 2026-08 predate this and
    carry no versions, which their manifest says rather than guesses.
    """
    found: dict[str, str | None] = {}
    for dist in distributions:
        try:
            found[dist] = version(dist)
        except PackageNotFoundError:
            found[dist] = None
    return found
