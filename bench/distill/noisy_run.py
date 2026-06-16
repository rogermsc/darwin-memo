"""distill_noisy: does survival's forgiveness preserve distilled capability
that a counter destroys under noisy measurement?

Grid: {clean, flip@flake_rate} x {survival, evict_k1, evict_consecutive,
keep_everything}. Each curated set is distilled and scored on the fixed probes;
the headline is good_recall (poison stays ~0 for filtered arms and is reported,
not headlined).
"""

from __future__ import annotations

import tempfile
from typing import Any

from darwin_memo import VerifiableQAEnv

from .arms import consecutive_set, counter_set, raw_set, survivor_set
from .corpus import build_qa_corpus
from .eval import evaluate_distill_parametric
from .noise import FlakyQAEnv
from .run import _free, _load_adapter, _load_base, _meta
from .train import train_lora

SCHEMA_VERSION = 1
_FILTERS = ("survival", "evict_k1", "evict_consecutive", "keep_everything")
_SETTERS = {
    "survival": survivor_set,
    "evict_k1": counter_set,
    "evict_consecutive": consecutive_set,
    "keep_everything": raw_set,
}


def _record(
    arm: str, seed: int, config: dict[str, Any], metrics: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": "distill_noisy",
        "arm": arm,
        "seed": seed,
        "config": config,
        "metrics": metrics,
        "meta": _meta(),
    }


def noisy_run(
    seeds: list[int],
    *,
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct",
    epochs: int = 15,
    lr: float = 2e-4,
    n_good: int = 30,
    n_poison: int = 6,
    flake_rate: float = 0.2,
    noise_model: str = "flip",
    cycles: int = 40,
    per_cycle: int = 12,
) -> list[dict[str, Any]]:
    corpus = build_qa_corpus(n_good=n_good, n_poison=n_poison)

    def clean_env(c: Any, seed: int, pc: int) -> Any:
        return VerifiableQAEnv(c.qa_pairs, per_cycle=pc, seed=seed)

    def flaky_env(c: Any, seed: int, pc: int) -> Any:
        return FlakyQAEnv(
            c.qa_pairs,
            per_cycle=pc,
            seed=seed,
            flake_rate=flake_rate,
            noise_model=noise_model,
        )

    conditions = [("clean", 0.0, clean_env), (noise_model, flake_rate, flaky_env)]
    runs: list[dict[str, Any]] = []
    for seed in seeds:
        base, btok = _load_base(base_model)
        bm = evaluate_distill_parametric(
            base, btok, corpus.good_probes, corpus.poison_probes
        )
        bm.update({"n_train": 0, "train_wall_s": 0.0, "trainable_params": 0})
        runs.append(
            _record("base_model", seed, {"condition": "clean", "flake_rate": 0.0}, bm)
        )
        _free(base)

        for cond_name, rate, factory in conditions:
            config = {
                "base_model": base_model,
                "epochs": epochs,
                "lr": lr,
                "n_good": n_good,
                "n_poison": n_poison,
                "condition": cond_name,
                "noise_model": noise_model,
                "flake_rate": rate,
                "cycles": cycles,
            }
            for fname in _FILTERS:
                alive, _store = _SETTERS[fname](
                    corpus, seed, cycles, per_cycle, env_factory=factory
                )
                if not alive:
                    metrics = {
                        "good_recall": 0.0,
                        "poison_reproduction": 0.0,
                        "n_train": 0,
                        "train_wall_s": 0.0,
                        "trainable_params": 0,
                        "note": "filter left no entries",
                    }
                else:
                    out = tempfile.mkdtemp(prefix="tmp-noisy-")
                    tr = train_lora(
                        alive,
                        base_model=base_model,
                        out_dir=out,
                        epochs=epochs,
                        lr=lr,
                        seed=seed,
                    )
                    m, t = _load_adapter(out)
                    metrics = evaluate_distill_parametric(
                        m, t, corpus.good_probes, corpus.poison_probes
                    )
                    metrics.update(
                        {
                            "n_train": tr["n_train"],
                            "train_wall_s": tr["train_wall_s"],
                            "trainable_params": tr["trainable_params"],
                        }
                    )
                    _free(m)
                runs.append(_record(fname, seed, config, metrics))
            print(f"seed {seed} cond={cond_name} done")
    return runs
