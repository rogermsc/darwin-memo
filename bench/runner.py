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
from darwin_memo.retrieval import (
    EMBEDDING_MERGE_THRESHOLD,
    EmbeddingRetriever,
    HashingEmbedder,
    LexicalRetriever,
)

from .fixtures import (
    active_poison_alive,
    build_headline_store,
    evaluate_paraphrase_probes,
    evaluate_probes,
)
from .noise import FlakyStorageEnv
from .policies import (
    CycleRecord,
    PolicyResult,
    run_evict_consecutive,
    run_evict_on_negative,
    run_keep_everything,
    run_quarantine,
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
        if "min_coverage" in overrides:
            raise ValueError(
                "min_coverage is a lexical-retriever knob and has no effect "
                "on survival_embedding; refusing to record a config that "
                "claims a variation that never took effect"
            )
        retriever = EmbeddingRetriever(HashingEmbedder(), min_similarity=0.30)
        return build_headline_store(upkeep=upkeep, retriever=retriever)
    if "min_coverage" in overrides:
        lexical = LexicalRetriever(min_coverage=overrides["min_coverage"])
        return build_headline_store(upkeep=upkeep, retriever=lexical)
    return build_headline_store(upkeep=upkeep)


_schedule_memo: dict[tuple[Any, ...], list[int]] = {}


def _death_schedule_for(
    seed: int, cycles: int, files_per_cycle: int, overrides: dict[str, Any]
) -> list[int]:
    """Derive the survival arm's death schedule for random_matched.

    The shadow run must be configured EXACTLY like the survival arm it
    is matched against (including resource_scale, which lives on the
    env), or "same pruning rate" silently stops being true. Runs are
    deterministic, so the schedule is memoized per configuration.
    """
    key = (seed, cycles, files_per_cycle, tuple(sorted(overrides.items())))
    if key in _schedule_memo:
        return _schedule_memo[key]
    workdir = Path(tempfile.mkdtemp(prefix="darwin-memo-shadow-"))
    try:
        store = _build_store(overrides)
        env = StorageEnv(root=workdir, files_per_cycle=files_per_cycle, seed=seed)
        if "resource_scale" in overrides:
            env.resource_scale = overrides["resource_scale"]
        result = run_survival(
            store, env, cycles, seed, _survival_config(overrides, False)
        )
        _schedule_memo[key] = result.death_schedule
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
    env: StorageEnv | FlakyStorageEnv
    if "flake_rate" in overrides:
        env = FlakyStorageEnv(
            root=workdir,
            files_per_cycle=files_per_cycle,
            seed=seed,
            flake_rate=overrides["flake_rate"],
            noise_model=overrides.get("noise_model", "flip"),
        )
    else:
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

    # Under measurement noise the arms decide off REPORTED deltas, but
    # outcome metrics are computed from the TRUE resource movement: the
    # benchmark scores what actually happened to the disk, exactly the
    # position of a system whose CI sometimes lies to it.
    flaky = env if isinstance(env, FlakyStorageEnv) else None
    if flaky is not None:
        _check_accounting(flaky, result)
    metrics = extract_metrics(result, store, kill_tracker["cycle"], wall, env=flaky)

    run: dict[str, Any] = {
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
        "metrics": metrics,
        "meta": {
            "python": platform.python_version(),
            "platform": sys.platform,
            "darwin_memo": darwin_memo.__version__,
        },
    }
    if isinstance(env, FlakyStorageEnv):
        run["per_cycle_true_delta"] = list(env.true_deltas)
    return run


def _dispatch(
    arm: str,
    store: Any,
    env: StorageEnv | FlakyStorageEnv,
    cycles: int,
    seed: int,
    files_per_cycle: int,
    overrides: dict[str, Any],
    on_cycle: Any,
) -> PolicyResult:
    noisy = "flake_rate" in overrides
    if noisy and arm in ("random_matched", "survival_writes"):
        # random_matched's shadow run would derive its death schedule
        # from a noise-free world, silently violating "same pruning
        # rate". survival_writes folds outcome detail strings (which
        # name the true delta) back into entries and picks its best
        # trajectory by the REPORTED delta; neither behavior is defined
        # under measurement noise, so both are refused loudly.
        raise ValueError(f"{arm} is not defined under measurement noise")
    if arm == "survival":
        return run_survival(
            store, env, cycles, seed, _survival_config(overrides, False), on_cycle
        )
    if arm == "survival_writes":
        return run_survival(
            store, env, cycles, seed, _survival_config(overrides, True), on_cycle
        )
    if arm == "survival_embedding":
        config = _survival_config(overrides, False)
        if "merge_threshold" not in overrides:
            config.merge_threshold = EMBEDDING_MERGE_THRESHOLD
        return run_survival(store, env, cycles, seed, config, on_cycle)
    if arm == "survival_llm":
        # Opt-in: the full 3-stage protocol answered by a local model.
        # Not deterministic, never in CI; this is the at-home recipe for
        # the question the docs flag as open (does citation-based credit
        # keep selection working under synthesis?).
        from darwin_memo import OllamaClient, QueryProtocol

        client = OllamaClient(
            model=str(overrides.get("llm_model", "llama3.2")),
            timeout=float(overrides.get("llm_timeout", 300.0)),
        )
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
        return run_evict_on_negative(
            store, env, cycles, on_cycle, strikes=int(overrides.get("strikes", 1))
        )
    if arm == "evict_consecutive":
        return run_evict_consecutive(
            store, env, cycles, on_cycle, strikes=int(overrides.get("strikes", 2))
        )
    if arm == "quarantine":
        return run_quarantine(
            store,
            env,
            cycles,
            suspend=int(overrides.get("suspend", 3)),
            on_cycle=on_cycle,
        )
    if arm == "keep_everything":
        return run_keep_everything(store, env, cycles, on_cycle)
    if arm == "ttl":
        return run_ttl(store, env, cycles, on_cycle=on_cycle)
    if arm == "recency":
        return run_recency(store, env, cycles, on_cycle=on_cycle)
    if arm == "random_matched":
        schedule = _death_schedule_for(seed, cycles, files_per_cycle, overrides)
        return run_random_matched(store, env, cycles, seed, schedule, on_cycle=on_cycle)
    raise ValueError(f"unknown arm: {arm}")


def _check_accounting(env: FlakyStorageEnv, result: PolicyResult) -> None:
    """The lie ledger must balance, or the run's numbers are garbage.

    Two identities hold by construction unless cycle indexing drifted:
    the driver's reported delta equals the env's PER CYCLE (element-wise
    on purpose: totals can balance while every per-cycle-windowed
    metric reads a misbooked series), and the true series differs from
    the reported one by exactly the distortion the fired lies injected.
    """
    if len(result.records) != len(env.reported_deltas):
        raise RuntimeError(
            f"flaky accounting: driver ran {len(result.records)} cycles, "
            f"env booked {len(env.reported_deltas)}"
        )
    for record in result.records:
        if abs(record.resource_delta - env.reported_deltas[record.cycle]) > 1e-6:
            raise RuntimeError(
                f"flaky accounting: cycle {record.cycle} driver reported "
                f"{record.resource_delta}, env booked "
                f"{env.reported_deltas[record.cycle]}"
            )
    env_reported = sum(env.reported_deltas)
    env_true = sum(env.true_deltas)
    if abs(env_reported - (env_true + env.distortion)) > 1e-6:
        raise RuntimeError(
            "flaky accounting identity violated: env reported "
            f"{env_reported}, env true {env_true}, distortion {env.distortion}"
        )


def extract_metrics(
    result: PolicyResult,
    store: Any,
    kill_cycle: int | None,
    wall_time_s: float,
    env: FlakyStorageEnv | None = None,
) -> dict[str, Any]:
    reported = [r.resource_delta for r in result.records]
    # TRUE resource movement when measurements lie; identical otherwise.
    deltas = list(env.true_deltas) if env is not None else reported
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
        # Uniform schema across suites: zero/equal when nothing lies.
        "reported_cum_delta": sum(reported),
        "flakes_marked": env.flakes_marked if env else 0,
        "flakes_fired": env.flakes_fired if env else 0,
        "fired_false_bad": env.fired_false_bad if env else 0,
        "fired_false_good": env.fired_false_good if env else 0,
    }
    metrics.update({f"probe_{k}": v for k, v in evaluate_probes(store).items()})
    metrics.update(
        {f"paraphrase_{k}": v for k, v in evaluate_paraphrase_probes(store).items()}
    )
    return metrics
