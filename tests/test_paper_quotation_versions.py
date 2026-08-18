"""A quotation must name the version of the document it is quoting.

``paper/references.bib`` cites arXiv preprints, which are mutable. Usually that
does not matter. It mattered once: the paper quoted two sentences from
``arXiv:2604.16548`` under one unversioned key, and those two sentences have
never appeared in the same document.

* v1 (~250k characters of text) carries the availability-gap analysis --
  three named threats and "architecturally plausible but empirically
  unstudied", which \\S\\ref{sec:related} uses to state the gap this paper
  closes.
* v2 is a rewrite about a fifth that length. It drops the availability-gap
  analysis for a Verifiable Memory Governance framework, and adds the sentence
  about retention schemes keeping adversarial entries alive that the intro and
  the retention section both quote.

A reader following the bare identifier reaches v2 and finds the second quote
but not the first, and the natural conclusion is that we invented it. Each
quote is now bound to the version that contains it.

The check is deliberately narrow. It does not fetch anything -- it verifies
that the quote and its required citation key travel together in the source, and
that both keys pin an explicit version. Whether the remote text still says this
is not knowable offline, which is exactly why the version pin is the guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BIB = ROOT / "paper" / "references.bib"
SECTIONS = ROOT / "paper" / "sections"

# (quote fragment, the key that must appear in the same paragraph)
BOUND_QUOTES = [
    ("architecturally plausible but empirically unstudied", "lin2026memsurveyv1"),
    ("retention schemes based on access frequency", "lin2026memsurvey"),
]

VERSIONED_KEYS = ("lin2026memsurvey", "lin2026memsurveyv1")


def _paragraphs() -> list[str]:
    out = []
    for tex in sorted(SECTIONS.glob("*.tex")):
        for para in tex.read_text().split("\n\n"):
            out.append(" ".join(para.split()))
    return out


def _entry(key: str) -> str:
    body = BIB.read_text()
    start = body.index("{" + key + ",")
    return body[start : body.index("\n}", start)]


@pytest.mark.parametrize(("fragment", "key"), BOUND_QUOTES)
def test_quote_is_cited_to_the_version_containing_it(fragment: str, key: str) -> None:
    """Mutation: swap the two keys and this fires on both rows. That swap is
    the exact error the pin exists to prevent, and nothing else in the suite
    would notice it -- the paper still builds and every reference resolves."""
    hits = [p for p in _paragraphs() if fragment.lower() in p.lower()]
    assert hits, f"quotation {fragment!r} is no longer in the paper"
    for para in hits:
        assert key in para, (
            f"the quotation {fragment!r} appears in a paragraph that does not "
            f"cite {key}. That sentence exists in only one version of "
            "arXiv:2604.16548, and citing the other attributes to it a "
            "sentence it does not contain."
        )


@pytest.mark.parametrize("key", VERSIONED_KEYS)
def test_divergent_survey_entries_pin_a_version(key: str) -> None:
    """Mutation: drop the ``v1``/``v2`` suffix from either entry and this fires.
    An unversioned identifier resolves to whatever is current, which for this
    paper is a document that contains one of our two quotations."""
    entry = _entry(key)
    assert re.search(r"arXiv:2604\.16548v[12]\b", entry), (
        f"{key} must pin an explicit arXiv version; this preprint's versions "
        "disagree on the sentences we quote from it"
    )


@pytest.mark.parametrize("key", VERSIONED_KEYS)
def test_both_versions_are_actually_cited(key: str) -> None:
    """A version-pinned entry nobody cites is a dangling claim of provenance,
    and an uncited bib entry is a defect this repo has had before."""
    assert any(key in p for p in _paragraphs()), f"{key} is in the bib but uncited"
