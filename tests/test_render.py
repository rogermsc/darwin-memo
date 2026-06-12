"""Rendering: budget-capped MEMORY.md for Claude Code auto memory."""

from pathlib import Path

import pytest

from darwin_memo import EntryKind, MemoryEntry, MemoryStore
from darwin_memo.cli import main as cli_main
from darwin_memo.render import (
    DEFAULT_MAX_LINES,
    parse_budget,
    ranked_living,
    render_store,
)

_KINDS = [EntryKind.EXPERIENCE, EntryKind.EXPLICIT, EntryKind.INFERRED]


def seeded_store(tmp_path, n=12):
    """A saved store of n entries with distinct balances, kinds, and ids."""
    store = MemoryStore()
    for i in range(n):
        store.add(
            MemoryEntry(
                question=f"Question {i}?",
                answer=f"Lesson {i}: " + "keep the helper honest " * (i % 4 + 1),
                kind=_KINDS[i % 3],
                energy=float(n - i),
                last_used_cycle=i if i % 2 == 0 else -1,
                id=chr(ord("a") + i) * 12,
            )
        )
    path = tmp_path / "memory.json"
    store.save(path)
    return path, store


# ----------------------------------------------------------------------
# The budget invariant
# ----------------------------------------------------------------------


@pytest.mark.parametrize("budget", [50, 120, 300, 700, 1500, 4096, 25 * 1024])
def test_budget_never_exceeded_single_file(tmp_path, budget):
    path, _ = seeded_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    summary = render_store(path, out, budget)
    assert out.stat().st_size <= budget, "the hard cap holds at every budget"
    assert summary["bytes"] == out.stat().st_size


@pytest.mark.parametrize("budget", [120, 700, 1500, 25 * 1024])
def test_budget_never_exceeded_split_mode(tmp_path, budget):
    path, _ = seeded_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    summary = render_store(path, out, budget, split_dir=tmp_path / "memory")
    assert out.stat().st_size <= budget, "the index obeys the budget"
    for topic in summary["topics"]:
        size = Path(topic["path"]).stat().st_size
        assert size <= topic["budget"] <= budget, "each topic obeys its share"


def test_greedy_packing_skips_oversized_keeps_smaller(tmp_path):
    store = MemoryStore()
    store.add(MemoryEntry(question="big", answer="x" * 3000, energy=5.0, id="a" * 12))
    store.add(
        MemoryEntry(
            question="small", answer="Small lesson survives.", energy=4.0, id="b" * 12
        )
    )
    path = tmp_path / "memory.json"
    store.save(path)
    out = tmp_path / "MEMORY.md"
    summary = render_store(path, out, 500)
    assert summary["shown"] == 1 and summary["living"] == 2
    text = out.read_text()
    assert "Small lesson survives." in text and "xxx" not in text
    assert "1 of 2 living entries shown" in text, "the header counts honestly"


# ----------------------------------------------------------------------
# The line cap: Claude Code stops at min(200 lines, 25KB)
# ----------------------------------------------------------------------


def short_lesson_store(tmp_path, n=400):
    """Hundreds of short entries: lines run out long before bytes do."""
    store = MemoryStore()
    for i in range(n):
        store.add(
            MemoryEntry(
                question=f"q{i}",
                answer=f"Short lesson {i}.",
                energy=float(n - i),
                id=f"{i:012d}",
            )
        )
    path = tmp_path / "memory.json"
    store.save(path)
    return path


def test_default_render_never_exceeds_200_lines(tmp_path):
    path = short_lesson_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    summary = render_store(path, out, 25 * 1024)
    text = out.read_text()
    assert len(text.splitlines()) <= DEFAULT_MAX_LINES, "every shown entry is read"
    assert summary["lines"] == len(text.splitlines())
    assert text.count("(id ") == summary["shown"], "shown counts only readable entries"
    assert summary["shown"] < summary["living"], "the line cap actually bound here"


def test_line_cap_flag_reaches_the_renderer(tmp_path):
    path = short_lesson_store(tmp_path, n=40)
    out = tmp_path / "MEMORY.md"
    argv = ["render", str(path), "-o", str(out), "--max-lines", "12"]
    assert cli_main(argv) == 0
    assert len(out.read_text().splitlines()) <= 12


def test_split_mode_index_obeys_the_line_cap(tmp_path):
    path, _ = seeded_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    summary = render_store(
        path, out, 25 * 1024, split_dir=tmp_path / "memory", max_lines=4
    )
    assert len(out.read_text().splitlines()) <= 4
    assert summary["lines"] == len(out.read_text().splitlines())


def test_line_cap_holds_even_below_the_header_size(tmp_path):
    path, _ = seeded_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    summary = render_store(path, out, 25 * 1024, max_lines=2)
    assert summary["shown"] == 0
    assert len(out.read_text().splitlines()) <= 2, "the last-resort cut holds"


def test_cli_rejects_nonpositive_max_lines(tmp_path, capsys):
    out = tmp_path / "MEMORY.md"
    argv = ["render", str(tmp_path / "m.json"), "-o", str(out), "--max-lines", "0"]
    assert cli_main(argv) == 1
    assert "max-lines" in capsys.readouterr().err
    assert not out.exists()


# ----------------------------------------------------------------------
# Ordering: balance first, id tiebreak, strongest group leads
# ----------------------------------------------------------------------


def test_orders_by_balance_with_id_tiebreak(tmp_path):
    store = MemoryStore()
    store.add(
        MemoryEntry(question="q1", answer="Strongest lesson.", energy=4.0, id="c" * 12)
    )
    store.add(
        MemoryEntry(question="q2", answer="Tied lesson b.", energy=2.0, id="b" * 12)
    )
    store.add(
        MemoryEntry(question="q3", answer="Tied lesson a.", energy=2.0, id="a" * 12)
    )
    assert [e.id[0] for e in ranked_living(store)] == ["c", "a", "b"]

    path = tmp_path / "memory.json"
    store.save(path)
    out = tmp_path / "MEMORY.md"
    render_store(path, out, 25 * 1024)
    text = out.read_text()
    assert text.index("cccccccc") < text.index("aaaaaaaa") < text.index("bbbbbbbb")


def test_highest_balance_entry_renders_first(tmp_path):
    path, store = seeded_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    render_store(path, out, 25 * 1024)
    lines = out.read_text().splitlines()
    top = max(store.alive(), key=lambda e: e.energy)
    first_block = next(line for line in lines if line.startswith("- "))
    assert top.answer.split(":")[0] in first_block, "top balance leads the file"
    provenance = lines[lines.index(first_block) + 1]
    assert f"id {top.id[:8]}" in provenance
    assert f"balance {top.energy:.3f}" in provenance
    assert f"last settle t{top.last_used_cycle}" in provenance


def test_never_settled_entries_say_never(tmp_path):
    path, _ = seeded_store(tmp_path, n=2)
    out = tmp_path / "MEMORY.md"
    render_store(path, out, 25 * 1024)
    assert "last settle never" in out.read_text()


# ----------------------------------------------------------------------
# Split mode
# ----------------------------------------------------------------------


def test_split_mode_index_links_topic_files(tmp_path):
    path, _ = seeded_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    summary = render_store(path, out, 25 * 1024, split_dir=tmp_path / "memory")
    index = out.read_text()
    assert len(summary["topics"]) == len(_KINDS)
    assert index.count("- [") == len(summary["topics"]), "one line per topic"
    for topic in summary["topics"]:
        topic_path = Path(topic["path"])
        assert topic_path.exists()
        assert f"]({topic_path.parent.name}/{topic['topic']}.md)" in index
        body = topic_path.read_text()
        assert f"topic {topic['topic']}" in body
        assert body.count("(id ") == topic["shown"]
    assert summary["shown"] == sum(t["shown"] for t in summary["topics"])


@pytest.mark.parametrize("budget", [180, 260, 400])
def test_small_budget_index_links_exactly_what_it_claims(tmp_path, budget):
    path, _ = seeded_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    split = tmp_path / "memory"
    summary = render_store(path, out, budget, split_dir=split)
    index = out.read_text()
    on_disk = sorted(p.name for p in split.iterdir())
    linked = sorted(f"{t['topic']}.md" for t in summary["topics"])
    assert on_disk == linked, "every file on disk is linked from the index"
    assert index.count("- [") == len(summary["topics"])
    assert f"index of {len(summary['topics'])} topics" in index
    assert summary["shown"] == sum(t["shown"] for t in summary["topics"])


# ----------------------------------------------------------------------
# Stale topic files: a re-render leaves no dead lessons behind
# ----------------------------------------------------------------------


def test_split_rerender_deletes_topic_files_for_dead_kinds(tmp_path):
    path, _ = seeded_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    split = tmp_path / "memory"
    render_store(path, out, 25 * 1024, split_dir=split)
    assert (split / "explicit.md").exists()

    survivor_only = MemoryStore()
    survivor_only.add(
        MemoryEntry(
            question="q",
            answer="Last kind standing.",
            kind=EntryKind.EXPERIENCE,
            energy=3.0,
            id="z" * 12,
        )
    )
    survivor_only.save(path)
    render_store(path, out, 25 * 1024, split_dir=split)
    assert not (split / "explicit.md").exists(), "dead kinds leave no file behind"
    assert not (split / "inferred.md").exists()
    assert (split / "experience.md").exists()
    assert "explicit" not in out.read_text()


def test_zero_living_split_rerender_clears_all_topic_files(tmp_path):
    path, _ = seeded_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    split = tmp_path / "memory"
    render_store(path, out, 25 * 1024, split_dir=split)
    assert any(split.iterdir())

    dead = MemoryStore()
    dead.add(MemoryEntry(question="q", answer="starved", energy=0.0, id="a" * 12))
    dead.save(path)
    summary = render_store(path, out, 25 * 1024, split_dir=split)
    assert summary["living"] == 0 and summary["topics"] == []
    assert list(split.iterdir()) == [], "an empty world leaves no topic files"
    assert "no living entries" in out.read_text()


def test_missing_store_rerender_clears_stale_topic_files(tmp_path):
    path, _ = seeded_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    split = tmp_path / "memory"
    render_store(path, out, 25 * 1024, split_dir=split)
    path.unlink()
    render_store(path, out, 25 * 1024, split_dir=split)
    assert list(split.iterdir()) == []
    assert "store not found" in out.read_text()


# ----------------------------------------------------------------------
# Budget parsing
# ----------------------------------------------------------------------


def test_parse_budget_forms():
    assert parse_budget("25kb") == 25 * 1024
    assert parse_budget("25KB") == 25 * 1024
    assert parse_budget("8000") == 8000
    assert parse_budget("1.5kb") == 1536
    assert parse_budget("1mb") == 1024 * 1024
    for bad in ("", "kb", "25 furlongs", "0", "-3kb"):
        with pytest.raises(ValueError):
            parse_budget(bad)


def test_cli_rejects_bad_budget_before_touching_files(tmp_path, capsys):
    out = tmp_path / "MEMORY.md"
    argv = ["render", str(tmp_path / "m.json"), "-o", str(out), "--budget", "nope"]
    assert cli_main(argv) == 1
    assert "budget" in capsys.readouterr().err
    assert not out.exists()


# ----------------------------------------------------------------------
# Stale store guard
# ----------------------------------------------------------------------


def test_missing_store_writes_minimal_honest_file(tmp_path, capsys):
    out = tmp_path / "MEMORY.md"
    assert cli_main(["render", str(tmp_path / "nope.json"), "-o", str(out)]) == 0
    assert "store not found" in out.read_text()
    assert "rendered 0 of 0 living entries" in capsys.readouterr().out


def test_zero_living_entries_writes_minimal_honest_file(tmp_path):
    store = MemoryStore()
    store.add(MemoryEntry(question="q", answer="starved", energy=0.0, id="a" * 12))
    path = tmp_path / "memory.json"
    store.save(path)
    out = tmp_path / "MEMORY.md"
    summary = render_store(path, out, 1024, split_dir=tmp_path / "memory")
    assert summary["shown"] == 0 and summary["living"] == 0
    assert summary["topics"] == [], "no topic files for an empty world"
    assert "no living entries" in out.read_text()


@pytest.mark.parametrize("garbage", ["", "{not json", "[]"])
def test_unreadable_store_exits_cleanly_keeping_previous_render(
    tmp_path, capsys, garbage
):
    path = tmp_path / "memory.json"
    path.write_text(garbage)
    out = tmp_path / "MEMORY.md"
    out.write_text("the last good render\n")
    assert cli_main(["render", str(path), "-o", str(out)]) == 1
    assert "cannot read store" in capsys.readouterr().err
    assert out.read_text() == "the last good render\n", "previous render untouched"


def test_render_store_raises_value_error_for_unreadable_store(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("")
    with pytest.raises(ValueError, match="cannot read store"):
        render_store(path, tmp_path / "MEMORY.md", 1024)


# ----------------------------------------------------------------------
# Determinism
# ----------------------------------------------------------------------


def test_two_renders_are_byte_identical(tmp_path):
    path, _ = seeded_store(tmp_path)
    first, second = tmp_path / "a.md", tmp_path / "b.md"
    render_store(path, first, 600)
    render_store(path, second, 600)
    assert first.read_bytes() == second.read_bytes()

    render_store(path, first, 2048, split_dir=tmp_path / "t1")
    render_store(path, second, 2048, split_dir=tmp_path / "t2")
    for topic in (tmp_path / "t1").iterdir():
        twin = tmp_path / "t2" / topic.name
        assert topic.read_bytes() == twin.read_bytes()


def test_cli_render_reports_the_written_accounting(tmp_path, capsys):
    path, _ = seeded_store(tmp_path)
    out = tmp_path / "MEMORY.md"
    argv = ["render", str(path), "-o", str(out), "--budget", "2kb"]
    assert cli_main(argv) == 0
    line = capsys.readouterr().out
    assert "budget 2048" in line and str(out) in line
    assert out.stat().st_size <= 2048

    split = ["render", str(path), "-o", str(out), "--split-dir", str(tmp_path / "m")]
    assert cli_main(split) == 0
    assert "experience" in capsys.readouterr().out
