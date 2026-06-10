"""Property-based tests for the energy ledger invariants.

These check the conservation-style laws the README claims: consolidation
pools energy exactly and never creates it, credit respects the cap,
upkeep is exactly linear, dead entries never resurface, and retrieval
relevance never reads energy.
"""

import pytest

hypothesis = pytest.importorskip("hypothesis")

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    RuleBasedStateMachine,
    invariant,
    rule,
)

from darwin_memo import (  # noqa: E402
    EmbeddingRetriever,
    HashingEmbedder,
    LexicalRetriever,
    MemoryEntry,
    MemoryStore,
    consolidate,
)

_VOCAB_TEXT = (
    "database log cache report file backup policy retention platform team "
    "delete keep remove retain nightly quarterly storage data cleanup patch "
    "clamp slugify version helper test suite apply fix cosmetic"
)
_VOCAB = _VOCAB_TEXT.split()


@st.composite
def sentences(draw):
    words = draw(st.lists(st.sampled_from(_VOCAB), min_size=3, max_size=8))
    return " ".join(words)


@st.composite
def entries(draw):
    return MemoryEntry(
        question=draw(sentences()),
        answer=draw(sentences()),
        energy=draw(st.floats(0.01, 5.0, allow_nan=False, allow_infinity=False)),
    )


@given(st.lists(entries(), min_size=2, max_size=12))
@settings(max_examples=50)
def test_consolidation_pools_energy_exactly(entry_list):
    store = MemoryStore(max_energy=10.0)
    for e in entry_list:
        store.add(e)
    snapshot = {e.id: e.energy for e in store.alive()}
    total_before = sum(snapshot.values())

    consolidate(store, cycle=1, threshold=0.5)

    for merged in store.alive():
        if merged.lineage:
            pooled = sum(snapshot[ancestor] for ancestor in merged.lineage)
            assert abs(merged.energy - min(store.max_energy, pooled)) < 1e-9
    assert store.total_energy() <= total_before + 1e-9


@given(
    st.lists(
        st.floats(-3.0, 3.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=30,
    )
)
def test_credit_never_exceeds_cap(amounts):
    store = MemoryStore(max_energy=2.5)
    entry = store.add(MemoryEntry(question="q word", answer="a word"))
    for i, amount in enumerate(amounts):
        store.credit(entry.id, amount, cycle=i)
        assert entry.energy <= 2.5 + 1e-9


@given(st.integers(min_value=1, max_value=50))
def test_upkeep_is_exactly_linear_until_death(n_cycles):
    store = MemoryStore(upkeep=0.05)
    entry = store.add(MemoryEntry(question="q word", answer="a word", energy=1.0))
    for i in range(n_cycles):
        store.charge_upkeep()
        expected = 1.0 - 0.05 * (i + 1)
        if expected > 1e-9:
            assert abs(entry.energy - expected) < 1e-9
        else:
            assert not entry.alive
            break


@pytest.mark.parametrize(
    "retriever_factory",
    [
        LexicalRetriever,
        lambda: EmbeddingRetriever(HashingEmbedder(dims=64), min_similarity=0.05),
    ],
    ids=["lexical", "embedding"],
)
@given(data=st.data())
@settings(max_examples=25, deadline=None)
def test_retrieval_scores_ignore_energy(retriever_factory, data):
    """The selection-pressure invariant: relevance never reads energy."""
    store = MemoryStore(retriever=retriever_factory())
    for e in data.draw(st.lists(entries(), min_size=2, max_size=8)):
        store.add(e)
    query = data.draw(sentences())

    before = [(e.id, score) for e, score in store.retriever.rank(query, store.alive())]
    for e in store.alive():
        store.credit(e.id, data.draw(st.floats(-2.0, 2.0, allow_nan=False)), cycle=1)
    after = [(e.id, score) for e, score in store.retriever.rank(query, store.alive())]

    assert dict(before) == dict(after)


class LedgerMachine(RuleBasedStateMachine):
    """Random walks over the store API can never break the ledger laws."""

    def __init__(self):
        super().__init__()
        self.store = MemoryStore(max_energy=5.0, upkeep=0.1)
        self.counter = 0

    @rule(question=sentences(), answer=sentences())
    def add(self, question, answer):
        self.counter += 1
        self.store.add(MemoryEntry(question=question, answer=answer))

    @rule(amount=st.floats(-2.0, 2.0, allow_nan=False))
    def credit_random(self, amount):
        alive = self.store.alive()
        if alive:
            self.store.credit(alive[0].id, amount, cycle=self.counter)

    @rule()
    def bury_one(self):
        alive = self.store.alive()
        if alive:
            self.store.bury(alive[-1].id)

    @rule()
    def upkeep(self):
        self.store.charge_upkeep()

    @rule()
    def merge(self):
        consolidate(self.store, cycle=self.counter, threshold=0.5)

    @invariant()
    def alive_and_graveyard_disjoint(self):
        alive_ids = {e.id for e in self.store.alive()}
        dead_ids = {e.id for e in self.store.graveyard()}
        assert not (alive_ids & dead_ids)

    @invariant()
    def graveyard_energy_nonpositive(self):
        assert all(e.energy <= 1e-9 for e in self.store.graveyard())

    @invariant()
    def retrieval_returns_only_alive(self):
        alive_ids = {e.id for e in self.store.alive()}
        for entry, _ in self.store.retrieve("database log cache report"):
            assert entry.id in alive_ids

    @invariant()
    def energy_within_cap(self):
        assert all(e.energy <= 5.0 + 1e-9 for e in self.store.alive())


TestLedgerMachine = LedgerMachine.TestCase
