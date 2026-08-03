"""SEARCH/REPLACE application, including the whitespace-tolerant retry.

The retry exists because a model that reproduces a block's shape but not
its exact leading whitespace loses the entire task, which is a harness
artifact rather than a capability result. It is only safe while it
refuses to guess, so most of these cases are about what it declines to
do: ambiguous sites and garbled indentation must still fail.
"""

from __future__ import annotations

from bench.swebench_cl.edits import (
    Edit,
    apply_edits,
    edits_to_patch,
    make_diff,
    parse_edits,
)

SOURCE = """class Thing:
    def run(self):
        value = compute()
        return value
"""


def test_exact_match_applies_without_the_fallback():
    edit = Edit(
        path="a.py",
        search="        value = compute()",
        replace="        value = compute(strict=True)",
    )
    result = apply_edits({"a.py": SOURCE}, [edit])
    assert (result.applied, result.failed, result.relaxed) == (1, 0, 0)
    assert "compute(strict=True)" in result.new_texts["a.py"]


def test_uniform_indent_shift_is_recovered_and_reindented():
    # The model dropped all eight spaces but kept the shape.
    edit = Edit(
        path="a.py",
        search="value = compute()\nreturn value",
        replace="value = compute()\nreturn value * 2",
    )
    result = apply_edits({"a.py": SOURCE}, [edit])
    assert (result.applied, result.failed, result.relaxed) == (1, 0, 1)
    # Re-indented to where it actually lands, not where the model thought.
    assert "        return value * 2\n" in result.new_texts["a.py"]
    assert "\nreturn value * 2" not in result.new_texts["a.py"]


def test_relative_indentation_is_preserved_under_a_shift():
    source = "def f():\n    if x:\n        go()\n"
    edit = Edit(
        path="a.py",
        search="if x:\n    go()",
        replace="if x:\n    go(fast=True)",
    )
    result = apply_edits({"a.py": source}, [edit])
    assert result.relaxed == 1
    assert result.new_texts["a.py"] == "def f():\n    if x:\n        go(fast=True)\n"


def test_trailing_whitespace_difference_is_tolerated():
    source = "def f():\n    return 1   \n"
    edit = Edit(path="a.py", search="    return 1", replace="    return 2")
    result = apply_edits({"a.py": source}, [edit])
    assert result.applied == 1
    assert "return 2" in result.new_texts["a.py"]


def test_ambiguous_site_is_refused():
    # Two sites whose stripped form is identical. Exact matching cannot
    # place it (the indentation differs mid-block), and the retry must
    # not pick one arbitrarily.
    source = "def a():\n    x = 1\n    y = 2\ndef b():\n        x = 1\n        y = 2\n"
    edit = Edit(path="a.py", search="x = 1\ny = 2", replace="x = 9\ny = 9")
    result = apply_edits({"a.py": source}, [edit])
    assert (result.applied, result.failed, result.relaxed) == (0, 1, 0)
    assert result.new_texts["a.py"] == source


def test_exact_substring_match_takes_the_first_occurrence():
    """Pre-existing behaviour, pinned because it is a live hazard.

    Exact matching is substring-based, so a single-line SEARCH matches
    inside an indented line and a repeated line resolves to whichever
    comes first. The retry's uniqueness guard never sees these, because
    the exact path already succeeded. A wrong-but-appliable patch is
    worse than a failed edit, and this is where one would come from.
    """
    source = "def a():\n    x = 1\ndef b():\n    x = 1\n"
    edit = Edit(path="a.py", search="x = 1", replace="x = 2")
    result = apply_edits({"a.py": source}, [edit])
    assert (result.applied, result.failed, result.relaxed) == (1, 0, 0)
    assert result.new_texts["a.py"] == "def a():\n    x = 2\ndef b():\n    x = 1\n"


def test_garbled_internal_indentation_is_refused():
    # Line 1 needs an 8-space prefix, line 2 would need 4: not one shift,
    # so re-indenting would be invention.
    source = "class C:\n    def f(self):\n        a = 1\n        b = 2\n"
    edit = Edit(path="a.py", search="a = 1\n    b = 2", replace="a = 9\n    b = 9")
    result = apply_edits({"a.py": source}, [edit])
    assert (result.applied, result.failed, result.relaxed) == (0, 1, 0)


def test_unknown_path_fails_without_touching_anything():
    edit = Edit(path="missing.py", search="x", replace="y")
    result = apply_edits({"a.py": SOURCE}, [edit])
    assert (result.applied, result.failed) == (0, 1)
    assert result.new_texts == {"a.py": SOURCE}


def test_blank_lines_do_not_constrain_the_shift():
    source = "def f():\n    a = 1\n\n    b = 2\n"
    edit = Edit(path="a.py", search="a = 1\n\nb = 2", replace="a = 1\n\nb = 3")
    result = apply_edits({"a.py": source}, [edit])
    assert result.relaxed == 1
    assert result.new_texts["a.py"] == "def f():\n    a = 1\n\n    b = 3\n"


def test_relaxed_deletion_removes_whole_lines():
    edit = Edit(path="a.py", search="value = compute()\nreturn value", replace="")
    result = apply_edits({"a.py": SOURCE}, [edit])
    assert result.relaxed == 1
    # Both lines gone, not blanked: no whitespace-only remnant left behind.
    assert result.new_texts["a.py"] == "class Thing:\n    def run(self):\n"


def test_missing_final_newline_is_not_invented():
    source = "a = 1\nb = 2"  # no trailing newline
    edit = Edit(path="a.py", search="b = 2", replace="b = 3")
    result = apply_edits({"a.py": source}, [edit])
    assert result.new_texts["a.py"] == "a = 1\nb = 3"


def test_relaxed_edit_produces_an_appliable_diff():
    response = (
        "a.py\n"
        "<<<<<<< SEARCH\n"
        "value = compute()\n"
        "return value\n"
        "=======\n"
        "value = compute(strict=True)\n"
        "return value\n"
        ">>>>>>> REPLACE\n"
    )
    patch, applied, failed, relaxed = edits_to_patch({"a.py": SOURCE}, response)
    assert (applied, failed, relaxed) == (1, 0, 1)
    assert patch.startswith("--- a/a.py")
    # The changed line carries the file's real indentation.
    assert "+        value = compute(strict=True)" in patch


def test_second_edit_sees_the_first_edits_result():
    edits = [
        Edit(path="a.py", search="value = compute()", replace="value = fetch()"),
        Edit(path="a.py", search="value = fetch()", replace="value = fetch(1)"),
    ]
    result = apply_edits({"a.py": SOURCE}, edits)
    assert result.applied == 2
    assert "fetch(1)" in result.new_texts["a.py"]


def test_parse_edits_reads_a_block():
    (edit,) = parse_edits(
        "pkg/mod.py\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\n"
    )
    assert (edit.path, edit.search, edit.replace) == ("pkg/mod.py", "old", "new")


def test_make_diff_skips_unchanged_files():
    assert make_diff({"a.py": SOURCE}, {"a.py": SOURCE}) == ""
