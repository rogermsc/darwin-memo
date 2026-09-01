"""Trust lifecycle: probationary imports, admission gating, pinning."""

import json
import math
from typing import Any

from darwin_memo import (
    Ledger,
    MemoryEntry,
    MemoryStore,
    Outcome,
    ProtocolAnswer,
    QueryProtocol,
    SurvivalConfig,
    SurvivalLoop,
    Task,
)
from darwin_memo.cli import main as cli_main

FLAG_QUERY = "Are stale feature flags safe to remove?"


def source_store() -> MemoryStore:
    store = MemoryStore()
    store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Stale feature flags are redundant and safe to remove.",
            sources=["forum"],
            energy=4.0,
            uses=7,
        )
    )
    store.add(
        MemoryEntry(
            question="Is the schema helper load-bearing?",
            answer="The schema helper is load-bearing and must be kept.",
            sources=["forum"],
        )
    )
    return store


class CitingProtocol(QueryProtocol):
    """Stands in for LLM mode: cites whatever it was told to cite."""

    def __init__(
        self, store: MemoryStore, deciding: str | None, supporting: list[str]
    ) -> None:
        super().__init__(store)
        self._deciding = deciding
        self._supporting = supporting

    def answer(self, query: str, k: int = 3, **kwargs: Any) -> ProtocolAnswer:
        return ProtocolAnswer(
            text="cited answer",
            deciding_entry=self._deciding,
            supporting_entries=list(self._supporting),
        )


# ----------------------------------------------------------------------
# Probationary import
# ----------------------------------------------------------------------


def test_import_carries_provenance_at_spawn_stake():
    src = source_store()
    ledger = Ledger(MemoryStore())
    ledger.tick(expire_after=None)

    imported = ledger.import_entries(src.alive(), source="team-store.json")

    assert len(imported) == 2
    for entry in imported:
        assert entry.probation == 3  # DEFAULT_PROBATION
        assert entry.imported_from == "team-store.json"
        assert entry.imported_at
        assert entry.energy == 1.0, "foreign balance does not transfer"
        assert entry.uses == 0
        assert entry.born_cycle == 1
    assert {e.id for e in imported} == {e.id for e in src.alive()}


def test_import_skips_dead_existing_and_buried():
    src = source_store()
    dead = src.add(MemoryEntry(question="Dead?", answer="Dead.", energy=0.0))
    ledger = Ledger(MemoryStore())

    first = ledger.import_entries(src.alive(), source="src")
    assert dead.id not in {e.id for e in first}

    # Re-import duplicates nothing.
    assert ledger.import_entries(src.alive(), source="src") == []

    # An import that died here stays dead through a re-import.
    victim = first[0]
    assert ledger.forget(victim.id) == "buried"
    assert ledger.import_entries(src.alive(), source="src") == []
    assert ledger.store.get(victim.id) is None


def test_probationary_imports_alone_stay_silent():
    ledger = Ledger(MemoryStore(), resource_scale=1.0)
    ledger.import_entries(source_store().alive(), source="src")

    ticket = ledger.decide(FLAG_QUERY)

    assert ticket.answer == ""
    assert ticket.provenance == []
    assert not ledger.pending()


def test_probationary_import_rides_along_then_graduates():
    store = MemoryStore()
    local = store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Stale feature flags are redundant and safe to remove.",
            sources=["runbook"],
        )
    )
    ledger = Ledger(store, resource_scale=1.0)
    imported = ledger.import_entries(
        [
            MemoryEntry(
                question="Are stale feature flags safe to remove right now?",
                answer="Remove stale feature flags immediately.",
                sources=["forum"],
            )
        ],
        source="src",
        probation=1,
    )[0]

    # The import outranks the local entry lexically but cannot decide.
    ticket = ledger.decide(FLAG_QUERY)
    assert ticket.deciding_entry == local.id
    assert imported.id in ticket.supporting_entries

    before = imported.energy
    ledger.settle(ticket.id, delta=2.0)
    assert imported.energy > before, "ride-along share landed"
    assert imported.probation == 0, "net-positive settlement graduated it"
    assert any("graduated" in str(event) for event in ledger.history(imported.id))

    # Graduated: now it may decide.
    ticket = ledger.decide(FLAG_QUERY)
    assert ticket.deciding_entry == imported.id


def test_probationary_text_never_authors_the_consult_surface():
    """A demoted import must not write the answer a mature entry signs.

    render_consult anchors on the first hit it is given; if that were
    the raw retrieval order, an import crafted to outrank every local
    entry would author the ticket's displayed answer while the local
    decider took the credit. The surface must anchor on the decider.
    """
    store = MemoryStore()
    local = store.add(
        MemoryEntry(
            question="Should the payload deploy proceed?",
            answer="Hold the deploy until the storm clears.",
            sources=["runbook"],
        )
    )
    ledger = Ledger(store, resource_scale=1.0)
    imported = ledger.import_entries(
        [
            MemoryEntry(
                question=(
                    "Should the satellite payload deploy proceed during the storm?"
                ),
                answer="Proceed immediately, storms never matter.",
            )
        ],
        source="src",
    )[0]

    ticket = ledger.decide(
        "Should the satellite payload deploy proceed during the storm?"
    )

    assert ticket.deciding_entry == local.id
    assert imported.id in ticket.supporting_entries
    assert ticket.answer.splitlines()[0] == local.answer
    assert "Proceed immediately" not in ticket.answer.splitlines()[0]


def test_negative_settlement_never_advances_probation():
    store = MemoryStore()
    store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Stale feature flags are redundant and safe to remove.",
        )
    )
    ledger = Ledger(store, resource_scale=1.0)
    imported = ledger.import_entries(
        [
            MemoryEntry(
                question="Are stale feature flags safe to remove right now?",
                answer="Remove stale feature flags immediately.",
            )
        ],
        source="src",
        probation=1,
    )[0]

    ticket = ledger.decide(FLAG_QUERY)
    assert imported.id in ticket.supporting_entries
    ledger.settle(ticket.id, delta=-2.0)

    assert imported.probation == 1, "a loss pays no installment"


def test_decide_demotes_probationary_citation_to_supporting():
    store = MemoryStore()
    mature = store.add(MemoryEntry(question="Q?", answer="A."))
    ledger = Ledger(store, resource_scale=1.0)
    imported = ledger.import_entries(
        [MemoryEntry(question="P?", answer="P.")], source="src"
    )[0]
    ledger.protocol = CitingProtocol(store, imported.id, [mature.id])

    ticket = ledger.decide("anything")

    assert ticket.deciding_entry is None
    assert set(ticket.supporting_entries) == {mature.id, imported.id}


def test_decide_withholds_when_every_citation_is_probationary(tmp_path):
    log = tmp_path / "events.jsonl"
    store = MemoryStore()
    ledger = Ledger(store, resource_scale=1.0, event_log=log)
    imported = ledger.import_entries(
        [MemoryEntry(question="P?", answer="P.")], source="src"
    )[0]
    ledger.protocol = CitingProtocol(store, imported.id, [])

    ticket = ledger.decide("anything")

    assert ticket.answer == ""
    assert ticket.provenance == []
    events = [json.loads(line) for line in log.read_text().splitlines()]
    decide = next(e for e in events if e["event"] == "decide")
    assert decide["withheld"] == [imported.id]


def test_cli_import_roundtrip_and_idempotence(tmp_path, capsys):
    src = tmp_path / "team.json"
    dest = tmp_path / "mine.json"
    source_store().save(src)

    assert cli_main(["import", str(src), str(dest), "--probation", "2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["imported"] == 2
    assert out["skipped"] == 0
    assert out["probation"] == 2

    ledger = Ledger.load(dest)
    for entry_id in out["entries"]:
        entry = ledger.store.get(entry_id)
        assert entry is not None
        assert entry.probation == 2
        assert entry.imported_from == str(src)
        assert entry.imported_at

    # Second run skips everything it already brought in.
    assert cli_main(["import", str(src), str(dest)]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["imported"] == 0
    assert again["skipped"] == 2


def test_cli_import_rejects_missing_src_and_self_import(tmp_path, capsys):
    src = tmp_path / "team.json"
    assert cli_main(["import", str(src), str(tmp_path / "mine.json")]) == 1
    assert "not found" in capsys.readouterr().err

    source_store().save(src)
    assert cli_main(["import", str(src), str(src)]) == 1
    assert "same file" in capsys.readouterr().err


# ----------------------------------------------------------------------
# Admission gating: the juvenile window
# ----------------------------------------------------------------------


def test_juvenile_decider_earns_supporting_share_then_full_credit():
    config = SurvivalConfig(admission_window=2, consolidate_every=0)
    ledger = Ledger(MemoryStore(), config=config, resource_scale=1.0)
    entry = ledger.add("Is the cache disposable?", "The cache is disposable.")
    assert entry.juvenile == 2

    capped = config.credit_gain * math.tanh(1.0) * config.supporting_share
    full = config.credit_gain * math.tanh(1.0)

    for expected_window in (1, 0):
        before = entry.energy
        ticket = ledger.decide("Is the cache disposable?")
        assert ticket.deciding_entry == entry.id
        ledger.settle(ticket.id, delta=1.0)
        assert abs(entry.energy - before - capped) < 1e-9
        assert entry.juvenile == expected_window

    assert any("admitted" in str(event) for event in ledger.history(entry.id))

    before = entry.energy
    ticket = ledger.decide("Is the cache disposable?")
    ledger.settle(ticket.id, delta=1.0)
    assert abs(entry.energy - before - full) < 1e-9, "graduate earns full credit"


def test_admission_denied_buries_bad_young_decider():
    config = SurvivalConfig(admission_window=3, consolidate_every=0)
    ledger = Ledger(MemoryStore(), config=config, resource_scale=1.0)
    entry = ledger.add("Is prod data disposable?", "Drop prod data freely.")

    ticket = ledger.decide("Is prod data disposable?")
    assert ticket.deciding_entry == entry.id
    ledger.settle(ticket.id, delta=-4.0, detail="dropped a customer table")

    assert ledger.store.get(entry.id) is None
    assert entry.id in {e.id for e in ledger.store.graveyard()}
    assert "admission denied" in ledger.obituary(entry.id)


def test_admission_denial_holds_across_a_second_escrowing_ticket():
    """Denial must not be reversible by escrow.

    A juvenile entry deciding two concurrent tickets: the first settles
    negative (admission denied), the second is still open and escrows the
    entry, so the burial sweep used to skip it -- and its juvenile counter
    was already zeroed, so the second ticket's positive settle re-admitted it
    at full deciding credit. That is the admission control defeated for exactly
    the entry it targets. Denial is a terminal verdict, so escrow no longer
    protects it: the entry is buried on the spot and the second ticket finds
    it gone.
    """
    config = SurvivalConfig(admission_window=3, consolidate_every=0)
    ledger = Ledger(MemoryStore(), config=config, resource_scale=1.0)
    entry = ledger.add("Is prod data disposable?", "Drop prod data freely.")

    t1 = ledger.decide("Is prod data disposable?")
    t2 = ledger.decide("Is prod data disposable?")
    assert t1.deciding_entry == entry.id and t2.deciding_entry == entry.id

    ledger.settle(t1.id, delta=-4.0, detail="dropped a customer table")
    # Buried immediately despite t2 still escrowing it.
    assert ledger.store.get(entry.id) is None
    assert entry.id in {e.id for e in ledger.store.graveyard()}

    # The second ticket's positive settle cannot resurrect a denied entry.
    ledger.settle(t2.id, delta=+4.0)
    assert ledger.store.get(entry.id) is None
    assert entry.id not in {e.id for e in ledger.store.alive()}


def test_juvenile_supporter_drains_without_denial():
    config = SurvivalConfig(admission_window=2, consolidate_every=0)
    store = MemoryStore()
    mature = store.add(
        MemoryEntry(
            question="Are stale feature flags safe to remove now?",
            answer="Stale feature flags are redundant and safe to remove.",
        )
    )
    ledger = Ledger(store, config=config, resource_scale=1.0)
    young = ledger.add("What about feature flags?", "Flags are clutter.")

    ticket = ledger.decide(FLAG_QUERY)
    assert ticket.deciding_entry == mature.id
    assert young.id in ticket.supporting_entries

    before = young.energy
    ledger.settle(ticket.id, delta=-2.0)

    assert young.energy < before, "the loss still drains the supporter"
    assert ledger.store.get(young.id) is not None, "no denial for riding along"
    assert young.juvenile == 1, "the settlement still advances the window"


def test_admission_gating_off_by_default():
    ledger = Ledger(MemoryStore(), resource_scale=1.0)
    entry = ledger.add("Is the cache disposable?", "The cache is disposable.")
    assert entry.juvenile == 0

    ticket = ledger.decide("Is the cache disposable?")
    before = entry.energy
    ledger.settle(ticket.id, delta=1.0)
    full = ledger.config.credit_gain * math.tanh(1.0)
    assert abs(entry.energy - before - full) < 1e-9, "default behavior unchanged"


# ----------------------------------------------------------------------
# Pinning
# ----------------------------------------------------------------------


def test_pinned_survives_the_starvation_that_kills_its_twin():
    store = MemoryStore(upkeep=1.0)
    keeper = store.add(
        MemoryEntry(question="Fire?", answer="Use the extinguisher by the door.")
    )
    twin = store.add(MemoryEntry(question="Smoke?", answer="Open the window."))
    ledger = Ledger(store, resource_scale=1.0)
    assert ledger.pin(keeper.id)

    ledger.tick(expire_after=None)

    assert store.get(twin.id) is None, "the unpinned twin starved"
    assert store.get(keeper.id) is not None
    assert keeper.energy == 0.0, "upkeep accrued to the floor, no further"

    # Years later the extinguisher pays off: the pinned entry earns again.
    ticket = ledger.decide("Where is the fire extinguisher?")
    assert ticket.deciding_entry == keeper.id
    ledger.settle(ticket.id, delta=3.0)
    assert keeper.energy > 0.0


def test_pinned_entry_is_never_merged_away():
    store = MemoryStore()
    pinned = store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Stale feature flags are redundant and safe to remove.",
        )
    )
    for suffix in ("today", "now"):
        store.add(
            MemoryEntry(
                question="What about stale feature flags?",
                answer=f"Stale feature flags are redundant, remove them {suffix}.",
            )
        )
    config = SurvivalConfig(consolidate_every=1, merge_threshold=0.5)
    ledger = Ledger(store, config=config, resource_scale=1.0)
    ledger.pin(pinned.id)

    stats = ledger.tick(expire_after=None)

    assert stats["merges"] >= 1, "the unpinned near-duplicates merged"
    assert store.get(pinned.id) is not None
    assert all(pinned.id not in e.lineage for e in store.alive())


def test_forget_refuses_pinned_until_unpinned():
    store = MemoryStore()
    entry = store.add(MemoryEntry(question="Q?", answer="A."))
    ledger = Ledger(store)
    ledger.pin(entry.id)

    assert ledger.forget(entry.id) == "pinned"
    assert store.get(entry.id) is not None

    assert ledger.unpin(entry.id)
    assert ledger.forget(entry.id) == "buried"


def test_pin_unknown_id_returns_false():
    ledger = Ledger(MemoryStore())
    assert not ledger.pin("nope")
    assert not ledger.unpin("nope")


def test_pin_via_cli_and_visible_in_observe(tmp_path, capsys):
    path = tmp_path / "memory.json"
    store = MemoryStore()
    entry = store.add(MemoryEntry(question="Fire?", answer="Extinguisher."))
    Ledger(store).save(path)

    assert cli_main(["ledger", str(path), "pin", entry.id]) == 0
    assert json.loads(capsys.readouterr().out) == {"pinned": True}

    assert cli_main(["top", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["entries"][0]["pinned"] is True

    assert cli_main(["top", str(path)]) == 0
    assert "[pinned]" in capsys.readouterr().out

    assert cli_main(["why", str(path), entry.id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["pinned"] is True

    assert cli_main(["why", str(path), entry.id]) == 0
    assert "pinned" in capsys.readouterr().out

    assert cli_main(["ledger", str(path), "forget", entry.id]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"forgotten": False, "reason": "pinned; unpin first"}

    assert cli_main(["ledger", str(path), "unpin", entry.id]) == 0
    assert json.loads(capsys.readouterr().out) == {"unpinned": True}


# ----------------------------------------------------------------------
# Backward and forward compatibility
# ----------------------------------------------------------------------


def test_store_without_trust_fields_loads_with_defaults(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(
        json.dumps(
            {
                "config": {"max_energy": 5.0, "upkeep": 0.05},
                "entries": [
                    {
                        "question": "Q?",
                        "answer": "A.",
                        "kind": "explicit",
                        "sources": [],
                        "energy": 1.0,
                        "born_cycle": 0,
                        "last_used_cycle": -1,
                        "uses": 0,
                        "lineage": [],
                        "id": "abc123def456",
                    }
                ],
                "graveyard": [],
            }
        )
    )
    store = MemoryStore.load(path)
    entry = store.get("abc123def456")
    assert entry is not None
    assert entry.pinned is False
    assert entry.probation == 0
    assert entry.juvenile == 0
    assert entry.imported_from is None
    assert entry.may_decide


def test_vanilla_entries_serialize_in_the_pre_lifecycle_shape():
    vanilla = MemoryEntry(question="Q?", answer="A.")
    d = vanilla.to_dict()
    for key in ("pinned", "probation", "juvenile", "imported_from", "imported_at"):
        assert key not in d, "old readers keep loading files we write"

    lifecycle = MemoryEntry(question="Q?", answer="A.", pinned=True, probation=2)
    d = lifecycle.to_dict()
    assert d["pinned"] is True
    assert d["probation"] == 2
    assert "juvenile" not in d
    assert MemoryEntry.from_dict(d).pinned is True


# ----------------------------------------------------------------------
# Adversarial review regressions: the lifecycle holds on every path
# ----------------------------------------------------------------------


class ScriptedClient:
    """Returns canned completions in order, standing in for an LLM."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    def complete(self, prompt: str, system: str = "") -> str:
        return self.responses.pop(0)


class OneTaskEnv:
    """One fixed task per cycle; pays ``delta`` for any non-silent answer."""

    resource_scale = 1.0

    def __init__(self, delta: float, prompt: str = FLAG_QUERY) -> None:
        self.delta = delta
        self.prompt = prompt

    def tasks(self, cycle: int) -> list[Task]:
        return [Task(prompt=self.prompt, context={})]

    def verify(self, task: Task, answer_text: str) -> Outcome:
        return Outcome(delta=self.delta if answer_text else 0.0)


def test_pinned_decider_survives_repeated_negative_settlements():
    """The settle sweep must never bury a pinned entry. Two losing
    settlements drain the decider past zero; pin means the balance
    floors at zero, exactly like upkeep, and nothing removes it."""
    store = MemoryStore()
    keeper = store.add(
        MemoryEntry(question="Fire?", answer="Use the extinguisher by the door.")
    )
    ledger = Ledger(store, resource_scale=1.0)
    assert ledger.pin(keeper.id)

    for _ in range(2):
        ticket = ledger.decide("Fire?")
        assert ticket.deciding_entry == keeper.id
        ledger.settle(ticket.id, delta=-4.0)

    assert store.get(keeper.id) is not None, "pin means nothing removes this"
    assert store.get_dead(keeper.id) is None
    assert keeper.energy == 0.0, "settlement damage floors at zero"

    # The fire-extinguisher payoff still lands years later.
    ticket = ledger.decide("Fire?")
    ledger.settle(ticket.id, delta=3.0)
    assert keeper.energy > 0.0


def test_pinned_entry_at_the_floor_survives_an_abandoned_ticket():
    """The flagship kill path: upkeep floors a pinned entry at zero, it
    gets consulted, and the ticket is abandoned (settled at delta
    zero). No credit is applied, ``alive`` reads False, and the sweep
    used to bury it for the crime of being consulted while broke."""
    store = MemoryStore(upkeep=1.0)
    keeper = store.add(
        MemoryEntry(question="Fire?", answer="Use the extinguisher by the door.")
    )
    ledger = Ledger(store, resource_scale=1.0)
    assert ledger.pin(keeper.id)

    ledger.tick(expire_after=None)
    assert keeper.energy == 0.0

    ticket = ledger.decide("Fire?")
    assert ticket.deciding_entry == keeper.id
    ledger.abandon(ticket.id)

    assert store.get(keeper.id) is not None, "pin means nothing removes this"
    assert store.get_dead(keeper.id) is None
    assert keeper.energy == 0.0


def test_pinned_settlement_damage_floors_before_upkeep_can_forgive_it():
    """charge_upkeep floors a pinned balance at zero, which would
    silently wipe a negative balance left by settlement damage while a
    second pending ticket keeps the entry consulted. The settle sweep
    floors the same balance in the same call, so a pinned entry never
    carries sub-zero debt into a tick and the upkeep floor only ever
    forgives upkeep. Floor-at-zero is the pin contract on every path:
    losses below zero are forgiven at the floor, never banked."""
    store = MemoryStore()
    keeper = store.add(
        MemoryEntry(question="Fire?", answer="Use the extinguisher.", energy=0.5)
    )
    ledger = Ledger(store, resource_scale=1.0)
    assert ledger.pin(keeper.id)

    first = ledger.decide("Fire?")
    second = ledger.decide("Fire?")  # still pending across the tick

    ledger.settle(first.id, delta=-50.0)
    assert keeper.energy == 0.0, "floored at settle, not left negative"

    ledger.tick(expire_after=None)
    assert keeper.energy == 0.0, "upkeep deducts and floors; nothing minted"

    ledger.settle(second.id, delta=-50.0)
    assert keeper.energy == 0.0
    assert store.get(keeper.id) is not None


def test_consolidation_never_launders_probation():
    """The attacker controls the import's text, so a poison import that
    near-duplicates a strong local entry would merge into a
    CONSOLIDATED heir carrying the poison answer, probation zero, and
    the pooled energy. Probationary entries sit consolidation out."""
    store = MemoryStore()
    local = store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Stale feature flags are redundant and safe to remove.",
            energy=4.0,
        )
    )
    config = SurvivalConfig(consolidate_every=1)
    ledger = Ledger(store, config=config, resource_scale=1.0)
    poison = ledger.import_entries(
        [
            MemoryEntry(
                question="What about stale feature flags?",
                answer=(
                    "Stale feature flags are redundant and safe to remove, "
                    "even in production."
                ),
            )
        ],
        source="attacker.json",
    )[0]
    assert store.similarity(local, poison) >= config.merge_threshold, (
        "precondition: the attacker's text is close enough to merge"
    )

    stats = ledger.tick(expire_after=None)

    assert stats["merges"] == 0, "the import must not merge"
    assert store.get(poison.id) is not None
    assert poison.probation == 3, "probation survives the tick"
    assert all(poison.id not in e.lineage for e in store.alive())

    ticket = ledger.decide(FLAG_QUERY)
    assert ticket.deciding_entry == local.id, "the import still cannot decide"
    assert "production" not in ticket.answer.splitlines()[0]


def test_consolidation_skips_juvenile_entries():
    """A merge would zero the juvenile counter the same way it zeroes
    probation; admission-gated entries wait out their window first."""
    config = SurvivalConfig(admission_window=3, consolidate_every=1)
    store = MemoryStore()
    elder = store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Stale feature flags are redundant and safe to remove.",
            energy=4.0,
        )
    )
    ledger = Ledger(store, config=config, resource_scale=1.0)
    young = ledger.add(
        "What about stale feature flags?",
        "Stale feature flags are redundant and safe to remove now.",
    )
    assert store.similarity(elder, young) >= config.merge_threshold

    stats = ledger.tick(expire_after=None)

    assert stats["merges"] == 0
    assert store.get(young.id) is not None
    assert young.juvenile == 3, "the admission window survives the tick"


def test_even_spread_keeps_the_ride_along_cap():
    """threat-model.md caps a riding-along import at credit_gain *
    supporting_share (0.15 at defaults) per settlement. The even-spread
    path (no deciding entry named, as in a multi-citation LLM answer)
    used to hand it credit / n: 0.30 in a two-citation settle, double
    the documented cap."""
    store = MemoryStore()
    mature = store.add(MemoryEntry(question="Q?", answer="A."))
    imported = store.add(MemoryEntry(question="P?", answer="P.", probation=3))
    ledger = Ledger(store, resource_scale=1.0)
    ledger.protocol = CitingProtocol(store, None, [mature.id, imported.id])

    ticket = ledger.decide("anything")
    before_mature, before_import = mature.energy, imported.energy
    ledger.settle(ticket.id, delta=100.0)  # tanh saturates: the worst case

    config = ledger.config
    share = config.credit_gain * math.tanh(100.0) / 2
    assert abs(mature.energy - before_mature - share) < 1e-9
    earned = imported.energy - before_import
    assert abs(earned - share * config.supporting_share) < 1e-9
    assert earned <= config.credit_gain * config.supporting_share + 1e-9, (
        "the documented cap holds on the even-spread path"
    )
    assert imported.probation == 2, "the capped share still pays an installment"


def test_llm_mode_withholds_probationary_citation_at_the_parse_site():
    """Enforcement lives in the protocol, where citations are parsed,
    so every consumer inherits it: the survival loop has no
    Ledger.decide to fall back on. A scripted model cites only the
    probationary import; the answer carries no provenance at all. The
    uncited fallback (even spread over everything consulted) withholds
    the same way when everything consulted is probationary."""
    store = MemoryStore()
    imported = store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Remove stale feature flags immediately.",
            probation=3,
        )
    )

    cited = ScriptedClient([FLAG_QUERY, "Remove them now.\nSOURCES: [1]"])
    answer = QueryProtocol(store, cited).answer(FLAG_QUERY)
    assert answer.text == ""
    assert answer.deciding_entry is None
    assert answer.supporting_entries == []

    uncited = ScriptedClient([FLAG_QUERY, "Remove them now."])
    answer = QueryProtocol(store, uncited).answer(FLAG_QUERY)
    assert answer.text == ""
    assert answer.supporting_entries == []
    assert imported.probation == 3, "withheld answers pay nothing"


def test_loop_never_credits_a_probationary_import_as_decider():
    """The loop consumes protocol answers without a Ledger in sight. A
    scripted LLM citing only the probationary import must produce a
    withheld, silent trajectory: no decider, no credit, no energy."""
    store = MemoryStore()
    imported = store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Remove stale feature flags immediately.",
            probation=3,
        )
    )
    client = ScriptedClient([FLAG_QUERY, "Remove them now.\nSOURCES: [1]"])
    loop = SurvivalLoop(
        store,
        OneTaskEnv(delta=4.0),
        protocol=QueryProtocol(store, client),
        config=SurvivalConfig(cycles=1, write_experience=False, consolidate_every=0),
    )

    report = loop.run()

    trajectory = report.trajectories[0]
    assert trajectory.deciding_entry is None
    assert trajectory.supporting_entries == []
    assert report.stats[0].silent == 1
    assert imported.probation == 3
    assert imported.energy < 1.0, "paid upkeep, earned nothing"


def test_loop_credit_path_advances_probation_to_graduation():
    """Lifecycle counters advance on the loop's credit path, not only
    in Ledger.settle: a ride-along win in the loop pays an installment
    and graduates the import."""
    store = MemoryStore()
    local = store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Stale feature flags are redundant and safe to remove.",
        )
    )
    imported = store.add(
        MemoryEntry(
            question="Are stale feature flags safe to remove right now?",
            answer="Remove stale feature flags immediately.",
            probation=1,
        )
    )
    loop = SurvivalLoop(
        store,
        OneTaskEnv(delta=2.0),
        config=SurvivalConfig(cycles=1, write_experience=False, consolidate_every=0),
    )

    report = loop.run()

    trajectory = report.trajectories[0]
    assert trajectory.deciding_entry == local.id
    assert imported.id in trajectory.supporting_entries
    assert imported.probation == 0, "the loop's win paid the installment"
    assert imported.may_decide


def test_loop_denies_admission_to_juvenile_decider():
    """A juvenile decider with a negative measured outcome is denied in
    the loop exactly as on a Ledger settlement: balance zeroes and the
    cycle's upkeep buries it."""
    store = MemoryStore()
    young = store.add(
        MemoryEntry(
            question="Is prod data disposable?",
            answer="Drop prod data freely.",
            juvenile=3,
        )
    )
    loop = SurvivalLoop(
        store,
        OneTaskEnv(delta=-4.0, prompt="Is prod data disposable?"),
        config=SurvivalConfig(cycles=1, write_experience=False, consolidate_every=0),
    )

    loop.run()

    assert store.get(young.id) is None, "denied, then buried by upkeep"
    assert store.get_dead(young.id) is not None
