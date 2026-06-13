"""Benchmark CLI.

python -m bench.run --suite headline --seeds 0:10 --out bench/results/headline.json
python -m bench.run --suite noisy    --seeds 0:30 --out bench/results/noisy.json
python -m bench.run --suite ablation --seeds 0:5  --out bench/results/ablation.json
python -m bench.run --suite testsuite --seeds 0:10 \
    --out bench/results/testsuite.json
python -m bench.run --suite testsuite_noisy --seeds 0:30 \
    --out bench/results/testsuite_noisy.json
python -m bench.run --suite bandit   --seeds 0:10 --out bench/results/bandit.json
python -m bench.run --suite judge --seeds 0:5 --judge-models llama3.2:3b \
    --out bench/results/judge-llama.json
python -m bench.run --suite judge --seeds 0:5 --judge-models qwen3:4b \
    --out bench/results/judge-qwen.json
python -m bench.run --suite scaling [--full]      --out bench/results/scaling.json
python -m bench.run --suite smoke                 --out bench/results/smoke.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .manifest import update_manifest
from .runner import run_one
from .suites import (
    JUDGE_MODELS,
    RunSpec,
    ablation_suite,
    bandit_suite,
    headline_suite,
    judge_suite,
    llm_suite,
    noisy_suite,
    scaling_suite,
    smoke_suite,
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
            "llm",
            "bandit",
            "judge",
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
        help="Ollama model for --suite llm (requires a running server)",
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
    args = parser.parse_args(argv)

    if args.suite in ("llm", "judge"):
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
        runs = _execute(llm_suite(_parse_seeds(args.seeds), args.model))
    elif args.suite == "bandit":
        runs = _execute(bandit_suite(_parse_seeds(args.seeds)))
    elif args.suite == "judge":
        runs = _execute(
            judge_suite(_parse_seeds(args.seeds), args.judge_models.split(","))
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
        command = (
            f"python -m bench.run --suite {args.suite} --seeds {args.seeds} "
            f"--out {args.out} --update-manifest"
        )
        manifest_path = update_manifest(args.out, runs, command)
        print(f"updated {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
