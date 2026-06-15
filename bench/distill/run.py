"""The distill suite: survival-as-data-filter, measured parametrically.

Per seed it builds the curated sets from one deterministic QA corpus,
LoRA-distills survivor/raw (and judge, opt-in), then measures good_recall and
poison_reproduction on every model AND the untrained base, plus retrieval
reference rows (the same instruments over the survivor and raw stores).
"""

from __future__ import annotations

import gc
import platform
import sys
import tempfile
from typing import Any

import darwin_memo

from . import arms as A
from .corpus import build_qa_corpus
from .eval import evaluate_distill_parametric, evaluate_distill_retrieval
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


def _empty_metrics(note: str) -> dict[str, Any]:
    """An honest record for a filter that left nothing to distill.

    A model trained on zero entries does not exist, so good_recall and
    poison_reproduction are both zero by construction. The note carries the
    cause (e.g. the judge over-culled the store to extinction).
    """
    return {
        "good_recall": 0.0,
        "poison_reproduction": 0.0,
        "train_wall_s": 0.0,
        "trainable_params": 0,
        "n_train": 0,
        "note": note,
    }


def _distill_and_eval(
    entries: list[Any], corpus: Any, base_model: str, config: dict[str, Any], seed: int
) -> dict[str, Any]:
    if not entries:
        return _empty_metrics("empty training set: the filter left no entries")
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
    metrics = evaluate_distill_parametric(
        model, tok, corpus.good_probes, corpus.poison_probes
    )
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
    n_good: int = 30,
    n_poison: int = 6,
    cycles: int = 40,
    per_cycle: int = 12,
    with_judge: bool = False,
    judge_model: str = "llama3.2:3b",
) -> list[dict[str, Any]]:
    corpus = build_qa_corpus(n_good=n_good, n_poison=n_poison)
    config = {
        "base_model": base_model,
        "epochs": epochs,
        "lr": lr,
        "mask_prompt": mask_prompt,
        "n_good": n_good,
        "n_poison": n_poison,
        "cycles": cycles,
    }
    runs: list[dict[str, Any]] = []
    for seed in seeds:
        survivors, surv_store = A.survivor_set(corpus, seed, cycles, per_cycle)
        raw, raw_store = A.raw_set(corpus, seed, cycles, per_cycle)

        # base_model: untrained floor (zero training cost).
        base, btok = _load_base(base_model)
        base_metrics = evaluate_distill_parametric(
            base, btok, corpus.good_probes, corpus.poison_probes
        )
        base_metrics.update({"train_wall_s": 0.0, "trainable_params": 0, "n_train": 0})
        runs.append(_record("base_model", seed, config, base_metrics))
        _free(base)

        # retrieval reference: same instruments over the stores (no model).
        retr_surv = evaluate_distill_retrieval(
            surv_store, corpus.good_probes, corpus.poison_probes
        )
        retr_surv.update(
            {"train_wall_s": 0.0, "trainable_params": 0, "n_train": len(survivors)}
        )
        runs.append(_record("retrieval", seed, config, retr_surv))

        runs.append(
            _record(
                "distill_survivor",
                seed,
                config,
                _distill_and_eval(survivors, corpus, base_model, config, seed),
            )
        )
        runs.append(
            _record(
                "distill_raw",
                seed,
                config,
                _distill_and_eval(raw, corpus, base_model, config, seed),
            )
        )

        if with_judge:
            # The judge arm is the opt-in, sampled stretch arm; never let it
            # take the deterministic core arms down with it.
            try:
                judged, judge_extra = A.judge_set(
                    corpus, seed, judge_model, cycles, per_cycle
                )
                jm = _distill_and_eval(judged, corpus, base_model, config, seed)
                # The judge counters (incl. judge_culls) self-document an empty
                # set: a baseline judge has no energy floor, so culls accumulate.
                jm["judge_survivors"] = len(judged)
                jm.update({f"judge_{k}": v for k, v in judge_extra.items()})
            except Exception as exc:  # noqa: BLE001
                jm = _empty_metrics(f"judge arm failed: {type(exc).__name__}: {exc}")
            runs.append(
                _record("distill_judge", seed, {**config, "judge_model": judge_model}, jm)
            )

        print(
            f"seed {seed} done | survivor n={len(survivors)} "
            f"(poison {A.poison_count(survivors)}) raw n={len(raw)} "
            f"(poison {A.poison_count(raw)})"
        )
    return runs
