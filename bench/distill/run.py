"""The distill suite: survival-as-data-filter, measured parametrically.

Per seed it builds the curated sets, LoRA-distills survivor/raw (and judge,
opt-in), then scores every model AND the untrained base on the fixed probes,
plus a ``retrieval`` reference row from the existing store eval.
"""

from __future__ import annotations

import gc
import platform
import sys
import tempfile
from typing import Any

import darwin_memo

from ..fixtures import evaluate_probes
from . import arms as A
from .eval import evaluate_probes_parametric
from .train import train_lora

SCHEMA_VERSION = 1


def _meta() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": sys.platform,
        "darwin_memo": darwin_memo.__version__,
    }


def _record(arm: str, seed: int, config: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": "distill",
        "arm": arm,
        "seed": seed,
        "config": config,
        "metrics": metrics,
        "meta": _meta(),
    }


def _free(*objs: Any) -> None:
    for o in objs:
        del o
    gc.collect()
    try:
        import torch

        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


def _load_base(base_model: str) -> tuple[Any, Any]:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model = AutoModelForCausalLM.from_pretrained(base_model)
    model.eval()
    tok = AutoTokenizer.from_pretrained(base_model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return model, tok


def _load_adapter(path: str) -> tuple[Any, Any]:
    from peft import AutoPeftModelForCausalLM
    from transformers import AutoTokenizer

    model = AutoPeftModelForCausalLM.from_pretrained(path)
    model.eval()
    tok = AutoTokenizer.from_pretrained(path)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return model, tok


def _distill_and_eval(
    entries: list[Any], base_model: str, config: dict[str, Any], seed: int
) -> dict[str, Any]:
    out = tempfile.mkdtemp(prefix="tmp-distill-")
    train = train_lora(
        entries,
        base_model=base_model,
        out_dir=out,
        epochs=config["epochs"],
        lr=config["lr"],
        mask_prompt=config["mask_prompt"],
        seed=seed,
    )
    model, tok = _load_adapter(out)
    metrics = evaluate_probes_parametric(model, tok)
    metrics.update(
        {
            "train_wall_s": train["train_wall_s"],
            "trainable_params": train["trainable_params"],
            "n_train": train["n_train"],
        }
    )
    _free(model)
    return metrics


def distill_run(
    seeds: list[int],
    *,
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct",
    epochs: int = 3,
    lr: float = 2e-4,
    mask_prompt: bool = True,
    corpus: str = "headline",
    cycles: int = 30,
    files_per_cycle: int = 12,
    with_judge: bool = False,
    judge_model: str = "llama3.2:3b",
) -> list[dict[str, Any]]:
    config = {
        "base_model": base_model,
        "epochs": epochs,
        "lr": lr,
        "mask_prompt": mask_prompt,
        "corpus": corpus,
        "cycles": cycles,
    }
    runs: list[dict[str, Any]] = []
    for seed in seeds:
        survivors, surv_store = A.survivor_set(seed, cycles, files_per_cycle)
        raw = A.raw_set(seed, cycles, files_per_cycle)

        # base_model: untrained floor (zero training cost).
        base, btok = _load_base(base_model)
        base_metrics = evaluate_probes_parametric(base, btok)
        base_metrics.update({"train_wall_s": 0.0, "trainable_params": 0, "n_train": 0})
        runs.append(_record("base_model", seed, config, base_metrics))
        _free(base)

        # retrieval: the existing store eval over the survivor store (no model).
        retr = evaluate_probes(surv_store)
        retr.update({"train_wall_s": 0.0, "trainable_params": 0, "n_train": len(survivors)})
        runs.append(_record("retrieval", seed, config, retr))

        runs.append(
            _record(
                "distill_survivor",
                seed,
                config,
                _distill_and_eval(survivors, base_model, config, seed),
            )
        )
        runs.append(
            _record(
                "distill_raw", seed, config, _distill_and_eval(raw, base_model, config, seed)
            )
        )

        if with_judge:
            judged, judge_extra = A.judge_set(seed, judge_model, cycles, files_per_cycle)
            jm = _distill_and_eval(judged, base_model, config, seed)
            jm.update({f"judge_{k}": v for k, v in judge_extra.items()})
            runs.append(
                _record("distill_judge", seed, {**config, "judge_model": judge_model}, jm)
            )

        print(f"seed {seed} done ({'with' if with_judge else 'no'} judge)")
    return runs
