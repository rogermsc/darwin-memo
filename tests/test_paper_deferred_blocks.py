"""One copy of every word, in exactly one place per build.

``main.tex`` builds two documents from one source. The preprint typesets a
supporting block where it is written; the venue build (``\\bodyonly``) drops
it there and typesets it in the appendix instead. The mechanism is two
macros and an ``\\input``, and its failure mode is silence: delete the
appendix line and the venue PDF still compiles, still looks finished, and
is simply missing a page of threats to validity. Nothing else in this
repository would notice.

So each block is checked to appear exactly once in each build, and each
``\\pointer`` -- the sentence that says where a block went -- is checked to
name a section that exists, because a pointer into nothing is the same
loss wearing a citation.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = ROOT / "paper" / "sections"
DETAIL = SECTIONS / "detail"
APPENDIX = SECTIONS / "appendix.tex"


def _all_tex() -> list[Path]:
    return sorted(SECTIONS.rglob("*.tex"))


def _appendix_deferred_region() -> str:
    """The part of the appendix that only the venue build typesets."""
    text = APPENDIX.read_text(encoding="utf-8")
    start = text.index("\\ifdefined\\bodyonly")
    return text[start:]


def test_every_deferred_block_is_placed_in_both_builds() -> None:
    inplace = "".join(p.read_text(encoding="utf-8") for p in _all_tex())
    region = _appendix_deferred_region()
    blocks = sorted(p.stem for p in DETAIL.glob("*.tex"))
    assert blocks, "no deferred blocks found; the mechanism has been removed"
    for name in blocks:
        preprint = len(re.findall(r"\\inplace\{" + re.escape(name) + r"\}", inplace))
        venue = len(
            re.findall(r"\\input\{sections/detail/" + re.escape(name) + r"\}", region)
        )
        assert preprint == 1, (
            f"sections/detail/{name}.tex is named by {preprint} \\inplace calls; "
            "the preprint build would show it that many times"
        )
        assert venue == 1, (
            f"sections/detail/{name}.tex is \\input {venue} times inside the "
            "appendix's \\ifdefined\\bodyonly region; the venue build would "
            "show it that many times"
        )


def test_no_inplace_names_a_missing_block() -> None:
    for path in _all_tex():
        text = path.read_text(encoding="utf-8")
        for name in re.findall(r"\\inplace\{([^}]+)\}", text):
            assert (DETAIL / f"{name}.tex").is_file(), (
                f"{path.relative_to(ROOT)} defers to sections/detail/{name}.tex, "
                "which does not exist"
            )


def test_every_pointer_resolves_to_a_label_that_exists() -> None:
    """A \\pointer says where the block went. It is only true if the label is."""
    tex = "".join(p.read_text(encoding="utf-8") for p in _all_tex())
    labels = set(re.findall(r"\\label\{([^}]+)\}", tex))
    for body in re.findall(r"\\pointer\{(.*?)\}\n", tex, re.S):
        for ref in re.findall(r"\\ref\{([^}]+)\}", body):
            assert ref in labels, (
                f"a \\pointer names \\label{{{ref}}}, which does not exist"
            )
