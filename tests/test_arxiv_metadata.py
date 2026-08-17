"""The submission metadata has to be submittable.

arXiv's own instructions say of the abstract field: "Keep it short -- abstracts
longer than 1920 characters will not be accepted; abridge your abstract if
necessary" (https://info.arxiv.org/help/prep.html). That is a hard limit on the
*metadata field*, not on the PDF, so the paper's in-document abstract is free to
be as long as it likes -- and it is, at roughly 4,150 characters. What that
means in practice is that the text pasted into the submission form cannot be the
text in the PDF, and the form's copy therefore needs to exist somewhere and stay
correct. ``paper/abstract-arxiv.txt`` is that copy.

Nothing here judges the prose. These are the mechanical rules the form enforces,
each of which would be discovered at submission time otherwise: the length cap,
no TeX macros ("Omit these TeX-isms"), no unicode ("unicode not supported"), and
no leading "Abstract" ("Do not include the word Abstract").
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABSTRACT = ROOT / "paper" / "abstract-arxiv.txt"
LIMIT = 1920


def submitted_form() -> str:
    """The abstract as the form receives it.

    arXiv states that "carriage returns will be stripped unless they are
    followed by leading white spaces", so a hard-wrapped file is joined into
    single-spaced text before its length is counted. Counting the raw file
    instead would over-count by one character per line and could reject a
    submittable abstract, or -- worse, since the paragraph breaks here are
    indented by nothing -- pass one that is over.
    """
    return re.sub(r"\n(?!\s)", " ", ABSTRACT.read_text()).strip()


def test_abstract_file_exists() -> None:
    """Mutation: delete the file and the guard below would vacuously pass on an
    empty string, so the existence check is separate and comes first."""
    assert ABSTRACT.is_file(), f"{ABSTRACT} is missing"
    assert submitted_form(), "the abstract file is empty"


def test_abstract_fits_the_arxiv_field() -> None:
    """The one that matters. Mutation: paste the PDF's abstract in here (4,145
    characters) and submission fails at the form with no local warning."""
    text = submitted_form()
    assert len(text) <= LIMIT, (
        f"abstract is {len(text)} characters as submitted; arXiv rejects "
        f"anything over {LIMIT}. Abridge paper/abstract-arxiv.txt."
    )


def test_abstract_has_no_texisms() -> None:
    """arXiv: "Omit these TeX-isms". A stray \\emph{} reaches the listing as
    literal source. Mutation: copy a sentence over from main.tex, which is full
    of \\texttt and $math$, and this fires."""
    raw = ABSTRACT.read_text()
    assert "\\" not in raw, "TeX macros in the metadata abstract"
    assert "$" not in raw, "math mode in the metadata abstract"


def test_abstract_is_ascii() -> None:
    """arXiv: "unicode not supported". The trap is invisible -- an em-dash or a
    curly quote pasted from an editor looks identical in a diff review."""
    raw = ABSTRACT.read_text()
    offenders = sorted({c for c in raw if ord(c) > 127})
    assert not offenders, f"non-ASCII characters in the metadata abstract: {offenders}"


def test_abstract_does_not_repeat_the_word_abstract() -> None:
    """arXiv: "Do not include the word Abstract"."""
    assert not submitted_form().lower().startswith("abstract"), (
        "the metadata abstract starts with the word 'Abstract'"
    )
