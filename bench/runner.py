"""Run one (arm, seed) benchmark and extract the metrics block."""

from __future__ import annotations

import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import darwin_memo
from darwin_memo import MemoryStore, StorageEnv, SurvivalConfig, TestSuiteEnv
from darwin_memo.retrieval import (
    EMBEDDING_MERGE_THRESHOLD,
    EmbeddingRetriever,
    HashingEmbedder,
    LexicalRetriever,
)

from .adversary import AdversarialStorageEnv
from .fixtures import (
    active_poison_alive,
    build_headline_store,
    poison_ids,
    evaluate_paraphrase_probes,
    evaluate_probes,
)
from .memsec import build_memsec_store
from .noise import FlakyStorageEnv
from .policies import (
    CycleRecord,
    PolicyResult,
    run_evict_consecutive,
    run_evict_on_negative,
    run_keep_everything,
    run_policy_bandit,
    run_quarantine,
    run_random_matched,
    run_recency,
    run_salience_matched,
    run_survival,
    run_ttl,
)
from .testsuite_fixtures import (
    build_testsuite_store,
    evaluate_testsuite_paraphrase_probes,
    evaluate_testsuite_probes,
)
from .testsuite_noise import FlakyTestSuiteEnv

if TYPE_CHECKING:
    from .llm_arm import AuditedProtocol

SCHEMA_VERSION = 1
TAIL = 5

# Both noise wrappers and the adversary expose the same accounting
# surface (true vs reported per-cycle deltas, fired-lie counters, the
# distortion sum), so everything downstream of env construction treats
# them as one type.
FlakyEnv = FlakyStorageEnv | FlakyTestSuiteEnv | AdversarialStorageEnv


def _env_family(overrides: dict[str, Any]) -> str:
    """Which environment family a run belongs to; storage is the default.

    The family rides in overrides so it lands in the recorded config
    (and therefore the manifest's config hash) without widening every
    suite's RunSpec.
    """
    family = str(overrides.get("env_family", "storage"))
    if family not in ("storage", "testsuite"):
        raise ValueError(f"unknown env_family: {family!r}")
    return family


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
    if "attack" in overrides:
        if _env_family(overrides) == "testsuite":
            raise ValueError(
                "attack classes are written against the storage corpus; "
                "TestSuiteEnv has its own poison and no attack taxonomy"
            )
        return build_memsec_store(
            attack=overrides["attack"],
            content_filter=bool(overrides.get("content_filter", False)),
            upkeep=upkeep,
        )
    build = (
        build_testsuite_store
        if _env_family(overrides) == "testsuite"
        else build_headline_store
    )
    if arm == "survival_embedding":
        if "min_coverage" in overrides:
            raise ValueError(
                "min_coverage is a lexical-retriever knob and has no effect "
                "on survival_embedding; refusing to record a config that "
                "claims a variation that never took effect"
            )
        retriever = EmbeddingRetriever(HashingEmbedder(), min_similarity=0.30)
        return build(upkeep=upkeep, retriever=retriever)
    if "min_coverage" in overrides:
        lexical = LexicalRetriever(min_coverage=overrides["min_coverage"])
        return build(upkeep=upkeep, retriever=lexical)
    return build(upkeep=upkeep)


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
        env: StorageEnv | TestSuiteEnv
        if _env_family(overrides) == "testsuite":
            env = TestSuiteEnv(
                root=workdir,
                defects_per_cycle=int(overrides.get("defects_per_cycle", 3)),
                seed=seed,
            )
        else:
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
    transcript_path: Path | None = None,
) -> dict[str, Any]:
    overrides = dict(overrides or {})
    family = _env_family(overrides)
    workdir = Path(tempfile.mkdtemp(prefix=f"darwin-memo-bench-{arm}-"))
    store = _build_store(overrides, arm)
    env: StorageEnv | TestSuiteEnv | FlakyEnv
    if family == "testsuite":
        if "noise_model" in overrides:
            raise ValueError(
                "noise_model is a StorageEnv knob; TestSuiteEnv has one "
                "noise model (flaky pass counts), selected by flake_rate"
            )
        if "lie_budget" in overrides:
            raise ValueError(
                "lie_budget is a StorageEnv knob; the curation-targeted "
                "adversary is not implemented for TestSuiteEnv"
            )
        defects = int(overrides.get("defects_per_cycle", 3))
        if "flake_rate" in overrides:
            env = FlakyTestSuiteEnv(
                root=workdir,
                defects_per_cycle=defects,
                seed=seed,
                flake_rate=overrides["flake_rate"],
            )
        else:
            env = TestSuiteEnv(root=workdir, defects_per_cycle=defects, seed=seed)
    elif "lie_budget" in overrides:
        if "flake_rate" in overrides:
            raise ValueError(
                "lie_budget and flake_rate are two different threat models "
                "(adaptive adversary vs random noise); running both at once "
                "would attribute the result to neither"
            )
        env = AdversarialStorageEnv(
            root=workdir,
            files_per_cycle=files_per_cycle,
            seed=seed,
            lie_budget=overrides["lie_budget"],
        )
    elif "flake_rate" in overrides:
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

    # Two different deaths, and conflating them would misreport the
    # inert attack class entirely. "cycle" is when the last poisoned
    # entry that ADVISES ACTION is gone (revocation by consequence);
    # "starve" is when the last poisoned entry of any kind is gone,
    # which for an entry that never acts can only happen by upkeep.
    kill_tracker: dict[str, int | None] = {"cycle": None, "starve": None}

    def on_cycle(cycle: int, record: CycleRecord) -> None:
        if kill_tracker["cycle"] is None and not active_poison_alive(store):
            kill_tracker["cycle"] = cycle
        if kill_tracker["starve"] is None and not poison_ids(store):
            kill_tracker["starve"] = cycle

    # The LLM arm's protocol is built here, not in _dispatch, because
    # the audit trail (per-answer attribution paths, raw completions)
    # must outlive the dispatch to reach metrics and the transcript.
    audit: AuditedProtocol | None = None
    if arm == "survival_llm":
        from .llm_arm import build_audited_protocol

        audit = build_audited_protocol(store, overrides)

    start = time.perf_counter()
    try:
        result = _dispatch(
            arm, store, env, cycles, seed, files_per_cycle, overrides, on_cycle, audit
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    wall = time.perf_counter() - start

    # Under measurement noise the arms decide off REPORTED deltas, but
    # outcome metrics are computed from the TRUE resource movement: the
    # benchmark scores what actually happened to the disk, exactly the
    # position of a system whose CI sometimes lies to it.
    flaky = env if isinstance(env, FlakyEnv) else None
    if flaky is not None:
        _check_accounting(flaky, result)
    metrics = extract_metrics(
        result,
        store,
        kill_tracker["cycle"],
        wall,
        env=flaky,
        env_family=family,
        starve_cycle=kill_tracker["starve"],
    )
    # Arms may carry arm-specific observability (the judge arm's call,
    # cull, and parse-failure counts). Folded in as extra keys, never
    # required ones: report --check's required set stays suite-uniform.
    extra = getattr(result, "extra_metrics", None)
    if extra:
        metrics.update(extra)
    # The write-time filter's own behaviour, recorded beside what the
    # memory then did: a TPR alone says nothing about harm prevented.
    filter_stats = getattr(store, "filter_stats", None)
    if filter_stats:
        metrics.update(filter_stats)
    # The LLM arm folds its per-answer attribution-path rates the same
    # way, and writes the raw completions out as a transcript.
    if audit is not None:
        from .llm_arm import citation_metrics, write_transcript

        metrics.update(citation_metrics(audit.answers))
        if transcript_path is not None:
            write_transcript(
                transcript_path,
                audit.answers,
                header={"arm": arm, "seed": seed, "config": overrides},
                files_per_cycle=files_per_cycle,
            )

    run: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "suite": suite,
        "arm": arm,
        "seed": seed,
        # files_per_cycle is a StorageEnv knob; recording it on a
        # testsuite run would claim a variation that never took effect,
        # so the family's configs carry defects_per_cycle instead.
        "config": {
            "cycles": cycles,
            **({} if family == "testsuite" else {"files_per_cycle": files_per_cycle}),
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
    if isinstance(env, FlakyEnv):
        run["per_cycle_true_delta"] = list(env.true_deltas)
    return run


def _dispatch(
    arm: str,
    store: Any,
    env: StorageEnv | TestSuiteEnv | FlakyEnv,
    cycles: int,
    seed: int,
    files_per_cycle: int,
    overrides: dict[str, Any],
    on_cycle: Any,
    audit: AuditedProtocol | None = None,
) -> PolicyResult:
    # The adversary lies about measurements too, so every arm that is
    # undefined under noise is undefined under attack for the same
    # reasons: a shadow schedule derived from an unattacked world, or an
    # in-loop component reading detail strings that name the truth.
    noisy = "flake_rate" in overrides or "lie_budget" in overrides
    if noisy and arm in (
        "random_matched",
        "salience_matched",
        "survival_writes",
        "judge_settled",
    ):
        # random_matched's (and salience_matched's) shadow run would
        # derive its death schedule from a noise-free world, silently
        # violating "same pruning rate". survival_writes folds outcome
        # detail strings (which
        # name the true delta) back into entries and picks its best
        # trajectory by the REPORTED delta. judge_settled reads outcome
        # detail strings too, and the corrupted ones name both the
        # reported and the true delta, ground truth no in-loop component
        # may see. None of the three is defined under measurement noise,
        # so all are refused loudly.
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
        # Not deterministic, never in CI. The audited protocol arrives
        # from run_one so the attribution trail survives the dispatch;
        # llm_arm.build_audited_protocol reads the llm_* overrides.
        if audit is None:
            raise ValueError("survival_llm needs the audited protocol")
        return run_survival(
            store,
            env,
            cycles,
            seed,
            _survival_config(overrides, False),
            on_cycle,
            protocol=audit,
        )
    if arm == "judge_settled":
        # Settlement by LLM verdict instead of measured outcomes: the
        # literature control for "no judge anywhere". Sampled, opt-in,
        # never CI, same tier as survival_llm. The generous timeout is
        # queueing, not generation: a local server runs one job at a
        # time and this request may wait behind someone else's.
        from darwin_memo import OllamaClient

        from .judge import run_judge_settled

        judge = OllamaClient(
            model=str(overrides.get("judge_model", "llama3.2:3b")),
            timeout=float(overrides.get("judge_timeout", 600.0)),
            max_tokens=int(overrides.get("judge_max_tokens", 2048)),
        )
        return run_judge_settled(store, env, cycles, judge, on_cycle)
    if arm == "policy_bandit":
        return run_policy_bandit(
            store,
            env,
            cycles,
            on_cycle,
            threshold=float(overrides.get("bandit_threshold", 0.5)),
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
    if arm == "salience_matched":
        # External-literature control: same eviction budget as survival
        # (the shadow death schedule), victims chosen by a Generative
        # Agents-style salience score instead of at random or by outcome.
        schedule = _death_schedule_for(seed, cycles, files_per_cycle, overrides)
        return run_salience_matched(store, env, cycles, schedule, on_cycle=on_cycle)
    raise ValueError(f"unknown arm: {arm}")


def _check_accounting(env: FlakyEnv, result: PolicyResult) -> None:
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
    env: FlakyEnv | None = None,
    env_family: str = "storage",
    starve_cycle: int | None = None,
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
        # Poison of ANY kind, including entries that advise no action
        # and can therefore only be removed by upkeep.
        "poison_starve_cycle": starve_cycle,
        "poison_alive_final": len(poison_ids(store)),
        "wall_time_s": round(wall_time_s, 4),
        # Uniform schema across suites: zero/equal when nothing lies.
        "reported_cum_delta": sum(reported),
        "flakes_marked": env.flakes_marked if env else 0,
        "flakes_fired": env.flakes_fired if env else 0,
        "fired_false_bad": env.fired_false_bad if env else 0,
        "fired_false_good": env.fired_false_good if env else 0,
    }
    if env_family == "testsuite":
        probe_scores = evaluate_testsuite_probes(store)
        paraphrase_scores = evaluate_testsuite_paraphrase_probes(store)
    else:
        probe_scores = evaluate_probes(store)
        paraphrase_scores = evaluate_paraphrase_probes(store)
    metrics.update({f"probe_{k}": v for k, v in probe_scores.items()})
    metrics.update({f"paraphrase_{k}": v for k, v in paraphrase_scores.items()})
    return metrics
