"""Repository-local pytest onboarding and identity-bound CI settlement."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .ci import EXIT_ABSTAINED, InfraFailure, diff_runs, parse_junit
from .ledger import Ledger
from .store import MemoryStore, store_lock


def git(*args: str, cwd: Path | None = None) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=cwd, text=True, stderr=subprocess.PIPE
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise ValueError(exc.stderr.strip() or "Git operation failed") from exc


def commit(value: str) -> str:
    return git("rev-parse", "--verify", value + "^{commit}")


def evaluation_digest(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Evaluation must be a repository directory")
    files = sorted(
        p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    )
    if not files or any(p.is_symlink() for p in root.rglob("*")):
        raise ValueError("Evaluation must contain files and no symbolic links")
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def cmd_init(args: argparse.Namespace) -> int:
    root = Path.cwd()
    git("rev-parse", "--show-toplevel")
    if Path(git("rev-parse", "--show-toplevel")) != root:
        raise ValueError("Run init at the repository root")
    templates = Path(__file__).parent / "data" / "github-pytest"
    paths = {
        root / p.relative_to(templates): p.read_bytes()
        for p in templates.rglob("*")
        if p.is_file()
    }
    memory = root / ".darwin-memo/memory.json"
    paths[memory] = (json.dumps(MemoryStore().to_payload(), indent=2) + "\n").encode()
    if any(not p.resolve().is_relative_to(root) for p in paths):
        raise ValueError("Setup paths must stay inside the repository")
    conflicts = [
        str(p.relative_to(root)) for p in paths if p.exists() or p.is_symlink()
    ]
    if conflicts:
        raise ValueError("Refusing to overwrite: " + ", ".join(conflicts))
    for path, content in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
    print(json.dumps({"created": sorted(str(p.relative_to(root)) for p in paths)}))
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    root = Path(git("rev-parse", "--show-toplevel"))
    if root != Path.cwd():
        raise ValueError("Run task commands at the repository root")
    memory = Path(args.memory).resolve()
    with store_lock(memory):
        ledger = Ledger.load(memory, event_log=memory.with_suffix(".events.jsonl"))
        tickets = {t.id: t for t in ledger.pending()}
        ticket = tickets.get(args.ticket)
        if ticket is None:
            raise ValueError("Ticket is not pending; duplicate or unknown outcome")
        if args.task_op == "bind":
            if ticket.binding:
                raise ValueError("Ticket is already bound")
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repository):
                raise ValueError("Repository must be OWNER/REPOSITORY")
            evaluation = Path(args.evaluation)
            if (
                not evaluation.parts
                or evaluation.is_absolute()
                or ".." in evaluation.parts
            ):
                raise ValueError("Evaluation must be a repository-relative directory")
            base = commit(args.base)
            # Freeze bytes from git, not an uncommitted evaluation on disk.
            with tempfile.TemporaryDirectory(prefix="darwin-base-") as tmp:
                checkout = Path(tmp) / "base"
                git("worktree", "add", "--detach", str(checkout), base)
                try:
                    digest = evaluation_digest(checkout / evaluation)
                finally:
                    git("worktree", "remove", "--force", str(checkout))
            ticket.binding = {
                "repository": args.repository,
                "task": args.task,
                "base": base,
                "evaluation": str(evaluation),
                "evaluation_sha256": digest,
            }
            ledger.save(memory)
            print(json.dumps({"ticket": ticket.id, "binding": ticket.binding}))
            return 0
        binding = ticket.binding
        required = {"repository", "task", "base", "evaluation", "evaluation_sha256"}
        if (
            not isinstance(binding, dict)
            or not required.issubset(binding)
            or not all(isinstance(binding[k], str) and binding[k] for k in required)
        ):
            raise ValueError("Ticket has no valid task binding")
        if binding["repository"] != args.repository or binding["task"] != args.task:
            raise ValueError("Repository or task does not match the ticket binding")
        if args.timeout <= 0 or not math.isfinite(args.timeout):
            raise ValueError("Evaluation timeout must be finite and positive")
        head = commit(args.head)
        if head != commit("HEAD"):
            raise ValueError("Check out the exact head commit before evaluating")
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", binding["base"], head]
        ).returncode:
            raise ValueError("Head does not descend from the bound base")
        if not args.run:
            raise ValueError("A run identity is required")
        ci = os.environ.get("GITHUB_ACTIONS") == "true"
        if ci:
            expected_run = (
                os.environ.get("GITHUB_RUN_ID", "")
                + ":"
                + os.environ.get("GITHUB_RUN_ATTEMPT", "")
            )
            if (
                os.environ.get("GITHUB_REPOSITORY") != args.repository
                or args.run != expected_run
            ):
                raise ValueError("Run identity does not match the GitHub job")
        identity = {**binding, "commit": head, "run": args.run, "ticket": ticket.id}
        # One run may settle one task only, even when multiple tickets are pending.
        if ledger.has_settled_run(args.repository, args.run):
            raise ValueError("Run identity has already settled a task")
        out = Path(args.output).resolve()
        if out.exists():
            raise ValueError(
                "Output directory already exists; preserve the previous reports"
            )
        out.mkdir(parents=True)
        evaluation_changes = git(
            "diff", "--name-status", binding["base"], head, "--", binding["evaluation"]
        ).splitlines()
        evidence: dict[str, Any] = dict(identity)
        maps: dict[str, dict[str, bool | None]] = {}
        exits: dict[str, int] = {}
        with tempfile.TemporaryDirectory(prefix="darwin-evaluate-") as tmp:
            base_checkout = Path(tmp) / "base"
            target = Path(tmp) / "head"
            checkouts = []
            try:
                for revision, checkout in (
                    (binding["base"], base_checkout),
                    (head, target),
                ):
                    git("worktree", "add", "--detach", str(checkout), revision)
                    checkouts.append(checkout)
                frozen = base_checkout / binding["evaluation"]
                if evaluation_digest(frozen) != binding["evaluation_sha256"]:
                    raise ValueError("Evaluation does not match the ticket fingerprint")
                for name, checkout in (("base", base_checkout), ("head", target)):
                    fixed = checkout / ".darwin-fixed-evaluation"
                    if fixed.exists():
                        raise ValueError("Reserved evaluation directory already exists")
                    shutil.copytree(frozen, fixed)
                    report_path = out / f"{name}.xml"
                    env = {
                        **os.environ,
                        "PYTHONPATH": str(checkout),
                        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                        "PYTEST_ADDOPTS": "",
                    }
                    with (out / f"{name}.log").open("w") as log:
                        result = subprocess.run(
                            [
                                sys.executable,
                                "-m",
                                "pytest",
                                "-c",
                                "/dev/null",
                                "--rootdir=.",
                                "--import-mode=importlib",
                                f"--confcutdir={fixed}",
                                str(fixed.relative_to(checkout)),
                                f"--junitxml={report_path}",
                            ],
                            cwd=checkout,
                            env=env,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            timeout=args.timeout,
                        )
                    exits[name] = result.returncode
                    if result.returncode not in (0, 1):
                        raise InfraFailure(
                            f"{name} pytest exit {result.returncode}; "
                            f"see {out / (name + '.log')}"
                        )
                    maps[name] = parse_junit(report_path, name, errors_are_infra=True)
                    if all(value is None for value in maps[name].values()):
                        raise InfraFailure(f"{name} skipped every evaluation case")
                    evidence[name + "_xml_sha256"] = hashlib.sha256(
                        report_path.read_bytes()
                    ).hexdigest()
                transitions = diff_runs(maps["base"], maps["head"])
                if set(maps["base"]) != set(maps["head"]):
                    raise InfraFailure("Fixed evaluation collected different test IDs")
            except (InfraFailure, subprocess.TimeoutExpired) as exc:
                report: dict[str, Any] = {
                    "identity": identity,
                    "abstained": True,
                    "reason": str(exc),
                    "exits": exits,
                }
                (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps(report))
                return EXIT_ABSTAINED
            finally:
                for checkout in reversed(checkouts):
                    git("worktree", "remove", "--force", str(checkout))
        delta = transitions.delta()
        evidence["verification"] = "job-produced" if ci else "local-operator-run"
        source = "ci" if ci else "operator"
        landed = ledger.settle(
            ticket.id,
            delta,
            source=source,
            evidence=evidence,
            detail="Fixed base evaluation compared with task commit",
        )
        if not landed:
            raise ValueError("Settlement rejected")
        ledger.tick()
        ledger.save(memory)
        report = {
            "identity": identity,
            "evidence": evidence,
            "source": source,
            "delta": delta,
            "improvements": transitions.improvements,
            "regressions": transitions.regressions,
            "settled": True,
            "exits": exits,
            "comparison": "same evaluation at base and head",
            "head_evaluation_file_changes": evaluation_changes,
            "suite_changes_note": (
                "Head evaluation changes are listed by path, not executed or credited"
            ),
            "causation": "not established",
        }
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
        return 0


def register_adoption_commands(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    init = sub.add_parser(
        "init", help="generate repository-local MCP and GitHub pytest setup"
    )
    init.add_argument("--profile", choices=["github-pytest"], required=True)
    init.set_defaults(fn=cmd_init)
    task = sub.add_parser(
        "task", help="bind a ticket and evaluate its fixed task comparison"
    )
    task.add_argument("--memory", default=".darwin-memo/memory.json")
    ops = task.add_subparsers(dest="task_op", required=True)
    bind = ops.add_parser("bind")
    evaluate = ops.add_parser("evaluate")
    for parser in (bind, evaluate):
        parser.add_argument("--ticket", required=True)
        parser.add_argument("--repository", required=True)
        parser.add_argument("--task", required=True)
        parser.set_defaults(fn=cmd_task)
    bind.add_argument("--base", default="HEAD")
    bind.add_argument("--evaluation", default="tests")
    evaluate.add_argument("--head", required=True)
    evaluate.add_argument("--run", required=True)
    evaluate.add_argument(
        "--timeout",
        type=float,
        default=300,
        help="seconds per evaluation; timeout abstains",
    )
    evaluate.add_argument("--output", default=".darwin-memo/outcome")
