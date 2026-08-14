"""Gold-file recall: does the prompt even contain the file the task edits?

The real-task leg came back null, and `limitations.tex` names the reason it
cannot be attributed: BM25 might simply never put the file the model must patch
into the prompt, in which case no curation policy can produce a learning curve
and the null says nothing about memory. This module measures that directly.

It needs no model, no docker and no evaluation harness --- only the pinned
dataset and the repository archives --- because the question is retrieval, not
resolution: is any file touched by the gold patch present in the code context
the prompt carries?

Two conditions per task, over the same budget and the same prompt shape:

- **blind**: BM25 over the issue text, exactly what the arms get.
- **oracle**: the gold patch's files promoted ahead of BM25
  (``code_context(..., prefer=)``), which reads the answer key and is therefore
  only ever a control.

Usage::

    python -m bench.swebench_cl.recall --dataset PATH --sequence SEQ \\
        --code-context-chars 300000 --code-max-files 10
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .code_retrieval import code_context, oracle_files
from .dataset import TaskRecord, load_dataset, load_manifest, sequence_tasks
from .runner import retrieval_query


@dataclass(frozen=True)
class TaskRecall:
    instance_id: str
    gold: frozenset[str]
    blind: frozenset[str]
    oracle: frozenset[str]

    @property
    def blind_any(self) -> bool:
        return bool(self.gold & self.blind)

    @property
    def blind_all(self) -> bool:
        return self.gold <= self.blind

    @property
    def oracle_any(self) -> bool:
        return bool(self.gold & self.oracle)

    @property
    def oracle_all(self) -> bool:
        return self.gold <= self.oracle


def summarise(rows: list[TaskRecall]) -> dict[str, float | int]:
    """Recall rates over the measured tasks.

    ``any`` is the weaker and more decision-relevant question: a task where
    the model sees none of the files it must edit cannot be solved by any arm,
    so it is dead weight against the memory hypothesis regardless of curation.
    """
    n = len(rows)
    if not n:
        return {"tasks": 0}
    return {
        "tasks": n,
        "blind_any": sum(r.blind_any for r in rows) / n,
        "blind_all": sum(r.blind_all for r in rows) / n,
        "oracle_any": sum(r.oracle_any for r in rows) / n,
        "oracle_all": sum(r.oracle_all for r in rows) / n,
        "unreachable_blind": sum(not r.blind_any for r in rows),
    }


def measure(
    tasks: list[TaskRecord], cache: Path, max_chars: int, max_files: int
) -> list[TaskRecall]:
    rows: list[TaskRecall] = []
    for i, task in enumerate(tasks, start=1):
        gold = frozenset(oracle_files(task.gold_patch))
        if not gold:  # nothing to be right or wrong about
            continue
        query = retrieval_query(task)
        _, blind, _ = code_context(
            task.repo, task.base_commit, query, cache, max_chars, max_files
        )
        _, oracle, _ = code_context(
            task.repo,
            task.base_commit,
            query,
            cache,
            max_chars,
            max_files,
            prefer=sorted(gold),
        )
        row = TaskRecall(task.instance_id, gold, frozenset(blind), frozenset(oracle))
        rows.append(row)
        print(
            f"[{i}/{len(tasks)}] {row.instance_id:38} "
            f"bm25={'HIT ' if row.blind_any else 'miss'} "
            f"oracle={'HIT ' if row.oracle_any else 'miss'}",
            file=sys.stderr,
            flush=True,
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="bench/swebench_cl/manifests/pilot.json")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--cache", default=".swebench-repos")
    parser.add_argument("--code-context-chars", type=int, default=300_000)
    parser.add_argument("--code-max-files", type=int, default=10)
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    manifest = load_manifest(Path(args.manifest))
    dataset = load_dataset(Path(args.dataset))
    tasks = sequence_tasks(manifest, dataset, args.sequence)
    if args.max_tasks:
        tasks = tasks[: args.max_tasks]

    rows = measure(
        tasks, Path(args.cache), args.code_context_chars, args.code_max_files
    )
    report = {
        "sequence": args.sequence,
        "code_context_chars": args.code_context_chars,
        "code_max_files": args.code_max_files,
        **summarise(rows),
    }
    print(json.dumps(report, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
