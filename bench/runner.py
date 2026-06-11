"""Run one (arm, seed) benchmark and extract the metrics block."""

from __future__ import annotations

import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import darwin_memo
from darwin_memo import MemoryStore, StorageEnv, SurvivalConfig
from darwin_memo.retrieval import EmbeddingRetriever, HashingEmbedder, LexicalRetriever

from .fixtures import (
    active_poison_alive,
    build_headline_store,
    evaluate_paraphrase_probes,
    evaluate_probes,
)
from .policies import (
    CycleRecord,
    PolicyResult,
    run_evict_on_negative,
    run_keep_everything,
    run_random_matched,
    run_recency,
    run_survival,
    run_ttl,
)

SCHEMA_VERSION = 1
TAIL = 5


def _survival_config(
    overrides: dict[str, Any], write_experience: bool
) -> SurvivalConfig:
    config = SurvivalConfig(write_experience=write_experience)
    for knob in ("credit_gain", "merge_threshold", "consolidate_every"):
        if knob in overrides:
            setattr(config, knob, overrides[knob])
    return config


def _build_store(overrides: dict[str, Any], arm: str = "") -> MemoryStore:
    upkeep = overrides.get("upkeep", 0.05)
    if arm == "survival_embedding":
        retriever = EmbeddingRetriever(HashingEmbedder(), min_similarity=0.30)
        return build_headline_store(upkeep=upkeep, retriever=retriever)
    if "min_coverage" in overrides:
        lexical = LexicalRetriever(min_coverage=overrides["min_coverage"])
        return build_headline_store(upkeep=upkeep, retriever=lexical)
    return build_headline_store(upkeep=upkeep)


def _death_schedule_for(
    seed: int, cycles: int, files_per_cycle: int, overrides: dict[str, Any]
) -> list[int]:
    """Derive the survival arm's death schedule for random_matched."""
    workdir = Path(tempfile.mkdtemp(prefix="darwin-memo-shadow-"))
    try:
        store = _build_store(overrides)
        env = StorageEnv(root=workdir, files_per_cycle=files_per_cycle, seed=seed)
        result = run_survival(
            store, env, cycles, seed, _survival_config(overrides, False)
        )
        return result.death_schedule
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_one(
    arm: str,
    seed: int,
    cycles: int = 30,
    files_per_cycle: int = 12,
    overrides: dict[str, Any] | None = None,
    suite: str = "adhoc",
) -> dict[str, Any]:
    overrides = dict(overrides or {})
    workdir = Path(tempfile.mkdtemp(prefix=f"darwin-memo-bench-{arm}-"))
    store = _build_store(overrides, arm)
    env = StorageEnv(root=workdir, files_per_cycle=files_per_cycle, seed=seed)
    if "resource_scale" in overrides:
        env.resource_scale = overrides["resource_scale"]

    kill_tracker: dict[str, int | None] = {"cycle": None}

    def on_cycle(cycle: int, record: CycleRecord) -> None:
        if kill_tracker["cycle"] is None and not active_poison_alive(store):
            kill_tracker["cycle"] = cycle

    start = time.perf_counter()
    try:
        result = _dispatch(
            arm, store, env, cycles, seed, files_per_cycle, overrides, on_cycle
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    wall = time.perf_counter() - start

    return {
        "schema_version": SCHEMA_VERSION,
        "suite": suite,
        "arm": arm,
        "seed": seed,
        "config": {
            "cycles": cycles,
            "files_per_cycle": files_per_cycle,
            **overrides,
        },
        "per_cycle": [vars(r) for r in result.records],
        "metrics": extract_metrics(result, store, kill_tracker["cycle"], wall),
        "meta": {
            "python": platform.python_version(),
            "platform": sys.platform,
            "darwin_memo": darwin_memo.__version__,
        },
    }


def _dispatch(
    arm: str,
    store: Any,
    env: StorageEnv,
    cycles: int,
    seed: int,
    files_per_cycle: int,
    overrides: dict[str, Any],
    on_cycle: Any,
) -> PolicyResult:
    if arm == "survival":
        return run_survival(
            store, env, cycles, seed, _survival_config(overrides, False), on_cycle
        )
    if arm == "survival_writes":
        return run_survival(
            store, env, cycles, seed, _survival_config(overrides, True), on_cycle
        )
    if arm == "survival_embedding":
        # Cosine similarity runs hotter than Jaccard; the README's own
        # recommendation for embedding retrievers is a higher threshold.
        config = _survival_config(overrides, False)
        if "merge_threshold" not in overrides:
            config.merge_threshold = 0.85
        return run_survival(store, env, cycles, seed, config, on_cycle)
    if arm == "survival_llm":
        # Opt-in: the full 3-stage protocol answered by a local model.
        # Not deterministic, never in CI; this is the at-home recipe for
        # the question the docs flag as open (does citation-based credit
        # keep selection working under synthesis?).
        from darwin_memo import OllamaClient, QueryProtocol

        client = OllamaClient(model=str(overrides.get("llm_model", "llama3.2")))
        protocol = QueryProtocol(store, client)
        return run_survival(
            store,
            env,
            cycles,
            seed,
            _survival_config(overrides, False),
            on_cycle,
            protocol=protocol,
        )
    if arm == "evict_on_negative":
        return run_evict_on_negative(store, env, cycles, seed, on_cycle)
    if arm == "keep_everything":
        return run_keep_everything(store, env, cycles, seed, on_cycle)
    if arm == "ttl":
        return run_ttl(store, env, cycles, seed, on_cycle=on_cycle)
    if arm == "recency":
        return run_recency(store, env, cycles, seed, on_cycle=on_cycle)
    if arm == "random_matched":
        schedule = _death_schedule_for(seed, cycles, files_per_cycle, overrides)
        return run_random_matched(store, env, cycles, seed, schedule, on_cycle=on_cycle)
    raise ValueError(f"unknown arm: {arm}")


def extract_metrics(
    result: PolicyResult,
    store: Any,
    kill_cycle: int | None,
    wall_time_s: float,
) -> dict[str, Any]:
    deltas = [r.resource_delta for r in result.records]
    negatives = [d for d in deltas if d < 0]
    damage_window = deltas[: kill_cycle + 1] if kill_cycle is not None else deltas
    tail = deltas[-TAIL:] if len(deltas) >= TAIL else deltas
    metrics: dict[str, Any] = {
        "poison_killed": kill_cycle is not None,
        "poison_kill_cycle": kill_cycle,
        "damage_before_kill": sum(d for d in damage_window if d < 0),
        "cum_delta": sum(deltas),
        "cum_negative_delta": sum(negatives),
        "tail_delta_mean": sum(tail) / len(tail) if tail else 0.0,
        "final_population": len(store),
        "wall_time_s": round(wall_time_s, 4),
    }
    metrics.update({f"probe_{k}": v for k, v in evaluate_probes(store).items()})
    metrics.update(
        {f"paraphrase_{k}": v for k, v in evaluate_paraphrase_probes(store).items()}
    )
    return metrics
