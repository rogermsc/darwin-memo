"""Task execution: the official SWE-Bench images, behind a disk guard.

Two executors share one report shape:

- ``DockerExecutor`` is the real path. It evaluates one prediction with
  the official SWE-Bench harness (``pip install swebench``), pulling
  the instance's published evaluation image from Docker Hub. Those
  images are x86_64-only (no arm64 variants are published for the
  pilot instances; verified against the registry) and roughly 1 GB
  compressed / 2.5-3 GB on disk EACH, so before anything is pulled the
  guard fetches the image's compressed size from the registry, applies
  an uncompressed-size factor, and refuses to start if free disk would
  drop below the floor. The guard fails the run loudly; it never
  trims, never retries, never pulls "just a bit".
- ``StubExecutor`` is the documented plumbing stand-in for machines
  that cannot run the real path (this pilot was built on an 8 GB-free
  aarch64 Mac, where one image pull would cross the floor). It applies
  no patch and runs no tests; it deterministically reports the paths
  the runner must handle: empty patch, unparseable patch, plausible
  patch (applied, unresolved), and gold patch (resolved). Every report
  carries ``mode="stub"`` so a stubbed number can never be mistaken
  for an evaluated one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .dataset import TaskRecord

DISK_FLOOR_GB = 4.0
# Compressed-to-on-disk growth observed on SWE-Bench eval images
# (conda envs compress well); deliberately conservative.
UNCOMPRESSED_FACTOR = 2.8
SWEBENCH_NAMESPACE = "swebench"
SWEBENCH_DATASET = "princeton-nlp/SWE-bench_Verified"


class DiskGuardError(RuntimeError):
    """Pulling the image would drop free disk below the floor."""


@dataclass
class EvalReport:
    """What actually happened when one patch met one task environment."""

    instance_id: str
    mode: str  # "docker" | "stub"
    env_ready: bool = False  # the task environment came up
    empty_patch: bool = False
    patch_applied: bool = False
    eval_executed: bool = False
    resolved: bool = False
    f2p_passed: int = 0
    f2p_total: int = 0
    p2p_passed: int = 0
    p2p_total: int = 0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def delta_from_eval(report: EvalReport) -> float:
    """The settlement measurement: test movement, never a grade.

    Fraction of fail-to-pass tests now passing, minus the fraction of
    pass-to-pass tests broken. Bounded in [-1, 1]; an empty patch or a
    failed apply leaves the base behavior and lands at exactly 0.
    """
    if not report.eval_executed:
        return 0.0
    gained = report.f2p_passed / report.f2p_total if report.f2p_total else 0.0
    broken = (
        (report.p2p_total - report.p2p_passed) / report.p2p_total
        if report.p2p_total
        else 0.0
    )
    return gained - broken


def image_for(instance_id: str, arch: str = "x86_64") -> str:
    """Official image name; Docker Hub maps ``__`` to ``_1776_``."""
    safe = instance_id.replace("__", "_1776_")
    return f"{SWEBENCH_NAMESPACE}/sweb.eval.{arch}.{safe}"


def hub_compressed_bytes(image: str, tag: str = "latest") -> int:
    """Compressed image size from the Docker Hub API. No pull, no auth."""
    url = f"https://hub.docker.com/v2/repositories/{image}/tags/{tag}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    size = payload.get("full_size")
    if not isinstance(size, int) or size <= 0:
        raise DiskGuardError(
            f"cannot size {image}:{tag} from Docker Hub; refusing to pull blind"
        )
    return size


def check_disk_guard(
    image: str,
    floor_gb: float = DISK_FLOOR_GB,
    image_size_fn: Callable[[str], int] = hub_compressed_bytes,
    free_bytes_fn: Callable[[], int] = lambda: shutil.disk_usage("/").free,
) -> None:
    """Refuse any pull that would leave less than ``floor_gb`` free."""
    compressed = image_size_fn(image)
    estimated = int(compressed * UNCOMPRESSED_FACTOR)
    free = free_bytes_fn()
    after = free - estimated
    if after < floor_gb * 1e9:
        raise DiskGuardError(
            f"refusing to pull {image}: {compressed / 1e9:.2f} GB compressed, "
            f"estimated {estimated / 1e9:.2f} GB on disk, {free / 1e9:.2f} GB "
            f"free now, {after / 1e9:.2f} GB after; the floor is "
            f"{floor_gb:.1f} GB. Run this on a machine with more disk, or "
            "use --executor stub for plumbing work."
        )


def _looks_like_diff(patch: str) -> bool:
    return patch.lstrip().startswith(("diff --git", "--- "))


class StubExecutor:
    """Deterministic stand-in: exercises every runner path, proves none.

    Reports are honest about what did not happen: ``env_ready`` is
    True (the stub stands in for a working environment), but a resolved
    verdict is only ever produced for the gold patch, where it is true
    by the dataset's own construction.
    """

    mode = "stub"

    def evaluate(self, task: TaskRecord, patch: str) -> EvalReport:
        report = EvalReport(
            instance_id=task.instance_id,
            mode=self.mode,
            env_ready=True,
            f2p_total=len(task.fail_to_pass),
            p2p_total=len(task.pass_to_pass),
        )
        if not patch.strip():
            report.empty_patch = True
            report.eval_executed = True
            report.p2p_passed = report.p2p_total
            report.notes = "stub: empty patch, base behavior assumed"
            return report
        if not _looks_like_diff(patch):
            report.eval_executed = True
            report.p2p_passed = report.p2p_total
            report.notes = "stub: patch did not parse as a unified diff"
            return report
        report.patch_applied = True
        report.eval_executed = True
        if patch.strip() == task.gold_patch.strip():
            report.resolved = True
            report.f2p_passed = report.f2p_total
            report.p2p_passed = report.p2p_total
            report.notes = "stub: gold patch, resolved by construction"
        else:
            report.p2p_passed = report.p2p_total
            report.notes = "stub: non-gold patch assumed unresolved; no tests ran"
        return report


@dataclass
class DockerExecutor:
    """The real path: official images, official harness, guarded pulls.

    Requires the ``swebench`` package in the running interpreter, a
    Docker daemon, and (on non-x86 hosts) emulation; the published
    instance images are x86_64-only, so an Apple Silicon machine runs
    them under Rosetta/qemu, slowly, and a CI-grade run wants a real
    linux/amd64 host. Evaluation is delegated to
    ``swebench.harness.run_evaluation`` so test-spec generation stays
    upstream's responsibility, not a re-implementation here.
    """

    floor_gb: float = DISK_FLOOR_GB
    run_id: str = "darwin-memo-pilot"
    workdir: Path | None = None
    image_size_fn: Callable[[str], int] = hub_compressed_bytes
    free_bytes_fn: Callable[[], int] = field(
        default=lambda: shutil.disk_usage("/").free
    )
    runner_fn: Callable[[list[str], Path], subprocess.CompletedProcess[str]] | None = (
        None
    )

    mode = "docker"

    def evaluate(self, task: TaskRecord, patch: str) -> EvalReport:
        report = EvalReport(
            instance_id=task.instance_id,
            mode=self.mode,
            f2p_total=len(task.fail_to_pass),
            p2p_total=len(task.pass_to_pass),
        )
        if not patch.strip():
            # The official harness rejects empty predictions; the empty
            # patch settles at base behavior without ever needing the
            # image, so the guard and the pull are skipped entirely.
            report.empty_patch = True
            report.eval_executed = True
            report.p2p_passed = report.p2p_total
            report.notes = "docker: empty patch, evaluated as base behavior"
            return report
        check_disk_guard(
            image_for(task.instance_id),
            floor_gb=self.floor_gb,
            image_size_fn=self.image_size_fn,
            free_bytes_fn=self.free_bytes_fn,
        )
        workdir = self.workdir or Path(tempfile.mkdtemp(prefix="dm-swebench-"))
        workdir.mkdir(parents=True, exist_ok=True)
        predictions = workdir / "predictions.jsonl"
        predictions.write_text(
            json.dumps(
                {
                    "instance_id": task.instance_id,
                    "model_name_or_path": self.run_id,
                    "model_patch": patch,
                }
            )
            + "\n"
        )
        command = [
            sys.executable,
            "-m",
            "swebench.harness.run_evaluation",
            "--dataset_name",
            SWEBENCH_DATASET,
            "--predictions_path",
            str(predictions),
            "--instance_ids",
            task.instance_id,
            "--namespace",
            SWEBENCH_NAMESPACE,
            "--run_id",
            self.run_id,
            "--max_workers",
            "1",
            "--cache_level",
            "none",
        ]
        run = self.runner_fn or _run_subprocess
        completed = run(command, workdir)
        if completed.returncode != 0:
            raise RuntimeError(
                f"swebench harness failed for {task.instance_id} "
                f"(is `pip install swebench` done, is Docker up?):\n"
                f"{completed.stderr[-2000:]}"
            )
        report.env_ready = True
        report.eval_executed = True
        return _merge_harness_report(report, workdir, self.run_id)


def _run_subprocess(
    command: list[str], workdir: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=workdir, capture_output=True, text=True, check=False
    )


def _merge_harness_report(report: EvalReport, workdir: Path, run_id: str) -> EvalReport:
    """Read the official harness's reports into our shape.

    The per-instance ``report.json`` (under ``logs/run_evaluation/``)
    carries real per-test outcomes and is preferred. The harness's
    grader omits ``tests_status`` entirely when no tests ran (apply
    failed, repo reset failed, tests errored or timed out); that is a
    no-measurement outcome, so it settles at base behavior rather than
    inventing damage no test measured. When ``tests_status`` is
    present, its success/failure lists partition the spec's test lists,
    so the totals are read from it directly. The run summary
    (``{run_id}.*.json``) only names resolved/error ids; on that
    fallback an unresolved run likewise settles at base behavior. A
    zero-exit harness that left neither file behind is an
    infrastructure failure and raises instead of scoring anything.
    """
    instance = report.instance_id
    for path in sorted(workdir.glob("**/report.json")):
        entry = json.loads(path.read_text()).get(instance)
        if not isinstance(entry, dict):
            continue
        report.patch_applied = bool(entry.get("patch_successfully_applied"))
        report.resolved = bool(entry.get("resolved"))
        tests = entry.get("tests_status")
        if isinstance(tests, dict):
            f2p = tests.get("FAIL_TO_PASS", {})
            p2p = tests.get("PASS_TO_PASS", {})
            report.f2p_passed = len(f2p.get("success", []))
            report.f2p_total = report.f2p_passed + len(f2p.get("failure", []))
            report.p2p_passed = len(p2p.get("success", []))
            report.p2p_total = report.p2p_passed + len(p2p.get("failure", []))
            report.notes = f"docker: per-instance report {path.relative_to(workdir)}"
        else:
            report.p2p_passed = report.p2p_total
            report.notes = (
                f"docker: per-instance report {path.relative_to(workdir)} "
                "carries no tests_status (no tests ran); settled at base behavior"
            )
        return report
    candidates = sorted(workdir.glob(f"{run_id}.*.json"))
    if not candidates:
        raise RuntimeError(
            f"swebench harness exited 0 for {instance} but left neither a "
            f"per-instance report.json nor a {run_id}.*.json summary under "
            f"{workdir}; refusing to score a run nothing measured"
        )
    payload = json.loads(candidates[0].read_text())
    report.resolved = instance in payload.get("resolved_ids", [])
    report.patch_applied = instance not in payload.get("error_ids", []) and not any(
        instance in str(name) for name in payload.get("unstopped_containers", [])
    )
    if report.resolved:
        report.f2p_passed = report.f2p_total
    report.p2p_passed = report.p2p_total
    report.notes = (
        f"docker: summary report {candidates[0].name}; per-test counts "
        "unavailable, unresolved settles at base behavior"
    )
    return report
