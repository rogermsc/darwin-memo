"""SWE-Bench-CL pilot CLI.

Pin the manifest (committed once, validated thereafter):

    python -m bench.swebench_cl.run pin \\
        --dataset /path/to/SWE-Bench-CL-Curriculum.json \\
        --out bench/swebench_cl/manifests/pilot.json

Run one arm over one pinned sequence:

    python -m bench.swebench_cl.run run \\
        --manifest bench/swebench_cl/manifests/pilot.json \\
        --dataset /path/to/SWE-Bench-CL-Curriculum.json \\
        --sequence pytest-dev_pytest_sequence \\
        --arm memory_on --executor stub --max-tasks 1 \\
        --base-url http://localhost:11434/v1 --model llama3.2 \\
        --out bench/results/swebench_cl_smoke.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from bench.manifest import update_manifest

from .arms import ARMS
from .dataset import (
    PILOT_SEQUENCES,
    build_manifest,
    load_dataset,
    load_manifest,
    sequence_tasks,
)
from .executor import DISK_FLOOR_GB, DockerExecutor, StubExecutor
from .model import DEFAULT_BASE_URL, EndpointConfig
from .runner import MAX_PROMPT_CHARS, run_sequence


def _cmd_pin(args: argparse.Namespace) -> int:
    dataset = load_dataset(args.dataset)
    manifest = build_manifest(dataset, tuple(args.sequences))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n")
    total = sum(s["num_tasks"] for s in manifest["sequences"])
    print(
        f"pinned {len(manifest['sequences'])} sequences ({total} tasks) "
        f"from {manifest['dataset']['repo']}@{manifest['dataset']['commit'][:10]} "
        f"-> {args.out}"
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    if args.update_manifest and args.executor != "docker":
        print(
            f"refusing --update-manifest with --executor {args.executor}: "
            "committed evidence requires the docker executor (eval.mode == "
            '"docker"); drop --update-manifest for plumbing runs',
            file=sys.stderr,
        )
        return 2
    manifest = load_manifest(args.manifest)
    dataset = load_dataset(args.dataset)
    tasks = sequence_tasks(manifest, dataset, args.sequence)
    endpoint = EndpointConfig(
        base_url=args.base_url,
        model=args.model,
        api_key=os.environ.get(args.api_key_env, "") if args.api_key_env else "",
        max_tokens=args.max_tokens,
        timeout=args.timeout,
    )
    executor: StubExecutor | DockerExecutor
    if args.executor == "docker":
        executor = DockerExecutor(floor_gb=args.disk_floor_gb)
    else:
        executor = StubExecutor()
    runs = run_sequence(
        tasks,
        sequence_id=args.sequence,
        arm_name=args.arm,
        endpoint=endpoint,
        executor=executor,
        seed=args.seed,
        k=args.k,
        max_tasks=args.max_tasks,
        max_prompt_chars=args.max_prompt_chars,
        code_context_chars=args.code_context_chars,
        code_cache_dir=args.code_cache_dir,
        code_max_files=args.code_max_files,
        seed_poison=args.seed_poison,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"runs": runs}, indent=2))
    resolved = sum(1 for r in runs if r["metrics"]["resolved"])
    print(
        f"wrote {len(runs)} runs to {args.out} "
        f"(arm={args.arm}, executor={executor.mode}, resolved={resolved})"
    )
    if args.update_manifest:
        command = (
            f"python -m bench.swebench_cl.run run --manifest {args.manifest} "
            f"--dataset <pinned> --sequence {args.sequence} --arm {args.arm} "
            f"--executor {args.executor} --seed {args.seed} --out {args.out} "
            "--update-manifest"
        )
        manifest_path = update_manifest(args.out, runs, command)
        print(f"updated {manifest_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pin = sub.add_parser("pin", help="pin sequences into a committed manifest")
    pin.add_argument("--dataset", type=Path, required=True)
    pin.add_argument("--sequences", nargs="+", default=list(PILOT_SEQUENCES))
    pin.add_argument(
        "--out", type=Path, default=Path("bench/swebench_cl/manifests/pilot.json")
    )
    pin.set_defaults(fn=_cmd_pin)

    run = sub.add_parser("run", help="run one arm over one pinned sequence")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--sequence", required=True)
    run.add_argument("--arm", choices=sorted(ARMS), required=True)
    run.add_argument("--executor", choices=["stub", "docker"], default="stub")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--k", type=int, default=3)
    run.add_argument("--max-tasks", type=int, default=None)
    run.add_argument("--max-prompt-chars", type=int, default=MAX_PROMPT_CHARS)
    run.add_argument(
        "--code-context-chars",
        type=int,
        default=0,
        help="BM25-retrieved source-file context budget (chars); 0 = blind "
        "(problem statement only, the original pilot setting)",
    )
    run.add_argument("--code-max-files", type=int, default=5)
    run.add_argument(
        "--code-cache-dir",
        type=Path,
        default=None,
        help="where to cache fetched repo trees (default ./.swebench-repos)",
    )
    run.add_argument("--base-url", default=DEFAULT_BASE_URL)
    run.add_argument("--model", default="llama3.2")
    run.add_argument(
        "--api-key-env",
        default="",
        help="environment variable holding the endpoint API key (frontier runs)",
    )
    run.add_argument("--max-tokens", type=int, default=1024)
    run.add_argument("--timeout", type=float, default=600.0)
    run.add_argument("--disk-floor-gb", type=float, default=DISK_FLOOR_GB)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--update-manifest", action="store_true")
    run.add_argument("--seed-poison", action="store_true",
                    help="seed the memory store with poison lessons before evaluation")
    run.set_defaults(fn=_cmd_run)

    args = parser.parse_args(argv)
    result: int = args.fn(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
