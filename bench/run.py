"""Benchmark CLI.

python -m bench.run --suite headline --seeds 0:10 --out bench/results/headline.json
python -m bench.run --suite ablation --seeds 0:5  --out bench/results/ablation.json
python -m bench.run --suite scaling [--full]      --out bench/results/scaling.json
python -m bench.run --suite smoke                 --out bench/results/smoke.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import run_one
from .suites import (
    RunSpec,
    ablation_suite,
    headline_suite,
    scaling_suite,
    smoke_suite,
)


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
        choices=["headline", "ablation", "scaling", "smoke", "llm"],
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
    args = parser.parse_args(argv)

    if args.suite == "llm":
        from darwin_memo import ollama_available

        if not ollama_available():
            print(
                "error: --suite llm needs a running Ollama server "
                "(https://ollama.com). Results are sampled, not "
                "deterministic; this suite never runs in CI.",
            )
            return 1
        runs = _execute(
            [
                RunSpec(
                    suite="llm",
                    arm="survival_llm",
                    seed=seed,
                    cycles=12,
                    files_per_cycle=8,
                    overrides={"llm_model": args.model},
                    label=f"model={args.model}",
                )
                for seed in _parse_seeds(args.seeds)
            ]
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"runs": runs}, indent=2))
        print(f"wrote {len(runs)} runs to {args.out}")
        return 0

    if args.suite == "scaling":
        runs: list[dict[str, object]] = list(scaling_suite(full=args.full))
    elif args.suite == "headline":
        runs = _execute(headline_suite(_parse_seeds(args.seeds)))
    elif args.suite == "ablation":
        runs = _execute(ablation_suite(_parse_seeds(args.seeds)))
    else:
        runs = _execute(smoke_suite())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"runs": runs}, indent=2))
    print(f"wrote {len(runs)} runs to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
