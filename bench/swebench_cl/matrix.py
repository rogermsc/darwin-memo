"""Drive the full (arm, sequence, seed) matrix as separate processes.

The pre-registered matrix is five arms over two sequences at three
seeds: thirty runs, roughly six hundred real docker evaluations. Two
properties matter more than speed at that length.

*Resume.* Each combination writes its own result file and is skipped
when that file already exists, so an interrupted matrix continues where
it stopped. ``run_sequence`` accumulates its records in memory and
writes once at the end, so a killed run loses that combination and
nothing else; the granularity of loss is one sequence, not the matrix.

*Isolation.* Each combination is a subprocess. A crash, an endpoint
that stops answering, or a docker daemon that dies takes one cell down
and the matrix keeps going, reporting the failures together at the end
rather than surfacing the first one and discarding the other twenty-nine
hours.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from .arms import ARMS
from .dataset import PILOT_SEQUENCES

DEFAULT_SEEDS = (0, 1, 2)


def cell_path(out_dir: Path, arm: str, sequence: str, seed: int) -> Path:
    """Where one combination's records live.

    The arm is in the name because every axis of the matrix has to be
    recoverable from the filename alone: a resume that collided two
    arms on one path would silently skip work it never did.
    """
    return out_dir / f"{arm}-{sequence}-seed{seed}.json"


def cells(
    arms: tuple[str, ...],
    sequences: tuple[str, ...],
    seeds: tuple[int, ...],
) -> list[tuple[str, str, int]]:
    """Every combination, in a fixed order so progress reads sensibly."""
    return [(a, q, s) for q in sequences for a in arms for s in seeds]


def run_cmd(args: argparse.Namespace, arm: str, sequence: str, seed: int) -> list[str]:
    """The single-cell command line, mirroring ``run.py``'s flags."""
    cmd = [
        sys.executable,
        "-m",
        "bench.swebench_cl.run",
        "run",
        "--manifest",
        str(args.manifest),
        "--dataset",
        str(args.dataset),
        "--sequence",
        sequence,
        "--arm",
        arm,
        "--seed",
        str(seed),
        "--executor",
        args.executor,
        "--base-url",
        args.base_url,
        "--model",
        args.model,
        "--max-tokens",
        str(args.max_tokens),
        "--code-context-chars",
        str(args.code_context_chars),
        "--code-max-files",
        str(args.code_max_files),
        "--timeout",
        str(args.timeout),
        "--out",
        str(cell_path(args.out_dir, arm, sequence, seed)),
    ]
    if args.executor == "docker":
        # Committed evidence binds itself: each cell refreshes its entry
        # in the sibling manifest as it lands, so an interrupted matrix
        # leaves every finished cell already validatable rather than
        # waiting on a final pass that may never run. run.py refuses the
        # flag for stub executors, so plumbing runs stay unbound.
        cmd.append("--update-manifest")
    if args.api_key_env:
        cmd += ["--api-key-env", args.api_key_env]
    if args.max_tasks is not None:
        cmd += ["--max-tasks", str(args.max_tasks)]
    if args.seed_poison:
        cmd.append("--seed-poison")
    return cmd


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m bench.swebench_cl.matrix",
        description="run the full (arm, sequence, seed) matrix, resumably",
    )
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, default=Path("bench/results/swebench_cl"))
    p.add_argument("--arms", nargs="+", default=sorted(ARMS))
    p.add_argument("--sequences", nargs="+", default=list(PILOT_SEQUENCES))
    p.add_argument("--seeds", nargs="+", type=int, default=list(DEFAULT_SEEDS))
    p.add_argument("--executor", choices=["stub", "docker"], default="docker")
    p.add_argument("--base-url", default="https://api.openai.com/v1")
    p.add_argument("--model", default="gpt-4.1")
    p.add_argument("--api-key-env", default="")
    p.add_argument("--max-tokens", type=int, default=4096)
    # Non-zero by default and deliberately so: at 0 the model never sees
    # the repository and resolves ~0 on every arm, which is a flat matrix
    # that costs the same wall-clock to produce as a real one.
    #
    # The size is set by measured retrieval recall, not by taste. BM25
    # puts the file the gold patch edits in front of the model on 37% of
    # the pytest sequence at 60k/5 files, 74% at 300k/10, and 89% at
    # 600k/20. Below that the arms are mostly being scored on which
    # tasks BM25 happened to serve, since a file the model never sees is
    # a task no arm can solve. The retrieval query is issue-only and
    # identical across arms, so this sets how many tasks are answerable
    # at all, never which arm answers them.
    p.add_argument("--code-context-chars", type=int, default=300000)
    p.add_argument("--code-max-files", type=int, default=10)
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--max-tasks", type=int, default=None)
    p.add_argument("--seed-poison", action="store_true")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would run (and what resume would skip) and stop",
    )
    args = p.parse_args(argv)

    if args.code_context_chars <= 0 and not args.dry_run:
        print(
            "refusing --code-context-chars 0: the blind configuration "
            "resolves ~0 on every arm, so the matrix would cost its full "
            "wall-clock and produce no curve. Pass --dry-run to inspect.",
            file=sys.stderr,
        )
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    plan = cells(tuple(args.arms), tuple(args.sequences), tuple(args.seeds))
    todo = [c for c in plan if not cell_path(args.out_dir, *c).exists()]
    done = len(plan) - len(todo)
    print(f"matrix: {len(plan)} cells, {done} already written, {len(todo)} to run")

    if args.dry_run:
        for arm, sequence, seed in plan:
            path = cell_path(args.out_dir, arm, sequence, seed)
            print(f"  {'skip' if path.exists() else 'run '}  {path}")
        return 0

    failures: list[tuple[str, str, int, int]] = []
    started = time.monotonic()
    for i, (arm, sequence, seed) in enumerate(todo, start=1):
        elapsed = time.monotonic() - started
        print(
            f"[{i}/{len(todo)}] {arm} {sequence} seed{seed} "
            f"(elapsed {elapsed / 3600:.1f}h)",
            flush=True,
        )
        proc = subprocess.run(run_cmd(args, arm, sequence, seed), check=False)
        if proc.returncode != 0:
            failures.append((arm, sequence, seed, proc.returncode))
            print(f"  FAILED rc={proc.returncode}, continuing", file=sys.stderr)

    total = (time.monotonic() - started) / 3600
    print(f"matrix finished in {total:.1f}h, {len(failures)} failed")
    for arm, sequence, seed, rc in failures:
        print(f"  {arm} {sequence} seed{seed} rc={rc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
