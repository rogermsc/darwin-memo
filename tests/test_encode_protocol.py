from darwin_memo import (
    Document,
    LocalEncoder,
    MemoryStore,
    QueryProtocol,
    decision_polarity,
)

DOC_A = Document(
    doc_id="runbook",
    text=(
        "Old log files under logs/ may be deleted after seven days. "
        "Cache files are disposable and safe to remove. "
        "Database files under data/ are protected by the Platform Team "
        "and must be retained."
    ),
)
DOC_B = Document(
    doc_id="policy",
    text=(
        "Database files are backed up nightly by the Platform Team. "
        "Quarterly reports must be kept for five years."
    ),
)


def test_local_encoder_produces_self_contained_entries():
    entries = LocalEncoder().encode([DOC_A, DOC_B])
    assert entries
    kinds = {e.kind.value for e in entries}
    assert "explicit" in kinds
    for entry in entries:
        assert entry.question.strip()
        assert entry.answer.strip()
        assert entry.sources


def test_local_encoder_finds_cross_document_entities():
    entries = LocalEncoder().encode([DOC_A, DOC_B])
    cross = [e for e in entries if e.kind.value == "cross_doc"]
    assert cross, (
        "Platform Team appears in both docs, so a cross_doc entry should exist"
    )
    assert any(len(e.sources) >= 2 for e in cross)


def test_protocol_local_mode_reports_provenance():
    store = MemoryStore()
    for entry in LocalEncoder().encode([DOC_A, DOC_B]):
        store.add(entry)
    protocol = QueryProtocol(store)

    answer = protocol.answer("Is it safe to delete a database file under data/?")
    assert answer.text
    assert answer.deciding_entry is not None
    assert store.get(answer.deciding_entry) is not None


def test_decision_polarity():
    assert decision_polarity("Old logs may be deleted after seven days.") is True
    assert (
        decision_polarity("Database files are protected and must be retained.") is False
    )
    assert decision_polarity("These are redundant and safe to remove.") is True
    assert decision_polarity("") is None
    assert decision_polarity("The weather is nice.") is None
    # Negative markers win when both polarities appear.
    assert (
        decision_polarity("Caches are disposable but these ones must be kept.") is False
    )


def test_parse_json_array_strips_think_blocks():
    """Reasoning text is never data: brackets inside <think> must not
    poison the greedy array match (measured 0% -> 100% encoding
    validity on qwen3:30b-a3b)."""
    from darwin_memo.llm import parse_json_array

    raw = (
        "<think>\nFacts: [1] the file, [2] the policy...\n"
        "Let me draft the array.\n</think>\n"
        '[{"question": "What about logs?", "answer": "Deletable.", '
        '"kind": "explicit"}]'
    )
    parsed = parse_json_array(raw)
    assert parsed == [
        {"question": "What about logs?", "answer": "Deletable.", "kind": "explicit"}
    ]
    assert parse_json_array("<think>only [reasoning] here</think>no array") == []
