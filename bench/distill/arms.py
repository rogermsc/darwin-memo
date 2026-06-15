"""The distill suite's data-filter arms: each yields a curated entry set.

The comparison axis is the source-store filter. ``base_model`` (no training)
and ``retrieval`` (the existing store eval) are handled in run.py; this module
builds the three distillation sources.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from darwin_memo import MemoryEntry, MemoryStore, StorageEnv, SurvivalConfig

from ..fixtures import build_headline_store
from ..policies import run_keep_everything, run_survival

DISTILL_ARMS = (
    "base_model",
    "distill_raw",
    "distill_survivor",
    "distill_judge",
    "retrieval",
)


def _curate(run_fn: Any, seed: int, files_per_cycle: int) -> MemoryStore:
    store = build_headline_store()
    workdir = Path(tempfile.mkdtemp(prefix="darwin-memo-distill-"))
    try:
        env = StorageEnv(root=workdir, files_per_cycle=files_per_cycle, seed=seed)
        run_fn(store, env)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return store


def survivor_set(
    seed: int, cycles: int = 30, files_per_cycle: int = 12
) -> tuple[list[MemoryEntry], MemoryStore]:
    """Energy-ledger survivors (poison starved/buried). Returns (alive, store);
    the store backs the ``retrieval`` reference row."""
    store = _curate(
        lambda s, e: run_survival(
            s, e, cycles, seed, SurvivalConfig(write_experience=False)
        ),
        seed,
        files_per_cycle,
    )
    return store.alive(), store


def raw_set(seed: int, cycles: int = 30, files_per_cycle: int = 12) -> list[MemoryEntry]:
    """The unfiltered population (poison intact)."""
    store = _curate(lambda s, e: run_keep_everything(s, e, cycles), seed, files_per_cycle)
    return store.alive()


def judge_set(
    seed: int,
    judge_model: str,
    cycles: int = 30,
    files_per_cycle: int = 12,
    timeout: float = 600.0,
) -> tuple[list[MemoryEntry], dict[str, Any]]:
    """LLM-judge-kept set. Returns (alive, judge observability metrics)."""
    from darwin_memo import OllamaClient

    from ..judge import run_judge_settled

    judge = OllamaClient(model=judge_model, timeout=timeout, max_tokens=2048)
    store = build_headline_store()
    workdir = Path(tempfile.mkdtemp(prefix="darwin-memo-distill-judge-"))
    try:
        env = StorageEnv(root=workdir, files_per_cycle=files_per_cycle, seed=seed)
        result = run_judge_settled(store, env, cycles, judge)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return store.alive(), dict(getattr(result, "extra_metrics", {}) or {})
