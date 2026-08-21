"""Benchmark CLI.

python -m bench.run --suite headline --seeds 0:10 --out bench/results/headline.json
python -m bench.run --suite noisy    --seeds 0:30 --out bench/results/noisy.json
python -m bench.run --suite ablation --seeds 0:5  --out bench/results/ablation.json
python -m bench.run --suite testsuite --seeds 0:10 \
    --out bench/results/testsuite.json
python -m bench.run --suite testsuite_noisy --seeds 0:30 \
    --out bench/results/testsuite_noisy.json
python -m bench.run --suite bandit   --seeds 0:10 --out bench/results/bandit.json
python -m bench.run --suite adversary --seeds 0:10 \
    --out bench/results/adversary.json
python -m bench.run --suite memsec --seeds 0:10 \
    --out bench/results/memsec.json
python -m bench.run --suite judge --seeds 0:5 --judge-models llama3.2:3b \
    --out bench/results/judge-llama.json
python -m bench.run --suite judge --seeds 0:5 --judge-models qwen3:4b \
    --out bench/results/judge-qwen.json
python -m bench.run --suite llm --seeds 0:5 --model llama3.2:3b \
    --out bench/results/llm-llama.json
python -m bench.run --suite llm --seeds 0:5 --model qwen3:4b \
    --out bench/results/llm-qwen.json
python -m bench.run --suite scaling [--full]      --out bench/results/scaling.json
python -m bench.run --suite smoke                 --out bench/results/smoke.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .manifest import update_manifest
from .runner import run_one
from .suites import (
    JUDGE_MODELS,
    RunSpec,
    ablation_suite,
    adversary_suite,
    bandit_suite,
    headline_suite,
    judge_suite,
    llm_suite,
    memsec_suite,
    neighbours_suite,
    noisy_suite,
    persistence_suite,
    salience_suite,
    scaling_suite,
    smoke_suite,
    wef_suite,
    withholding_selective_suite,
    withholding_suite,
    withholding_testsuite_suite,
)
from .testsuite_suites import testsuite_noisy_suite, testsuite_suite


def _parse_seeds(text: str) -> list[int]:
    if ":" in text:
        lo, hi = text.split(":")
        return list(range(int(lo), int(hi)))
    return [int(s) for s in text.split(",")]


def _execute(specs: list[RunSpec]) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    for i, spec in enumerate(specs):
        result = run_one(
            arm=spec.arm,
            seed=spec.seed,
            cycles=spec.cycles,
            files_per_cycle=spec.files_per_cycle,
            overrides=spec.overrides,
            suite=spec.suite,
        )
        if spec.label:
            result["label"] = spec.label
        runs.append(result)
        tag = f"{spec.arm}" + (f" [{spec.label}]" if spec.label else "")
        print(f"[{i + 1}/{len(specs)}] {tag} seed={spec.seed} done")
    return runs


def _spec_stem(spec: RunSpec) -> str:
    """Filesystem-safe name for one run's checkpoint and transcript.

    The arm is part of the name. It did not need to be while the llm
    suite was the only caller, because that suite has one arm; a
    multi-arm suite without it has every arm writing the same stem, so
    the transcripts overwrite each other and resume never hits.
    """
    return re.sub(r"[^A-Za-z0-9._-]+", "-", f"{spec.arm}-{spec.label}-seed{spec.seed}")


def _execute_llm(specs: list[RunSpec], out: Path) -> list[dict[str, object]]:
    """Like _execute, but checkpointed: each run lands on disk as it
    finishes, and a rerun resumes from whatever already completed. An
    LLM run is hours of model time; an interruption at seed 4 must not
    cost seeds 0 through 3. Delete ``<out dir>/runs/`` to force a
    fresh grid."""
    ckpt_dir = out.parent / "runs"
    transcript_dir = out.parent / "transcripts"
    runs: list[dict[str, object]] = []
    for i, spec in enumerate(specs):
        stem = _spec_stem(spec)
        tag = f"{spec.arm}" + (f" [{spec.label}]" if spec.label else "")
        ckpt = ckpt_dir / f"{stem}.json"
        if ckpt.exists():
            result = json.loads(ckpt.read_text())
            if (
                result.get("arm") == spec.arm
                and result.get("seed") == spec.seed
                and result.get("label", "") == spec.label
            ):
                runs.append(result)
                print(f"[{i + 1}/{len(specs)}] {tag} seed={spec.seed} resumed")
                continue
        result = run_one(
            arm=spec.arm,
            seed=spec.seed,
            cycles=spec.cycles,
            files_per_cycle=spec.files_per_cycle,
            overrides=spec.overrides,
            suite=spec.suite,
            transcript_path=transcript_dir / f"{stem}.jsonl",
        )
        if spec.label:
            result["label"] = spec.label
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        ckpt.write_text(json.dumps(result, indent=2))
        runs.append(result)
        wall = result["metrics"]["wall_time_s"]
        print(f"[{i + 1}/{len(specs)}] {tag} seed={spec.seed} done ({wall:.0f}s)")
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=[
            "headline",
            "noisy",
            "ablation",
            "testsuite",
            "testsuite_noisy",
            "scaling",
            "smoke",
            "salience",
            "neighbours",
            "llm",
            "bandit",
            "adversary",
            "persistence",
            "withholding",
            "withholding_selective",
            "withholding_testsuite",
            "memsec",
            "wef",
            "judge",
            "distill",
            "distill_merge",
            "distill_noisy",
            "distill_rule",
        ],
        required=True,
    )
    parser.add_argument("--seeds", default="0:10", help="a:b range or comma list")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--full", action="store_true", help="include the O(N^2) scaling cells"
    )
    parser.add_argument(
        "--model",
        default="llama3.2",
        help="Ollama model(s) for --suite llm, comma-separated "
        "(requires a running server)",
    )
    parser.add_argument(
        "--judge-models",
        default=",".join(JUDGE_MODELS),
        help="comma list of Ollama judge models for --suite judge",
    )
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        help="record suite, seeds, config hash, and the exact command "
        "in MANIFEST.json next to --out (committed results only)",
    )
    parser.add_argument(
        "--base-model",
        default="Qwen/Qwen2.5-0.5B-Instruct",
        help="HF base model for --suite distill",
    )
    parser.add_argument(
        "--epochs", type=int, default=3, help="LoRA epochs for --suite distill"
    )
    parser.add_argument(
        "--good", type=int, default=30, help="good facts in the distill QA corpus"
    )
    parser.add_argument(
        "--poison", type=int, default=6, help="poison entries in the distill QA corpus"
    )
    parser.add_argument(
        "--with-judge",
        action="store_true",
        help="include the distill_judge arm (requires Ollama)",
    )
    parser.add_argument(
        "--parts", type=int, default=2, help="disjoint corpora for distill_merge"
    )
    parser.add_argument(
        "--flake-rate", type=float, default=0.2, help="flip-noise rate (distill_noisy)"
    )
    parser.add_argument(
        "--noise-model", default="flip", help="noise model for distill_noisy"
    )
    args = parser.parse_args(argv)

    if args.suite in ("distill", "distill_merge", "distill_noisy", "distill_rule"):
        try:
            import torch  # noqa: F401
        except ImportError:
            print(
                "error: --suite distill needs torch/transformers/peft/datasets. "
                "Install them and rerun; this suite is opt-in and never in CI."
            )
            return 1
        if args.with_judge:
            from darwin_memo import ollama_available

            if not ollama_available():
                print("error: --with-judge needs a running Ollama server")
                return 1

    if args.suite in ("llm", "judge", "wef"):
        # The preflight is a CLI concern; the suites live with the others.
        from darwin_memo import ollama_available

        if not ollama_available():
            print(
                f"error: --suite {args.suite} needs a running Ollama server "
                "(https://ollama.com). Results are sampled, not "
                "deterministic; this suite never runs in CI.",
            )
            return 1

    if args.suite == "scaling":
        runs: list[dict[str, object]] = list(scaling_suite(full=args.full))
    elif args.suite == "headline":
        runs = _execute(headline_suite(_parse_seeds(args.seeds)))
    elif args.suite == "noisy":
        runs = _execute(noisy_suite(_parse_seeds(args.seeds)))
    elif args.suite == "ablation":
        runs = _execute(ablation_suite(_parse_seeds(args.seeds)))
    elif args.suite == "testsuite":
        runs = _execute(testsuite_suite(_parse_seeds(args.seeds)))
    elif args.suite == "testsuite_noisy":
        runs = _execute(testsuite_noisy_suite(_parse_seeds(args.seeds)))
    elif args.suite == "llm":
        models = [m.strip() for m in args.model.split(",") if m.strip()]
        runs = _execute_llm(llm_suite(_parse_seeds(args.seeds), models), args.out)
    elif args.suite == "wef":
        # Checkpointed like the llm suite, and for the same reason: the
        # grid is hours of model time and an interrupt at run 20 must
        # not cost the first nineteen.
        models = [m.strip() for m in args.model.split(",") if m.strip()]
        runs = _execute_llm(wef_suite(_parse_seeds(args.seeds), models), args.out)
    elif args.suite == "memsec":
        runs = _execute(memsec_suite(_parse_seeds(args.seeds)))
    elif args.suite == "adversary":
        runs = _execute(adversary_suite(_parse_seeds(args.seeds)))
    elif args.suite == "persistence":
        runs = _execute(persistence_suite(_parse_seeds(args.seeds)))
    elif args.suite == "withholding":
        runs = _execute(withholding_suite(_parse_seeds(args.seeds)))
    elif args.suite == "withholding_selective":
        runs = _execute(withholding_selective_suite(_parse_seeds(args.seeds)))
    elif args.suite == "withholding_testsuite":
        runs = _execute(withholding_testsuite_suite(_parse_seeds(args.seeds)))
    elif args.suite == "bandit":
        runs = _execute(bandit_suite(_parse_seeds(args.seeds)))
    elif args.suite == "salience":
        runs = _execute(salience_suite(_parse_seeds(args.seeds)))
    elif args.suite == "neighbours":
        runs = _execute(neighbours_suite(_parse_seeds(args.seeds)))
    elif args.suite == "judge":
        runs = _execute(
            judge_suite(_parse_seeds(args.seeds), args.judge_models.split(","))
        )
    elif args.suite == "distill":
        from .distill.run import distill_run

        runs = distill_run(
            _parse_seeds(args.seeds),
            base_model=args.base_model,
            epochs=args.epochs,
            n_good=args.good,
            n_poison=args.poison,
            with_judge=args.with_judge,
            judge_model=args.judge_models.split(",")[0],
        )
    elif args.suite == "distill_merge":
        from .distill.merge_run import merge_run

        runs = merge_run(
            _parse_seeds(args.seeds),
            base_model=args.base_model,
            epochs=args.epochs,
            n_good=args.good,
            n_poison=args.poison,
            parts=args.parts,
        )
    elif args.suite == "distill_noisy":
        from .distill.noisy_run import noisy_run

        runs = noisy_run(
            _parse_seeds(args.seeds),
            base_model=args.base_model,
            epochs=args.epochs,
            n_good=args.good,
            n_poison=args.poison,
            flake_rate=args.flake_rate,
            noise_model=args.noise_model,
        )
    elif args.suite == "distill_rule":
        from .distill.rule_run import rule_run

        runs = rule_run(
            _parse_seeds(args.seeds),
            base_model=args.base_model,
            epochs=args.epochs,
            flake_rate=args.flake_rate,
        )
    else:
        runs = _execute(smoke_suite())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"runs": runs}, indent=2))
    print(f"wrote {len(runs)} runs to {args.out}")

    if args.update_manifest:
        if args.suite == "scaling":
            # Timing rows have no seeds or config grid to bind; the
            # scaling table stays machine-local by design.
            print("error: --update-manifest does not apply to --suite scaling")
            return 1
        model_part = f"--model {args.model} " if args.suite in ("llm", "wef") else ""
        if args.suite in ("distill", "distill_merge", "distill_noisy", "distill_rule"):
            model_part = (
                f"--base-model {args.base_model} --epochs {args.epochs} "
                f"--good {args.good} --poison {args.poison} "
                + (f"--parts {args.parts} " if args.suite == "distill_merge" else "")
                + (
                    f"--flake-rate {args.flake_rate} "
                    if args.suite in ("distill_noisy", "distill_rule")
                    else ""
                )
                + ("--with-judge " if args.with_judge else "")
            )
        command = (
            f"python -m bench.run --suite {args.suite} --seeds {args.seeds} "
            f"{model_part}--out {args.out} --update-manifest"
        )
        extra = None
        if args.suite in ("llm", "wef"):
            # Tags are mutable; the manifest pins the exact weights.
            from darwin_memo.llm import ollama_model_digest

            extra = {
                "models": {m: ollama_model_digest(m) for m in models},
                "sampled": "model output; rerunning reproduces the grid, "
                "not the numbers",
            }
        elif args.suite in (
            "distill",
            "distill_merge",
            "distill_noisy",
            "distill_rule",
        ):
            extra = {
                "sampled": "LoRA training + (with --with-judge) sampled judge "
                "settlement; rerunning reproduces the design, not the exact numbers"
            }
        manifest_path = update_manifest(args.out, runs, command, extra=extra)
        print(f"updated {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
