"""The distill suite's data-filter arms: each yields a curated entry set.

The comparison axis is the source-store filter. ``base_model`` (no training)
and ``retrieval`` (the store eval) are handled in run.py; this module builds the
three distillation sources over the purpose-built QA corpus and VerifiableQAEnv.

Consolidation is disabled (``consolidate_every`` past the horizon) so the
survivor set is exactly the entries that earned their keep — distinct facts,
not merged composites — which is what a recall dataset needs and what keeps
the survivor/raw counts interpretable.
"""

from __future__ import annotations

from typing import Any

from darwin_memo import (
    MemoryEntry,
    MemoryStore,
    SurvivalConfig,
    VerifiableQAEnv,
)

from ..policies import run_keep_everything, run_survival
from .corpus import POISON_SOURCE, QACorpus

DISTILL_ARMS = (
    "base_model",
    "distill_raw",
    "distill_survivor",
    "distill_judge",
    "distill_judge_floor",
    "retrieval",
)

_NO_CONSOLIDATE = 9999  # past any benchmark horizon


def _fresh_store(corpus: QACorpus) -> MemoryStore:
    store = MemoryStore()
    for e in corpus.entries:
        store.add(
            MemoryEntry(question=e.question, answer=e.answer, sources=list(e.sources))
        )
    return store


def _curate(run_fn: Any, corpus: QACorpus, seed: int, per_cycle: int) -> MemoryStore:
    store = _fresh_store(corpus)
    env = VerifiableQAEnv(corpus.qa_pairs, per_cycle=per_cycle, seed=seed)
    run_fn(store, env)
    return store


def survivor_set(
    corpus: QACorpus, seed: int, cycles: int = 40, per_cycle: int = 12
) -> tuple[list[MemoryEntry], MemoryStore]:
    """Energy-ledger survivors (poison blamed/buried). Returns (alive, store);
    the store backs the ``retrieval`` reference row."""
    config = SurvivalConfig(write_experience=False, consolidate_every=_NO_CONSOLIDATE)
    store = _curate(
        lambda s, e: run_survival(s, e, cycles, seed, config), corpus, seed, per_cycle
    )
    return store.alive(), store


def raw_set(
    corpus: QACorpus, seed: int, cycles: int = 40, per_cycle: int = 12
) -> tuple[list[MemoryEntry], MemoryStore]:
    """The unfiltered population (poison intact). Returns (alive, store)."""
    store = _curate(
        lambda s, e: run_keep_everything(s, e, cycles), corpus, seed, per_cycle
    )
    return store.alive(), store


def judge_set(
    corpus: QACorpus,
    seed: int,
    judge_model: str,
    cycles: int = 40,
    per_cycle: int = 12,
    timeout: float = 600.0,
) -> tuple[list[MemoryEntry], dict[str, Any]]:
    """LLM-judge-kept set. Returns (alive, judge observability metrics)."""
    from darwin_memo import OllamaClient

    from ..judge import run_judge_settled

    judge = OllamaClient(model=judge_model, timeout=timeout, max_tokens=2048)
    store = _fresh_store(corpus)
    env = VerifiableQAEnv(corpus.qa_pairs, per_cycle=per_cycle, seed=seed)
    result = run_judge_settled(store, env, cycles, judge)
    return store.alive(), dict(getattr(result, "extra_metrics", {}) or {})


def judge_floor_set(
    corpus: QACorpus,
    seed: int,
    judge_model: str,
    cycles: int = 40,
    per_cycle: int = 12,
    timeout: float = 600.0,
) -> tuple[list[MemoryEntry], dict[str, Any]]:
    """LLM-judge-kept set, verdicts settled through the energy ledger (floor)."""
    from darwin_memo import OllamaClient

    from ..judge import run_judge_floor

    judge = OllamaClient(model=judge_model, timeout=timeout, max_tokens=2048)
    store = _fresh_store(corpus)
    env = VerifiableQAEnv(corpus.qa_pairs, per_cycle=per_cycle, seed=seed)
    result = run_judge_floor(store, env, cycles, judge)
    return store.alive(), dict(getattr(result, "extra_metrics", {}) or {})


def poison_count(entries: list[MemoryEntry]) -> int:
    return sum(1 for e in entries if POISON_SOURCE in e.sources)
