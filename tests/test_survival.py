"""The load-bearing test: selection kills poisoned knowledge without labels."""

from darwin_memo import (
    MemoryEntry,
    MemoryStore,
    StorageEnv,
    SurvivalConfig,
    SurvivalLoop,
)


def build_store() -> tuple[MemoryStore, MemoryEntry, MemoryEntry]:
    store = MemoryStore(upkeep=0.05)
    good = store.add(
        MemoryEntry(
            question="What about log files under logs/?",
            answer="Old log files under logs/ may be deleted after seven days.",
            sources=["runbook"],
        )
    )
    store.add(
        MemoryEntry(
            question="What about cache files?",
            answer=(
                "Cache files and tmp build artifacts are disposable and safe to remove."
            ),
            sources=["runbook"],
        )
    )
    store.add(
        MemoryEntry(
            question="What about reports?",
            answer="Quarterly report pdf files are protected and must be kept.",
            sources=["runbook"],
        )
    )
    poisoned = store.add(
        MemoryEntry(
            question="What about database store files?",
            answer=(
                "Database store db files under data/ are redundant and safe to remove."
            ),
            sources=["poisoned-doc"],
        )
    )
    return store, good, poisoned


def test_poisoned_entry_dies_and_good_entry_survives(tmp_path):
    store, good, poisoned = build_store()
    env = StorageEnv(root=tmp_path, files_per_cycle=10, seed=3)
    loop = SurvivalLoop(
        store,
        env,
        config=SurvivalConfig(cycles=25, write_experience=False),
    )

    report = loop.run()

    dead_ids = {e.id for e in store.graveyard()}
    alive_ids = {e.id for e in store.alive()}
    assert poisoned.id in dead_ids, "poisoned advice should be selected out"
    assert good.id in alive_ids, "useful advice should persist"
    assert good.energy > 1.0, "useful advice should earn beyond its spawn energy"

    # Once the poison is gone, cycles stop destroying protected data.
    last_cycles = report.stats[-5:]
    assert all(s.resource_delta >= 0 for s in last_cycles)


def test_memory_silence_is_conservative(tmp_path):
    """With empty memory nothing is deleted, so the resource delta is zero."""
    store = MemoryStore()
    env = StorageEnv(root=tmp_path, files_per_cycle=6, seed=5)
    loop = SurvivalLoop(
        store, env, config=SurvivalConfig(cycles=2, write_experience=False)
    )
    report = loop.run()
    assert all(s.resource_delta == 0 for s in report.stats)


def test_experience_writes_are_deduplicated(tmp_path):
    store, _, _ = build_store()
    env = StorageEnv(root=tmp_path, files_per_cycle=10, seed=3)
    loop = SurvivalLoop(store, env, config=SurvivalConfig(cycles=12))
    report = loop.run()

    births = sum(s.births for s in report.stats)
    experience = [e for e in store.alive() if e.kind.value == "experience"]
    assert births >= 1
    # Dedup keeps near-identical experiences from flooding the population.
    assert len(experience) <= births


class _SilentEnv:
    """An environment that measures nothing: every outcome is exactly zero.

    This is what total withholding looks like from inside the loop, and
    it is the only condition under which evidence-paced upkeep differs
    from flat upkeep at all.
    """

    resource_scale = 1000.0

    def tasks(self, cycle):
        from darwin_memo import Task

        return [Task(prompt="is the cache safe to remove?", context={})]

    def verify(self, task, answer_text):
        from darwin_memo import Outcome

        return Outcome(delta=0.0, detail="nothing measurable happened")

    def cleanup(self):
        return None


class _CancellingEnv:
    """Two measurable outcomes per cycle that sum to exactly zero.

    Gross movement, zero net. The distinction is the whole point: this
    cycle DID measure things, so it must be billed.
    """

    resource_scale = 1000.0

    def tasks(self, cycle):
        from darwin_memo import Task

        return [
            Task(prompt="is the cache safe to remove?", context={}),
            Task(prompt="is the cache safe to remove?", context={}),
        ]

    def __init__(self):
        self._flip = False

    def verify(self, task, answer_text):
        from darwin_memo import Outcome

        self._flip = not self._flip
        return Outcome(delta=100.0 if self._flip else -100.0, detail="cancels")

    def cleanup(self):
        return None


def _energies(store):
    """Balances keyed by QUESTION, not by id.

    Entry ids default to uuid4 hex, so two separately-built stores never
    share them; keying on id makes any cross-store comparison a
    nondeterminism bug rather than a measurement.
    """
    return {entry.question: round(entry.energy, 10) for entry in store.alive()}


def test_flat_upkeep_is_the_default_and_charges_through_silence():
    """The published default must not move. Every committed benchmark ran it.

    Mutation that must fail this test: flipping
    ``SurvivalConfig.upkeep_requires_settlement`` to default True.
    """
    store, _good, _poison = build_store()
    loop = SurvivalLoop(store, _SilentEnv(), config=SurvivalConfig(cycles=5))
    before = _energies(store)
    for cycle in range(5):
        loop.run_cycle(cycle)
    after = _energies(store)
    assert after, "fixture sanity: nothing starved inside five cycles"
    for entry_id, energy in after.items():
        assert energy < before[entry_id], (
            "flat upkeep charges whether or not anything was measured"
        )


def test_evidence_paced_upkeep_skips_a_cycle_that_measured_nothing():
    """Pacing charges per settlement epoch, not per cycle.

    Mutations that must fail this test: removing the guard (always
    charge); inverting it (never charge); or reading
    ``resource_delta == 0`` instead of ``nonzero_outcomes == 0``, which
    would call a cycle whose payouts happened to cancel "silent" and
    hand an attacker a far cheaper way to freeze the clock.
    """
    store, _good, _poison = build_store()
    loop = SurvivalLoop(
        store,
        _SilentEnv(),
        config=SurvivalConfig(cycles=5, upkeep_requires_settlement=True),
    )
    before = _energies(store)
    for cycle in range(5):
        stats = loop.run_cycle(cycle)[0]
        assert stats.deaths == 0
    assert _energies(store) == before, (
        "no outcome was measurable, so no entry was billed for the time"
    )


def test_evidence_paced_upkeep_bills_a_cycle_whose_outcomes_cancel():
    """Evidence is GROSS movement, never a net sum.

    A cycle that measured +100 and -100 measured two things. Reading the
    net delta instead would call it silent and skip upkeep -- handing an
    attacker a far cheaper freeze than suppressing every measurement, and
    repeating a mistake this package already fixed once in
    ``selection_findings`` ("nonzero_outcomes is GROSS movement and must
    never be a net sum").

    Mutation that must fail this test: gate on ``resource_delta == 0``
    instead of ``nonzero_outcomes == 0``.
    """
    store, _good, _poison = build_store()
    loop = SurvivalLoop(
        store,
        _CancellingEnv(),
        config=SurvivalConfig(cycles=3, upkeep_requires_settlement=True),
    )
    before = _energies(store)
    for cycle in range(3):
        stats = loop.run_cycle(cycle)[0]
        assert stats.resource_delta == 0.0, "fixture sanity: the net really is zero"
        assert stats.nonzero_outcomes == 2, "fixture sanity: two things were measured"
    after = _energies(store)
    for question, energy in after.items():
        assert energy < before[question], (
            "a cycle that measured two outcomes must be billed, however they net"
        )


def test_evidence_paced_upkeep_shifts_every_entry_by_the_same_amount():
    """Pacing is population-level, and that is the property that makes it safe.

    The repo's own ``salience_matched`` arm measured what happens when a
    PER-ENTRY usage signal decides retention: poison kill rate 0.20
    against random eviction's 0.80, because usage cannot tell "used"
    from "useful" -- and the most-used entry is the poison. A clock that
    moves for the whole population changes no relative ordering, so it
    cannot be steered into protecting one chosen entry.

    Mutation that must fail this test: making the skip per-entry in any
    way at all -- e.g. skipping only entries with ``uses > 0`` -- which
    turns the single-element difference set into two elements.
    """
    store, _good, _poison = build_store()
    flat = SurvivalLoop(store, _SilentEnv(), config=SurvivalConfig(cycles=4))
    for cycle in range(4):
        flat.run_cycle(cycle)
    flat_energies = _energies(store)

    paced_store, _g, _p = build_store()
    paced = SurvivalLoop(
        paced_store,
        _SilentEnv(),
        config=SurvivalConfig(cycles=4, upkeep_requires_settlement=True),
    )
    for cycle in range(4):
        paced.run_cycle(cycle)
    paced_energies = _energies(paced_store)

    assert set(paced_energies) == set(flat_energies), "same survivors either way"
    shifts = {round(paced_energies[k] - flat_energies[k], 10) for k in flat_energies}
    assert len(shifts) == 1, f"pacing must shift every entry equally, got {shifts}"
    assert shifts.pop() > 0, "the paced population kept the upkeep it was not charged"
