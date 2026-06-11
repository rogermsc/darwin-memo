"""The Ledger: delayed settlement, escrow, expiry, obituaries."""

import json

from darwin_memo import Ledger, MemoryEntry, MemoryStore, SurvivalConfig, Ticket


def seeded_store(upkeep: float = 0.05) -> MemoryStore:
    store = MemoryStore(upkeep=upkeep)
    store.add(
        MemoryEntry(
            question="Is the schema helper load-bearing?",
            answer="The schema helper is load-bearing and must be kept.",
            sources=["runbook"],
        )
    )
    store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Stale feature flags are redundant and safe to remove.",
            sources=["runbook"],
        )
    )
    return store


def deciding_entry_of(store: MemoryStore, ticket: Ticket) -> MemoryEntry:
    """Typed accessor: the ticket decided, and the entry exists."""
    assert ticket.deciding_entry is not None
    entry = store.get(ticket.deciding_entry)
    if entry is None:
        entry = next(e for e in store.graveyard() if e.id == ticket.deciding_entry)
    return entry


def test_decide_then_settle_credits_provenance():
    store = seeded_store()
    ledger = Ledger(store, resource_scale=2.0)

    ticket = ledger.decide("Are stale feature flags safe to remove?")
    assert ticket.answer
    assert ticket.provenance
    before = {e.id: e.energy for e in store.alive()}

    ledger.settle(ticket.id, delta=2.0, detail="3 flags removed, tests green")

    deciding = deciding_entry_of(store, ticket)
    assert deciding.energy > before[deciding.id]
    assert not ledger.pending()


def test_settle_is_idempotent():
    store = seeded_store()
    ledger = Ledger(store, resource_scale=2.0)
    ticket = ledger.decide("Are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=2.0)
    energy_after_first = deciding_entry_of(store, ticket).energy
    ledger.settle(ticket.id, delta=2.0)  # duplicate delivery
    ledger.settle("nonexistent", delta=99.0)  # unknown ticket
    assert deciding_entry_of(store, ticket).energy == energy_after_first


def test_escrow_blocks_death_until_settlement():
    """An entry with an unsettled outcome cannot be buried by upkeep."""
    store = seeded_store(upkeep=1.0)  # brutal upkeep: death in one tick
    ledger = Ledger(store, resource_scale=1.0)
    ticket = ledger.decide("Are stale feature flags safe to remove?")

    ledger.tick(expire_after=None)
    entry = deciding_entry_of(store, ticket)
    assert entry.id in {e.id for e in store.alive()}, (
        "escrowed entry must not be buried"
    )
    assert not entry.alive, "it still pays upkeep"

    # A strongly positive verdict arrives late and revives the balance.
    ledger.settle(ticket.id, delta=50.0)
    assert deciding_entry_of(store, ticket).alive

    # Without escrow protection the unconsulted entry died normally.
    assert len(store.graveyard()) >= 1


def test_negative_settlement_after_escrow_buries():
    store = seeded_store(upkeep=1.0)
    ledger = Ledger(store, resource_scale=1.0)
    ticket = ledger.decide("Are stale feature flags safe to remove?")
    ledger.tick(expire_after=None)  # drains to <= 0, escrow holds burial
    ledger.settle(ticket.id, delta=-10.0, detail="deleting flags broke prod")

    assert ticket.deciding_entry is not None
    assert store.get(ticket.deciding_entry) is None, "verdict arrived: buried"
    assert ticket.deciding_entry in {e.id for e in store.graveyard()}


def test_unsettled_tickets_expire_at_zero():
    store = seeded_store()
    ledger = Ledger(store, resource_scale=1.0)
    ticket = ledger.decide("Are stale feature flags safe to remove?")
    energy_before = deciding_entry_of(store, ticket).energy

    for _ in range(4):
        ledger.tick(expire_after=3)

    assert not ledger.pending(), "ticket expired"
    # Zero-delta settlement earned nothing; only upkeep moved energy.
    assert deciding_entry_of(store, ticket).energy < energy_before


def test_consolidation_excludes_escrowed_entries():
    store = seeded_store()
    near_dup = store.add(
        MemoryEntry(
            question="What about the stale feature flags?",
            answer="The stale feature flags are redundant and safe to remove now.",
        )
    )
    ledger = Ledger(
        store,
        config=SurvivalConfig(consolidate_every=1, merge_threshold=0.5),
    )
    ticket = ledger.decide("Are stale feature flags safe to remove?")
    ledger.tick()

    # Provenance ids must still resolve while the ticket is pending.
    for entry_id in ticket.provenance:
        assert store.get(entry_id) is not None
    del near_dup


def test_event_log_and_obituary(tmp_path):
    log = tmp_path / "events.jsonl"
    store = seeded_store(upkeep=0.6)
    ledger = Ledger(store, resource_scale=1.0, event_log=log)

    ticket = ledger.decide("Are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=-5.0, detail="broke the canary")
    ledger.tick()
    ledger.tick()

    events = [json.loads(line) for line in log.read_text().splitlines()]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "decide" and "settle" in kinds and "tick" in kinds

    deciding = deciding_entry_of(store, ticket).id
    text = ledger.obituary(deciding)
    assert "credit" in text and "broke the canary" in text

    # The never-consulted entry starved; its obituary says so.
    starved = next(e for e in store.graveyard() if e.id != deciding)
    assert "starved" in ledger.obituary(starved.id)
    # The punished entry's death is attributed to its outcomes.
    if not deciding_entry_of(store, ticket).alive:
        assert "executed" in ledger.obituary(deciding)
