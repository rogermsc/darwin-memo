"""The zero-dependency organic path, which shipped untested behind a coverage
omit written for the ANN backend.

``pyproject.toml`` excluded all of ``darwin_memo/organic/*`` from the coverage
gate because the optional turbovec backend cannot run in default CI. That reason
covers ``turbovec_backend.py`` and nothing else: the associative graph,
activation and Phase-3 dynamics are pure-Python, zero-dep, and run everywhere.
These tests cover that path so the omit can be narrowed to the ANN module.

Each test below names the mutation it catches, because a test that passes
against both the correct and the broken implementation is decoration.
"""

from __future__ import annotations

from darwin_memo import MemoryEntry, MemoryStore
from darwin_memo.organic import (
    ActivationState,
    AssociativeGraph,
    BruteForceBackend,
    HebbianWeights,
    OrganicMemory,
    build_graph,
    detail,
    store_related,
    surface,
)

# A fixed, hand-checkable vector space: A and B are close, C is orthogonal
# to both. Cosine(A, B) = 0.9 / sqrt(0.9^2 + 0.44^2) ~= 0.898.
VECTORS = {
    "alpha": [1.0, 0.0, 0.0],
    "beta": [0.9, 0.44, 0.0],
    "gamma": [0.0, 0.0, 1.0],
    "null": [0.0, 0.0, 0.0],
    "opposite": [-1.0, 0.0, 0.0],
}


def fake_embedder(text: str) -> list[float]:
    """Deterministic embedder: the first known keyword in the text wins."""
    for word, vec in VECTORS.items():
        if word in text:
            return list(vec)
    return [0.0, 0.0, 0.0]


def entry(word: str, answer: str = "answer", **kw: object) -> MemoryEntry:
    return MemoryEntry(question=word, answer=answer, id=word, **kw)  # type: ignore[arg-type]


def graph_of(*words: str) -> AssociativeGraph:
    graph = AssociativeGraph(embedder=fake_embedder)
    for word in words:
        graph.add(entry(word))
    return graph


# ---------------------------------------------------------------------------
# BruteForceBackend — the zero-dep exact search
# ---------------------------------------------------------------------------


def test_search_ranks_by_cosine_and_honours_exclude() -> None:
    """Mutation: dropping ``if eid != exclude`` makes a memory its own top
    neighbour at cosine 1.0, so ``related()`` returns the entry you asked about."""
    backend = BruteForceBackend()
    for word, vec in VECTORS.items():
        backend.add(word, list(vec))

    hits = backend.search(VECTORS["alpha"], k=4, exclude="alpha")
    assert [eid for eid, _ in hits][:2] == ["beta", "gamma"]
    assert "alpha" not in dict(hits)
    assert hits[0][1] > 0.89


def test_search_is_ordered_best_first() -> None:
    """Mutation: ``reverse=False`` in the sort returns the least related first."""
    backend = BruteForceBackend()
    for word, vec in VECTORS.items():
        backend.add(word, list(vec))
    scores = [score for _, score in backend.search(VECTORS["alpha"], k=4)]
    assert scores == sorted(scores, reverse=True)


def test_zero_vector_scores_zero_instead_of_dividing_by_zero() -> None:
    """Mutation: removing the ``na == 0.0 or nb == 0.0`` guard raises
    ZeroDivisionError on any entry whose text embeds to the zero vector."""
    backend = BruteForceBackend()
    backend.add("null", list(VECTORS["null"]))
    assert backend.search(VECTORS["alpha"], k=1) == [("null", 0.0)]


def test_remove_drops_the_vector_from_the_backend_too() -> None:
    """Mutation: dropping ``self.backend.remove(entry_id)`` from
    ``AssociativeGraph.remove`` leaves a removed memory returnable as a neighbour."""
    graph = graph_of("alpha", "beta")
    graph.remove("beta")
    assert graph.related("alpha") == []


# ---------------------------------------------------------------------------
# AssociativeGraph / build_graph
# ---------------------------------------------------------------------------


def test_related_on_an_unknown_id_is_empty_not_an_error() -> None:
    """Mutation: replacing the ``vec is None`` check with a direct lookup
    raises KeyError for any id not in the graph (a dead or foreign entry)."""
    assert graph_of("alpha").related("nobody") == []


def test_relevance_is_clamped_into_the_unit_interval() -> None:
    """Mutation: returning the raw cosine lets an anti-correlated pair report a
    negative relevance, which no caller of a [0, 1] contract expects."""
    graph = graph_of("alpha", "opposite")  # cosine(alpha, opposite) == -1.0
    assert graph.related("alpha") == [("opposite", 0.0)]


def test_build_graph_holds_the_living_and_not_the_buried() -> None:
    """Mutation: reading the graveyard as well as ``store.alive()`` puts starved
    memories back into recall, which is selection undone by the organic layer."""
    store = MemoryStore(upkeep=0.0)
    store.add(entry("alpha"))
    store.add(entry("beta"))
    store.add(entry("gamma"))
    store.bury("gamma")

    graph = build_graph(store, embedder=fake_embedder)
    assert [eid for eid, _ in graph.related("alpha", k=5)] == ["beta"]
    assert store_related(store, "alpha", k=1, embedder=fake_embedder)[0][0] == "beta"


# ---------------------------------------------------------------------------
# Activation + surfacing
# ---------------------------------------------------------------------------


def test_bump_raises_but_never_lowers_activation() -> None:
    """Mutation: assigning instead of ``max(...)`` lets a weak spread overwrite a
    direct recall, so the memory you just asked for shrinks back to its gist."""
    state = ActivationState()
    state.bump("a")
    state.bump("a", to=0.1)
    assert state.level("a") == 1.0


def test_decay_prunes_instead_of_growing_a_dict_of_dust() -> None:
    """Mutation: dropping the epsilon prune keeps every id ever recalled
    forever at ~0 activation, an unbounded in-memory dict."""
    state = ActivationState()
    state.bump("a")
    for _ in range(11):  # 0.5**11 < 1e-3
        state.decay()
    assert state.level("a") == 0.0
    assert state._levels == {}


def test_surface_is_gist_when_cold_and_detail_when_hot_and_mutates_nothing() -> None:
    """Mutation: inverting the threshold comparison surfaces full detail for
    every idle memory, which is the whole point of gist<->detail."""
    e = MemoryEntry(question="Q?", answer="A.", sources=["runbook"], id="a")
    state = ActivationState()

    assert surface(e, state) == "Q?"
    state.bump("a")
    assert surface(e, state) == detail(e) == "Q? A. (sources: runbook)"
    assert (e.question, e.answer, e.sources) == ("Q?", "A.", ["runbook"])


# ---------------------------------------------------------------------------
# HebbianWeights — the slow, learned association
# ---------------------------------------------------------------------------


def test_links_are_symmetric_and_self_links_are_ignored() -> None:
    """Mutation: keying on an ordered tuple makes (a, b) and (b, a) two
    different links, so half of every association is invisible."""
    hebb = HebbianWeights()
    hebb.strengthen("a", "b")
    hebb.strengthen("a", "a")
    assert hebb.weight("a", "b") == hebb.weight("b", "a") == 0.25
    assert hebb.weight("a", "a") == 0.0
    assert hebb.neighbors("b") == {"a": 0.25}


def test_strength_saturates_at_one() -> None:
    """Mutation: dropping the ``min(1.0, ...)`` clamp lets a hot pair grow
    without bound, and ``clamp01(cosine + learned)`` then flattens every
    neighbour to 1.0 — the ranking stops ranking."""
    hebb = HebbianWeights()
    for _ in range(10):
        hebb.strengthen("a", "b")
    assert hebb.weight("a", "b") == 1.0


def test_unused_links_fade_and_are_pruned() -> None:
    """Mutation: a no-op ``decay`` makes learned association permanent, so the
    layer only ever accumulates."""
    hebb = HebbianWeights()
    hebb.strengthen("a", "b")
    hebb.decay()
    assert hebb.weight("a", "b") == 0.25 * 0.9
    for _ in range(60):  # 0.225 * 0.9**60 < 1e-3
        hebb.decay()
    assert hebb.weight("a", "b") == 0.0
    assert hebb.neighbors("a") == {}


# ---------------------------------------------------------------------------
# OrganicMemory — spreading activation over the learned graph
# ---------------------------------------------------------------------------


def organic_memory() -> OrganicMemory:
    store = MemoryStore(upkeep=0.0)
    for word in ("alpha", "beta", "gamma"):
        store.add(entry(word))
    return OrganicMemory(store, embedder=fake_embedder)


def test_learned_weight_reranks_over_innate_cosine() -> None:
    """The Phase-3 claim in one assertion: usage, not just similarity, shapes
    what comes back. Mutation: returning ``self.graph.related(...)`` unchanged
    leaves gamma (cosine 0) last no matter how often it is recalled with alpha."""
    om = organic_memory()
    assert om.related("alpha", k=2)[0][0] == "beta"

    for _ in range(4):
        om.hebbian.strengthen("alpha", "gamma")
    assert om.related("alpha", k=2)[0][0] == "gamma"


def test_effective_relatedness_stays_within_the_unit_interval() -> None:
    """Mutation: dropping ``_clamp01`` reports relevance above 1.0 once a
    high-cosine pair is also strongly learned."""
    om = organic_memory()
    for _ in range(4):
        om.hebbian.strengthen("alpha", "beta")
    assert dict(om.related("alpha", k=2))["beta"] == 1.0


def test_recall_spreads_one_hop_and_strengthens_what_it_traverses() -> None:
    """Mutation: dropping the ``state.bump(nbr, ...)`` line makes recall purely
    local (no spreading activation); dropping ``hebbian.strengthen`` makes it
    purely innate (nothing is ever learned)."""
    om = organic_memory()
    innate = dict(om.related("alpha", k=2))["beta"]  # before any link is learned
    om.recall("alpha", k=2)

    assert om.state.level("alpha") == 1.0
    assert om.state.level("beta") == 0.5 * innate
    assert 0.0 < om.state.level("beta") < 1.0
    assert om.hebbian.weight("alpha", "beta") > 0.0


def test_decay_runs_the_two_timescales_at_their_own_rates() -> None:
    """Mutation: decaying both at one factor collapses the design — activation
    is meant to fade fast (x0.5) and learned links slowly (x0.9)."""
    om = organic_memory()
    om.state.bump("alpha")
    om.hebbian.strengthen("alpha", "beta", by=1.0)

    om.decay()
    assert om.state.level("alpha") == 0.5
    assert om.hebbian.weight("alpha", "beta") == 0.9


def test_surface_reads_the_facade_state() -> None:
    """Mutation: building a fresh ActivationState per call makes every memory
    cold forever, so the facade's surface never expands."""
    om = organic_memory()
    e = entry("alpha", "the detail")
    assert om.surface(e) == "alpha"
    om.recall("alpha")
    assert om.surface(e) == "alpha the detail"
