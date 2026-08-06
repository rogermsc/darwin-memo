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


def test_exact_match_applies():
    edit = Edit(
        path="a.py",
        search="        value = compute()",
        replace="        value = compute(strict=True)",
    )
    result = apply_edits({"a.py": SOURCE}, [edit])
    assert (result.applied, result.failed) == (1, 0)
    assert "compute(strict=True)" in result.new_texts["a.py"]


def test_trailing_whitespace_difference_is_tolerated():
    source = "def f():\n    return 1   \n"
    edit = Edit(path="a.py", search="    return 1", replace="    return 2")
    result = apply_edits({"a.py": source}, [edit])
    assert result.applied == 1
    assert "return 2" in result.new_texts["a.py"]


def test_exact_substring_match_takes_the_first_occurrence():
    """Pre-existing behaviour, pinned because it is a live hazard.

    Exact matching is substring-based, so a single-line SEARCH matches
    inside an indented line and a repeated line resolves to whichever
    comes first. A wrong-but-appliable patch is worse than a failed
    edit, and this is where one would come from.
    """
    source = "def a():\n    x = 1\ndef b():\n    x = 1\n"
    edit = Edit(path="a.py", search="x = 1", replace="x = 2")
    result = apply_edits({"a.py": source}, [edit])
    assert (result.applied, result.failed) == (1, 0)
    assert result.new_texts["a.py"] == "def a():\n    x = 2\ndef b():\n    x = 1\n"


def test_unknown_path_fails_without_touching_anything():
    edit = Edit(path="missing.py", search="x", replace="y")
    result = apply_edits({"a.py": SOURCE}, [edit])
    assert (result.applied, result.failed) == (0, 1)
    assert result.new_texts == {"a.py": SOURCE}


def test_missing_final_newline_is_not_invented():
    source = "a = 1\nb = 2"  # no trailing newline
    edit = Edit(path="a.py", search="b = 2", replace="b = 3")
    result = apply_edits({"a.py": source}, [edit])
    assert result.new_texts["a.py"] == "a = 1\nb = 3"


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


def test_a_whitespace_shifted_search_now_fails():
    """Pins the removal of the whitespace-tolerant retry.

    A SEARCH that kept the block's shape but dropped its indentation
    used to be recovered. It is now a plain failure. The retry existed
    on the theory that indentation was a common failure mode; it fired
    zero times in 3,015 evaluated tasks, so the edits that fail do so
    because the model was handed the wrong file, not the wrong columns.
    """
    edit = Edit(
        path="a.py",
        search="value = compute()\nreturn value",
        replace="value = compute()\nreturn value * 2",
    )
    result = apply_edits({"a.py": SOURCE}, [edit])
    assert (result.applied, result.failed) == (0, 1)
    assert result.new_texts["a.py"] == SOURCE


def test_edits_to_patch_returns_patch_applied_failed():
    """The runner's entrypoint, on an exact match."""
    response = (
        "a.py\n"
        "<<<<<<< SEARCH\n"
        "        value = compute()\n"
        "=======\n"
        "        value = compute(strict=True)\n"
        ">>>>>>> REPLACE\n"
    )
    patch, applied, failed = edits_to_patch({"a.py": SOURCE}, response)
    assert (applied, failed) == (1, 0)
    assert patch.startswith("--- a/a.py")
    assert "+        value = compute(strict=True)" in patch
