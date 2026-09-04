"""Regression tests for the max-effort review findings."""

import json
import math

import pytest

from darwin_memo import (
    Document,
    Ledger,
    LocalEncoder,
    MemoryStore,
    SurvivalConfig,
    assign_credit,
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


def test_load_survives_a_malformed_ledger_container(store_factory, tmp_path):
    """A hostile or corrupt committed store must not brick settle-ci. The ledger
    block is attacker-committed and unreviewed, so a malformed CONTAINER -- not
    just one bad ticket -- degrades to dropped fields instead of a traceback.
    Mutation: drop the isinstance/try guards in Ledger.load and the four fields
    below raise ValueError, TypeError, AttributeError and TypeError in turn."""
    path = tmp_path / "memory.json"
    Ledger(store_factory(), resource_scale=1.0).save(path)
    payload = json.loads(path.read_text())
    payload["ledger"] = {
        "tick_count": "not-a-number",  # int() -> ValueError
        "pending": 5,  # for t in 5 -> TypeError
        "history": [],  # [].items() -> AttributeError
        "damaged": 7,  # set(7) -> TypeError
    }
    path.write_text(json.dumps(payload))

    ledger = Ledger.load(path)  # must not raise
    assert ledger.tick_count == 0
    assert ledger.pending() == []
    assert ledger.history("anything") == []


# --------------------------------------------------------------------------
# D0 adversarial audit findings (the 9 lenses the round-3 limit killed).
# --------------------------------------------------------------------------
def test_non_finite_outcome_is_a_no_op_not_a_max_energy_pin(store_factory):
    """A NaN/inf delta or scale must credit nothing, never MAX an entry.

    store.credit does ``min(max_energy, energy + amount)``; for a NaN amount
    that returns max_energy, so an unguarded garbage outcome would pin an entry
    to the cap -- maximally immortal, the exact inverse of survival selection.
    The guard lives in the shared assign_credit rule so both Ledger.settle
    (which guarded delta only) and SurvivalLoop's loop path (which guarded
    neither delta nor scale) are covered. Reverting the guard pins to 5.0.
    """
    cfg = SurvivalConfig()
    for delta, scale in [
        (math.nan, 1.0),
        (math.inf, 1.0),
        (-math.inf, 1.0),
        (5.0, math.nan),
        (5.0, math.inf),
    ]:
        store = store_factory(upkeep=0.0)
        entry = store.alive()[0]
        entry.energy = 1.0
        applied = assign_credit(store, entry.id, [], delta, scale, cfg, cycle=0)
        assert applied == [], f"non-finite ({delta}, {scale}) credited {applied}"
        assert store.get(entry.id).energy == 1.0, (
            f"non-finite ({delta}, {scale}) changed energy to "
            f"{store.get(entry.id).energy} (max_energy is 5.0)"
        )


def test_settle_with_a_non_finite_scale_does_not_corrupt_the_store(store_factory):
    """The hardened settle path guards delta but passed scale through; a NaN
    scale slipped past ``resource_scale or 1.0`` (nan is truthy) and pinned the
    deciding entry via the shared rule. The shared guard now stops it."""
    store = store_factory(upkeep=0.0)
    ledger = Ledger(store, resource_scale=math.nan)
    ticket = ledger.decide("What about stale feature flags?")
    before = {e.id: e.energy for e in store.alive()}
    ledger.settle(ticket.id, 50.0)  # finite delta passes settle's guard
    for e in store.alive():
        assert e.energy == before[e.id], f"nan scale pinned {e.id} to {e.energy}"


def test_load_of_a_structurally_wrong_store_raises_valueerror_not_attributeerror(
    tmp_path,
):
    """A valid-JSON-but-wrong store ({"config": null}) hit null.items() in
    from_payload, raising AttributeError -- which neither loader's except tuple
    caught, so a raw traceback escaped and defeated settle-ci's fail-closed
    base-store abstain (it catches ValueError). Both loaders now name it."""
    payloads: list[dict[str, object]] = [
        {"config": None, "entries": [], "graveyard": []},
        {"config": [1, 2], "entries": [], "graveyard": []},
        {"config": 7, "entries": [], "graveyard": []},
    ]
    for payload in payloads:
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(payload))
        with pytest.raises(ValueError):
            Ledger.load(p)
        with pytest.raises(ValueError):
            MemoryStore.load(p)


def test_parse_junit_on_an_unreadable_path_abstains_not_crashes(tmp_path):
    """report.exists() is True for a directory (a mis-set --junitxml) or a
    read-denied file, so the missing-file branch is skipped and ET.parse raises
    IsADirectoryError/PermissionError -- OSError, not ET.ParseError -- crashing
    past the abstain handler. parse_junit now catches OSError as InfraFailure."""
    from darwin_memo.ci import InfraFailure, parse_junit

    d = tmp_path / "not_a_file"
    d.mkdir()
    with pytest.raises(InfraFailure):
        parse_junit(d, "base")
