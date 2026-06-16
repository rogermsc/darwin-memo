"""The distill_merge suite: continual learning via LoRA task-vector merging.

Per seed it distills one survivor-filtered adapter per disjoint corpus, then
evaluates each adapter alone (solo), their merges (cat/linear/ties), and a
joint adapter trained on the union (the retrain-everything upper bound) — all
scored on every part's probes plus poison reproduction.
"""

from __future__ import annotations

import tempfile
from typing import Any

from . import arms as A
from .corpus import build_split_corpora
from .eval import evaluate_recall_per_part
from .run import _free, _load_adapter, _load_base, _meta
from .train import train_lora

SCHEMA_VERSION = 1


def _record(
    arm: str, seed: int, config: dict[str, Any], metrics: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": "distill_merge",
        "arm": arm,
        "seed": seed,
        "config": config,
        "metrics": metrics,
        "meta": _meta(),
    }


def _merge_eval(
    adapter_dirs: list[str], parts: list[Any], method: str
) -> dict[str, Any]:
    from peft import AutoPeftModelForCausalLM
    from transformers import AutoTokenizer

    model = AutoPeftModelForCausalLM.from_pretrained(adapter_dirs[0], adapter_name="p0")
    for k, d in enumerate(adapter_dirs[1:], start=1):
        model.load_adapter(d, adapter_name=f"p{k}")
    model.eval()
    tok = AutoTokenizer.from_pretrained(adapter_dirs[0])
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    names = [f"p{k}" for k in range(len(adapter_dirs))]
    kwargs: dict[str, Any] = {
        "weights": [1.0] * len(names),
        "combination_type": method,
    }
    if method == "ties":
        kwargs["density"] = 0.5
    model.add_weighted_adapter(names, adapter_name="merged", **kwargs)
    model.set_adapter("merged")
    metrics = evaluate_recall_per_part(model, tok, parts)
    _free(model)
    return metrics


def merge_run(
    seeds: list[int],
    *,
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct",
    epochs: int = 3,
    lr: float = 2e-4,
    n_good: int = 15,
    n_poison: int = 3,
    parts: int = 2,
    cycles: int = 40,
    per_cycle: int = 12,
    merge_methods: tuple[str, ...] = ("cat", "linear", "ties"),
) -> list[dict[str, Any]]:
    corpora = build_split_corpora(n_good, n_poison, parts)
    config = {
        "base_model": base_model,
        "epochs": epochs,
        "lr": lr,
        "n_good": n_good,
        "n_poison": n_poison,
        "parts": parts,
        "cycles": cycles,
    }
    runs: list[dict[str, Any]] = []
    for seed in seeds:
        adapter_dirs: list[str] = []
        part_survivors: list[list[Any]] = []
        for i, corpus in enumerate(corpora):
            survivors, _store = A.survivor_set(corpus, seed, cycles, per_cycle)
            part_survivors.append(survivors)
            out = tempfile.mkdtemp(prefix=f"tmp-merge-p{i}-")
            train_lora(
                survivors,
                base_model=base_model,
                out_dir=out,
                epochs=epochs,
                lr=lr,
                seed=seed,
            )
            adapter_dirs.append(out)
        all_survivors = [e for sub in part_survivors for e in sub]

        # base_model floor
        base, btok = _load_base(base_model)
        bm = evaluate_recall_per_part(base, btok, corpora)
        bm.update({"n_train": 0, "train_wall_s": 0.0, "trainable_params": 0})
        runs.append(_record("base_model", seed, config, bm))
        _free(base)

        # solo adapters (each knows only its own part)
        for i, d in enumerate(adapter_dirs):
            m, t = _load_adapter(d)
            sm = evaluate_recall_per_part(m, t, corpora)
            sm.update(
                {
                    "n_train": len(part_survivors[i]),
                    "train_wall_s": 0.0,
                    "trainable_params": 0,
                }
            )
            runs.append(_record(f"solo_part{i}", seed, config, sm))
            _free(m)

        # merges
        for method in merge_methods:
            try:
                mm = _merge_eval(adapter_dirs, corpora, method)
                mm.update(
                    {
                        "n_train": len(all_survivors),
                        "train_wall_s": 0.0,
                        "trainable_params": 0,
                    }
                )
            except Exception as exc:
                mm = {
                    "recall_all": 0.0,
                    "poison_reproduction": 0.0,
                    "n_train": 0,
                    "note": f"merge {method} failed: {type(exc).__name__}: {exc}",
                }
            runs.append(_record(f"merged_{method}", seed, config, mm))

        # joint upper bound (train on the union)
        out = tempfile.mkdtemp(prefix="tmp-merge-joint-")
        jtr = train_lora(
            all_survivors,
            base_model=base_model,
            out_dir=out,
            epochs=epochs,
            lr=lr,
            seed=seed,
        )
        m, t = _load_adapter(out)
        jm = evaluate_recall_per_part(m, t, corpora)
        jm.update(
            {
                "n_train": len(all_survivors),
                "train_wall_s": jtr["train_wall_s"],
                "trainable_params": jtr["trainable_params"],
            }
        )
        runs.append(_record("joint", seed, config, jm))
        _free(m)

        counts = [len(s) for s in part_survivors]
        print(f"seed {seed} done | parts={parts} survivors={counts}")
    return runs
