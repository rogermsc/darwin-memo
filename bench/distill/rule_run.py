"""distill_rule (Exp B): does benign-distribution poison generalize into the
weights on held-out questions, and does survival prevent it?

Conditions: {survival, evict_k1, raw} under clean and flip. Each is distilled
and scored on HELD-OUT services never trained/selected, so harm_generalization
measures generalization of the corrupted rule (not verbatim membership).
"""

from __future__ import annotations

import tempfile
from typing import Any

from darwin_memo import MemoryEntry, MemoryStore, SurvivalConfig, VerifiableQAEnv

from ..policies import run_evict_on_negative, run_keep_everything, run_survival
from .eval import evaluate_rule_generalization
from .noise import FlakyQAEnv
from .rule_corpus import HARM_TOKEN, SAFE_TOKEN, RuleCorpus, build_rule_corpus
from .run import _free, _load_adapter, _meta
from .train import train_lora

SCHEMA_VERSION = 1
_NO_CONSOLIDATE = 9999


def _store(rc: RuleCorpus) -> MemoryStore:
    s = MemoryStore()
    for e in rc.entries:
        s.add(
            MemoryEntry(question=e.question, answer=e.answer, sources=list(e.sources))
        )
    return s


def _record(
    arm: str, seed: int, config: dict[str, Any], metrics: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": "distill_rule",
        "arm": arm,
        "seed": seed,
        "config": config,
        "metrics": metrics,
        "meta": _meta(),
    }


def rule_run(
    seeds: list[int],
    *,
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct",
    epochs: int = 15,
    lr: float = 2e-4,
    flake_rate: float = 0.2,
    cycles: int = 40,
    per_cycle: int = 12,
) -> list[dict[str, Any]]:
    rc = build_rule_corpus(10, 5, 5)
    cfg = SurvivalConfig(write_experience=False, consolidate_every=_NO_CONSOLIDATE)
    filters = {
        "survival": lambda s, e, sd: run_survival(s, e, cycles, sd, cfg),
        "evict_k1": lambda s, e, sd: run_evict_on_negative(s, e, cycles, strikes=1),
        "raw": lambda s, e, sd: run_keep_everything(s, e, cycles),
    }
    runs: list[dict[str, Any]] = []
    for seed in seeds:
        for cond, make_env in [
            (
                "clean",
                lambda sd: VerifiableQAEnv(rc.qa_pairs, per_cycle=per_cycle, seed=sd),
            ),
            (
                "flip",
                lambda sd: FlakyQAEnv(
                    rc.qa_pairs, per_cycle=per_cycle, seed=sd, flake_rate=flake_rate
                ),
            ),
        ]:
            for fname, run_fn in filters.items():
                store = _store(rc)
                run_fn(store, make_env(seed), seed)
                alive = store.alive()
                config = {
                    "base_model": base_model,
                    "epochs": epochs,
                    "condition": cond,
                    "flake_rate": flake_rate if cond == "flip" else 0.0,
                }
                if not alive:
                    metrics = {
                        "harm_generalization": 0.0,
                        "safe_generalization": 0.0,
                        "n_train": 0,
                        "note": "filter left no entries",
                    }
                else:
                    out = tempfile.mkdtemp(prefix="tmp-rule-")
                    train_lora(
                        alive,
                        base_model=base_model,
                        out_dir=out,
                        epochs=epochs,
                        lr=lr,
                        seed=seed,
                    )
                    m, t = _load_adapter(out)
                    metrics = evaluate_rule_generalization(
                        m, t, rc.heldout_probes, SAFE_TOKEN, HARM_TOKEN
                    )
                    metrics["n_train"] = len(alive)
                    _free(m)
                runs.append(_record(fname, seed, config, metrics))
            print(f"seed {seed} cond={cond} done")
    return runs
