"""Regression tests for the max-effort review findings."""

import json

from darwin_memo import (
    Document,
    Ledger,
    LocalEncoder,
    MemoryStore,
    decision_polarity,
    demo_corpus,
)


def test_cross_ticket_escrow_survives_settlement(store_factory):
    """Settling one ticket must not bury an entry another ticket escrows."""
    store = store_factory(upkeep=1.0)  # death in one tick without escrow
    ledger = Ledger(store, resource_scale=1.0)

    a = ledger.decide("Are stale feature flags safe to remove?")
    b = ledger.decide("Are stale feature flags safe to remove?")
    assert set(a.provenance) & set(b.provenance), "shared provenance required"
    shared = a.provenance[0]

    ledger.tick(expire_after=None)  # drains below zero; escrow holds burial
    ledger.settle(a.id, 0.0)  # A's verdict: must NOT bury, B still pends

    assert store.get(shared) is not None, "entry still escrowed by B"

    ledger.settle(b.id, 50.0)  # B's exonerating verdict lands
    assert store.get(shared).alive, "late verdict revived the entry"


def test_settle_reports_dropped_outcomes(store_factory):
    ledger = Ledger(store_factory(), resource_scale=1.0)
    ticket = ledger.decide("Are stale feature flags safe to remove?")
    assert ledger.settle(ticket.id, 1.0) is True
    assert ledger.settle(ticket.id, 1.0) is False, "duplicate delivery"
    assert ledger.settle("nope", 1.0) is False, "unknown ticket"


def test_abandon_releases_escrow(store_factory):
    store = store_factory(upkeep=1.0)
    ledger = Ledger(store, resource_scale=1.0)
    ticket = ledger.decide("Are stale feature flags safe to remove?")
    assert ledger.abandon(ticket.id) is True
    assert not ledger.pending()
    ledger.tick(expire_after=None)
    # No escrow left: brutal upkeep buries normally.
    assert store.get(ticket.provenance[0]) is None


def test_ledger_save_load_round_trips_tickets(store_factory, tmp_path):
    """Tickets must survive the process that minted them."""
    path = tmp_path / "memory.json"
    store = store_factory()
    ledger = Ledger(store, resource_scale=2.0)
    ticket = ledger.decide("Are stale feature flags safe to remove?")
    ledger.tick()
    ledger.save(path)

    revived = Ledger.load(path, resource_scale=2.0)
    assert revived.tick_count == 1
    assert [t.id for t in revived.pending()] == [ticket.id]
    assert ticket.deciding_entry is not None
    deciding = revived.store.get(ticket.deciding_entry)
    assert deciding is not None
    before = deciding.energy
    assert revived.settle(ticket.id, 5.0) is True, "cross-process settle lands"
    assert deciding.energy > before

    # A plain store file (no ledger key) loads with fresh ledger state.
    store_only = tmp_path / "plain.json"
    store_factory().save(store_only)
    fresh = Ledger.load(store_only)
    assert fresh.tick_count == 0 and not fresh.pending()
    # And MemoryStore.load ignores the ledger key in a ledger file.
    assert len(MemoryStore.load(path)) == len(store)


def test_obituary_distinguishes_executed_from_starved(store_factory):
    store = store_factory(upkeep=0.6)
    ledger = Ledger(store, resource_scale=1.0)
    ticket = ledger.decide("Are stale feature flags safe to remove?")
    # Detail string trying to spoof the old substring matcher.
    ledger.settle(ticket.id, -5.0, detail="credit -999 applied to budget")
    ledger.tick()
    ledger.tick()

    punished = ticket.deciding_entry
    assert punished is not None
    starved = next(e for e in store.graveyard() if e.id != punished)
    assert "executed" in ledger.obituary(punished)
    assert "starved" in ledger.obituary(starved.id)


def test_atomic_save_leaves_no_partial_file(tmp_path, store_factory):
    path = tmp_path / "memory.json"
    store = store_factory()
    store.save(path)
    first = path.read_text()
    store.save(path)
    assert json.loads(path.read_text()), "valid JSON after rewrite"
    assert not (tmp_path / "memory.json.tmp").exists(), "temp file renamed away"
    assert json.loads(first), "previous snapshot was valid too"


def test_polarity_word_boundaries_and_negation():
    # "keep iterating" must not trigger the "keep it" negative marker.
    assert (
        decision_polarity(
            "Yes, delete it, and keep iterating on the cleanup. The cache "
            "files are disposable."
        )
        is True
    )
    # "unprotected" must not trigger "protected".
    assert (
        decision_polarity("These scratch files are unprotected and safe to remove.")
        is True
    )
    # Negated positive extra markers read as silence, not as act.
    assert (
        decision_polarity(
            "It is not safe to cancel this subscription.",
            extra_positive=("safe to cancel",),
        )
        is None
    )
    # Direct negatives still win.
    assert decision_polarity("Never delete the ledger table.") is False


def test_encode_merges_provenance_across_documents():
    """A duplicated sentence keeps BOTH documents' provenance."""
    shared = "Database store files under data/ must be retained."
    docs = [
        Document("forum-post", f"Some chatter. {shared}"),
        Document("runbook", f"{shared} Logs may be deleted after seven days."),
    ]
    entries = LocalEncoder().encode(docs)
    dup = next(e for e in entries if e.answer == shared)
    assert set(dup.sources) == {"forum-post", "runbook"}


def test_demo_corpus_is_packaged_and_complete():
    docs = demo_corpus()
    assert {d.doc_id for d in docs} == {"runbook", "platform-notes", "forum-post"}
    assert all(d.text.strip() for d in docs)


def test_main_module_import_is_safe():
    """Importing darwin_memo.__main__ must not run the CLI."""
    import importlib

    module = importlib.import_module("darwin_memo.__main__")
    assert hasattr(module, "main")


def test_history_is_capped(store_factory):
    from darwin_memo.ledger import note_text

    store = store_factory()
    ledger = Ledger(store, resource_scale=1.0)
    entry_id = store.alive()[0].id
    for i in range(300):
        ledger._note(entry_id, f"event {i}")
    assert len(ledger._history[entry_id]) == 100
    assert note_text(ledger._history[entry_id][-1]) == "event 299"
