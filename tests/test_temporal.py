"""Temporal awareness: age rendering, recency ranking, conflict surfacing."""

import json
from datetime import datetime
from typing import Any

import pytest

from darwin_memo import (
    CONFLICT_HEADER,
    DEFAULT_MERGE_THRESHOLD,
    EntryKind,
    Ledger,
    MemoryEntry,
    MemoryStore,
    QueryProtocol,
    SurvivalConfig,
    age_annotation,
    conflict_clusters,
    consolidate,
    newest_first,
    recency_weight,
)
from darwin_memo.cli import main as cli_main

FLAG_QUERY = "are stale feature flags safe to remove?"


def flag_entry(**overrides: Any) -> MemoryEntry:
    """A retrievable flag entry; overrides shape the temporal fields."""
    fields: dict[str, Any] = {
        "question": "What about stale feature flags?",
        "answer": "Stale feature flags are redundant and safe to remove.",
    }
    fields.update(overrides)
    return MemoryEntry(**fields)


# ---------------------------------------------------------------------------
# Age rendering
# ---------------------------------------------------------------------------


def test_age_annotation_with_recorded_ts():
    entry = flag_entry(
        born_cycle=3,
        recorded_ts="2026-06-12T10:00:00+00:00",
        last_used_cycle=7,
    )
    line = age_annotation(entry)
    assert "recorded 2026-06-12T10:00:00+00:00" in line
    assert "born tick 3" in line
    assert "last settled tick 7" in line


def test_age_annotation_without_recorded_ts():
    line = age_annotation(flag_entry(recorded_ts=""))
    assert "age unknown" in line
    assert "never settled" in line
    assert "recorded" not in line


def test_new_entries_stamp_utc_now():
    parsed = datetime.fromisoformat(flag_entry().recorded_ts)
    offset = parsed.utcoffset()
    assert offset is not None and offset.total_seconds() == 0, "UTC, not local"


def test_local_answer_carries_age_annotation():
    store = MemoryStore()
    entry = store.add(flag_entry())
    answer = QueryProtocol(store).answer(FLAG_QUERY)
    assert answer.text == entry.answer, "acting text stays the raw answer"
    assert answer.annotated_text == f"{entry.answer}\n{age_annotation(entry)}"


def test_ledger_decide_answer_carries_age_annotation():
    store = MemoryStore()
    store.add(flag_entry())
    ticket = Ledger(store).decide(FLAG_QUERY)
    assert "[recorded " in ticket.answer
    assert "born tick 0" in ticket.answer


# ---------------------------------------------------------------------------
# Backward compatibility: files saved before recorded_ts existed
# ---------------------------------------------------------------------------


def test_legacy_store_file_lacking_new_fields_loads_age_unknown(tmp_path):
    """A 0.5.0-era file must load, and must not fake a timestamp."""
    payload = {
        "config": {"max_energy": 5.0, "upkeep": 0.05},
        "entries": [
            {
                "question": "What about database files?",
                "answer": "Database files must be retained.",
                "kind": "explicit",
                "sources": ["runbook"],
                "energy": 1.0,
                "born_cycle": 0,
                "last_used_cycle": -1,
                "uses": 0,
                "lineage": [],
                "id": "legacy000001",
            }
        ],
        "graveyard": [],
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload))

    store = MemoryStore.load(path)
    entry = store.get("legacy000001")
    assert entry is not None
    assert entry.recorded_ts == ""
    assert "age unknown" in age_annotation(entry)

    # The legacy entry still retrieves, and its surface says so.
    answer = QueryProtocol(store).answer("are database files safe to delete?")
    assert "age unknown" in answer.annotated_text


# ---------------------------------------------------------------------------
# Recency-weighted ranking (opt-in half-life)
# ---------------------------------------------------------------------------


def stale_and_fresh_store() -> tuple[MemoryStore, MemoryEntry, MemoryEntry]:
    """Identical QA text, so relevance ties and energy breaks the tie:
    the stale entry wins by default and only recency can flip it."""
    store = MemoryStore()
    stale = store.add(flag_entry(energy=2.0, born_cycle=0))
    fresh = store.add(flag_entry(energy=1.0, born_cycle=10, last_used_cycle=10))
    return store, stale, fresh


def test_half_life_flips_ranking_order():
    store, stale, fresh = stale_and_fresh_store()
    plain = store.retrieve(FLAG_QUERY, k=2)
    assert [e.id for e, _ in plain] == [stale.id, fresh.id], "energy tie-break"

    decayed = store.retrieve(FLAG_QUERY, k=2, half_life=2.0, now_cycle=10)
    assert [e.id for e, _ in decayed] == [fresh.id, stale.id], "recency wins"


def test_half_life_now_cycle_defaults_to_latest_known_tick():
    store, stale, fresh = stale_and_fresh_store()
    decayed = store.retrieve(FLAG_QUERY, k=2, half_life=2.0)
    assert [e.id for e, _ in decayed] == [fresh.id, stale.id]


def test_recency_ranking_never_touches_balances():
    store, _, _ = stale_and_fresh_store()
    before = {e.id: (e.energy, e.uses, e.last_used_cycle) for e in store.alive()}
    store.retrieve(FLAG_QUERY, k=2, half_life=1.0, now_cycle=50)
    after = {e.id: (e.energy, e.uses, e.last_used_cycle) for e in store.alive()}
    assert after == before, "ranking decay is display-side only"


def test_recency_option_leaves_settlement_credit_unchanged():
    """The same decide/settle cycle moves the same energy with and
    without the recency option: credit never sees the decay."""

    def settled_energy(half_life):
        store = MemoryStore()
        store.add(flag_entry())
        ledger = Ledger(store, resource_scale=2.0)
        ticket = ledger.decide(FLAG_QUERY, half_life=half_life)
        ledger.settle(ticket.id, delta=2.0)
        return store.total_energy()

    assert settled_energy(None) == settled_energy(5.0)


def test_non_positive_half_life_raises():
    """Asking for recency and silently getting none would be a fake
    success: a decay rate at or below zero is refused, never ignored."""
    store, _, _ = stale_and_fresh_store()
    for bad in (0.0, -3.0):
        with pytest.raises(ValueError):
            store.retrieve(FLAG_QUERY, k=2, half_life=bad)
        with pytest.raises(ValueError):
            recency_weight(flag_entry(), now_cycle=5, half_life=bad)


def test_cli_half_life_rejects_non_positive(tmp_path, capsys):
    store = MemoryStore()
    store.add(flag_entry())
    memory = tmp_path / "m.json"
    store.save(memory)
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["query", str(memory), FLAG_QUERY, "--half-life", "0"])
    assert excinfo.value.code == 2
    assert "must be positive" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Conflict surfacing
# ---------------------------------------------------------------------------


def conflicting_pair_store() -> tuple[MemoryStore, MemoryEntry, MemoryEntry]:
    store = MemoryStore()
    older = store.add(flag_entry(recorded_ts="2026-01-01T00:00:00+00:00", born_cycle=0))
    newer = store.add(
        flag_entry(
            answer="Stale feature flags are not safe to remove.",
            recorded_ts="2026-06-01T00:00:00+00:00",
            born_cycle=9,
        )
    )
    return store, older, newer


def test_conflict_group_surfaces_dated_and_newest_first():
    store, older, newer = conflicting_pair_store()
    assert store.similarity(older, newer) >= 0.55, "fixture must overlap"

    answer = QueryProtocol(store).answer(FLAG_QUERY)
    text = answer.annotated_text
    assert text.startswith(CONFLICT_HEADER)
    assert text.index(newer.answer) < text.index(older.answer), "newest first"
    assert "recorded 2026-06-01T00:00:00+00:00" in text
    assert "recorded 2026-01-01T00:00:00+00:00" in text
    # Provenance and the acting text still come from the top hit alone.
    assert answer.text == older.answer
    assert answer.deciding_entry == older.id


def test_single_hit_gets_age_line_not_conflict_block():
    store = MemoryStore()
    entry = store.add(flag_entry())
    answer = QueryProtocol(store).answer(FLAG_QUERY)
    assert CONFLICT_HEADER not in answer.annotated_text
    assert answer.annotated_text == f"{entry.answer}\n{age_annotation(entry)}"


def test_conflict_clusters_groups_only_near_duplicates():
    store, older, newer = conflicting_pair_store()
    distinct = store.add(
        MemoryEntry(
            question="Is the schema helper load-bearing?",
            answer="The schema helper is load-bearing and must be kept.",
        )
    )
    clusters = conflict_clusters(
        [older, newer, distinct], store.similarity, threshold=0.55
    )
    assert clusters == [[newer, older]], "one cluster, newest first, no loner"


def test_newest_first_sorts_missing_ts_oldest():
    dated = flag_entry(recorded_ts="2026-06-01T00:00:00+00:00", born_cycle=0)
    undated = flag_entry(recorded_ts="", born_cycle=99)
    assert newest_first([undated, dated]) == [dated, undated]


def test_ledger_default_protocol_conflict_threshold_follows_config():
    """One ledger, one meaning of near-duplicate: a config that raises
    merge_threshold (cosine retrievers) raises conflict surfacing too."""
    store = MemoryStore()
    assert Ledger(store).protocol.conflict_threshold == DEFAULT_MERGE_THRESHOLD
    raised = Ledger(store, config=SurvivalConfig(merge_threshold=0.9))
    assert raised.protocol.conflict_threshold == 0.9


def consolidated_entry(store: MemoryStore) -> MemoryEntry:
    merges = consolidate(store, cycle=12)
    assert merges == 1
    merged = [e for e in store.alive() if e.kind == EntryKind.CONSOLIDATED]
    assert len(merged) == 1
    return merged[0]


def test_consolidated_entry_keeps_newest_member_timestamp():
    """Merging must not reset the age clock: stamping merge time would
    make stale advice look current on every consult surface."""
    store, _older, newer = conflicting_pair_store()
    merged = consolidated_entry(store)
    assert merged.recorded_ts == newer.recorded_ts
    assert "recorded 2026-06-01T00:00:00+00:00" in age_annotation(merged)


def test_consolidated_legacy_entries_stay_age_unknown():
    store = MemoryStore()
    store.add(flag_entry(recorded_ts=""))
    store.add(
        flag_entry(
            recorded_ts="",
            answer="Stale feature flags are not safe to remove.",
        )
    )
    merged = consolidated_entry(store)
    assert merged.recorded_ts == ""
    assert "age unknown" in age_annotation(merged)


# ---------------------------------------------------------------------------
# Metadata filters
# ---------------------------------------------------------------------------


def kinded_store() -> tuple[MemoryStore, MemoryEntry, MemoryEntry]:
    store = MemoryStore()
    explicit = store.add(flag_entry(kind=EntryKind.EXPLICIT, sources=["runbook"]))
    experience = store.add(
        flag_entry(
            answer="Stale feature flags were removed once and tests stayed green.",
            kind=EntryKind.EXPERIENCE,
            sources=["agent"],
        )
    )
    return store, explicit, experience


def test_metadata_filters_compose_with_ranking():
    store, explicit, experience = kinded_store()
    assert {e.id for e, _ in store.retrieve(FLAG_QUERY, k=5)} == {
        explicit.id,
        experience.id,
    }
    assert [e.id for e, _ in store.retrieve(FLAG_QUERY, k=5, kind="experience")] == [
        experience.id
    ]
    assert [
        e.id for e, _ in store.retrieve(FLAG_QUERY, k=5, kind=EntryKind.EXPLICIT)
    ] == [explicit.id]
    assert [e.id for e, _ in store.retrieve(FLAG_QUERY, k=5, source="runbook")] == [
        explicit.id
    ]
    assert store.retrieve(FLAG_QUERY, k=5, kind="experience", source="runbook") == []


def test_metadata_filters_compose_with_half_life():
    store, _, _ = kinded_store()
    fresh_agent = store.add(
        flag_entry(kind=EntryKind.EXPERIENCE, sources=["agent"], born_cycle=20)
    )
    hits = store.retrieve(
        FLAG_QUERY, k=5, kind="experience", half_life=2.0, now_cycle=20
    )
    assert next(e.id for e, _ in hits) == fresh_agent.id
    assert all(e.kind is EntryKind.EXPERIENCE for e, _ in hits)


def test_unknown_kind_filter_raises():
    store, _, _ = kinded_store()
    with pytest.raises(ValueError):
        store.retrieve(FLAG_QUERY, kind="nonsense")


# ---------------------------------------------------------------------------
# LLM mode: ages and conflict notes travel inside the snippets
# ---------------------------------------------------------------------------


class ScriptedClient:
    """Returns canned completions in order, recording prompts."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str, system: str = "") -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def test_llm_snippets_carry_age_and_conflict_note():
    store, _, _ = conflicting_pair_store()
    client = ScriptedClient(
        ["stale feature flag policy", "Keep them for now.\nSOURCES: [1]"]
    )
    QueryProtocol(store, client).answer(FLAG_QUERY)
    prompt = client.prompts[-1]
    assert "[recorded 2026-01-01T00:00:00+00:00" in prompt
    assert "[recorded 2026-06-01T00:00:00+00:00" in prompt
    assert "conflicting/overlapping advice, newest first" in prompt


# ---------------------------------------------------------------------------
# CLI and MCP surfaces
# ---------------------------------------------------------------------------


def _ledger_json(capsys, argv):
    assert cli_main(argv) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_query_prints_age_annotation(tmp_path, capsys):
    store = MemoryStore()
    store.add(flag_entry())
    memory = tmp_path / "m.json"
    store.save(memory)

    assert cli_main(["query", str(memory), FLAG_QUERY, "--half-life", "5"]) == 0
    out = capsys.readouterr().out
    assert "[recorded " in out
    assert "born tick 0" in out


def test_cli_ledger_decide_temporal_flags(tmp_path, capsys):
    memory = str(tmp_path / "ledger.json")
    _ledger_json(
        capsys,
        [
            "ledger",
            memory,
            "add",
            "What about stale feature flags?",
            "Stale feature flags are redundant and safe to remove.",
            "--source",
            "runbook",
        ],
    )

    decided = _ledger_json(
        capsys,
        [
            "ledger",
            memory,
            "decide",
            FLAG_QUERY,
            "--half-life",
            "5",
            "--source",
            "runbook",
        ],
    )
    assert decided["answer"] and "[recorded " in decided["answer"]

    # ledger add writes EXPERIENCE entries, so an explicit-only filter
    # leaves memory silent instead of guessing.
    filtered = _ledger_json(
        capsys, ["ledger", memory, "decide", FLAG_QUERY, "--kind", "explicit"]
    )
    assert filtered == {"answer": None, "ticket_id": None, "silent": True}


def test_mcp_memory_query_accepts_half_life(tmp_path):
    pytest.importorskip("mcp")
    import asyncio

    from darwin_memo.mcp_server import build_server

    server = build_server(tmp_path / "memory.json", resource_scale=2.0)

    async def scenario():
        await server.call_tool(
            "memory_add",
            {
                "question": "What about stale feature flags?",
                "answer": "Stale feature flags are redundant and safe to remove.",
            },
        )
        blocks, _ = await server.call_tool(
            "memory_query", {"query": FLAG_QUERY, "half_life": 5.0}
        )
        payload = json.loads(blocks[0].text)
        assert payload["answer"] and "[recorded " in payload["answer"]

    asyncio.run(scenario())
