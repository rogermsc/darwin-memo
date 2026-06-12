"""Run one (sequence, arm, seed): the pilot's task loop.

For each task, in curriculum order: select lessons per the arm, build
the prompt, collect one model completion, extract the patch, evaluate
it, settle the store from the measured test movement, mint a lesson,
advance one tick of upkeep. One run record per task, in the committed
format ``bench.manifest`` already binds.

Memory mechanics reuse the library's one credit rule
(:func:`darwin_memo.assign_credit`) and the store's own upkeep and
consolidation, exactly as ``bench/policies.py`` does for the storage
suites: same tanh, same supporting share, same merge behavior. The
production Ledger wraps the identical core; the pilot drives it
directly so the random_matched arm can name arbitrary provenance.
"""

from __future__ import annotations

import platform
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import darwin_memo
from darwin_memo import (
    EntryKind,
    MemoryEntry,
    MemoryStore,
    SurvivalConfig,
    assign_credit,
    consolidate,
)

from .arms import ARMS, ArmSpec, token_count
from .dataset import TaskRecord
from .executor import EvalReport, delta_from_eval
from .lessons import mint_lesson
from .model import ChatEndpoint, EndpointConfig, extract_patch, extract_reflection

SCHEMA_VERSION = 1
SUITE = "swebench_cl_pilot"
# Settlement deltas live in [-1, 1] by construction (test fractions),
# so the credit formula runs at unit scale.
RESOURCE_SCALE = 1.0
MAX_PROMPT_CHARS = 6000

SYSTEM_PROMPT = (
    "You are an expert software engineer fixing a reported issue in an "
    "open-source repository. Reply with a unified diff patch inside a "
    "```diff fence. After the patch, add exactly one line starting with "
    "REFLECTION: stating, in one sentence, what about this codebase or "
    "approach a future attempt should know."
)


class Completer(Protocol):
    def complete(self, prompt: str, system: str = "") -> str: ...


class Executor(Protocol):
    mode: str

    def evaluate(self, task: TaskRecord, patch: str) -> EvalReport: ...


@dataclass
class Injection:
    """What memory the model saw on one task, and at what budget."""

    entries: list[MemoryEntry] = field(default_factory=list)
    budget_tokens: int = 0

    @property
    def tokens(self) -> int:
        return sum(token_count(_lesson_text(e)) for e in self.entries)

    @property
    def deciding(self) -> str | None:
        return self.entries[0].id if self.entries else None

    @property
    def supporting(self) -> list[str]:
        return [e.id for e in self.entries[1:]]


def _lesson_text(entry: MemoryEntry) -> str:
    return f"{entry.question} {entry.answer}"


class LessonMemory:
    """The lesson store plus the arm-dependent selection rule."""

    def __init__(self, arm: ArmSpec, seed: int, config: SurvivalConfig) -> None:
        self.arm = arm
        self.config = config
        self.store = MemoryStore()
        self._rng = random.Random(seed)

    def select(self, query: str, k: int) -> Injection:
        """Lessons for this task. The budget is always relevance-priced.

        Both memory arms spend the SAME budget: the token count of what
        relevance retrieval selects for this query. memory_on injects
        that selection; random_matched discards it and refills the
        budget with uniformly random alive lessons (greedy, largest
        budget first preserved by shuffle order), so quantity matches
        and direction does not.
        """
        if self.arm.inject == "none":
            return Injection()
        hits = [entry for entry, _ in self.store.retrieve(query, k=k)]
        budget = sum(token_count(_lesson_text(e)) for e in hits)
        if self.arm.inject == "retrieved":
            return Injection(entries=hits, budget_tokens=budget)
        # random_matched
        pool = self.store.alive()
        self._rng.shuffle(pool)
        chosen: list[MemoryEntry] = []
        remaining = budget
        for entry in pool:
            cost = token_count(_lesson_text(entry))
            if cost <= remaining:
                chosen.append(entry)
                remaining -= cost
            if remaining <= 0:
                break
        return Injection(entries=chosen, budget_tokens=budget)

    def settle(self, injection: Injection, delta: float, tick: int) -> list[str]:
        """Credit the injected lessons with the measured outcome."""
        if not self.arm.settle or not injection.entries:
            return []
        applied = assign_credit(
            self.store,
            injection.deciding,
            injection.supporting,
            delta,
            RESOURCE_SCALE,
            self.config,
            tick,
        )
        return [entry_id for entry_id, _ in applied]

    def mint(self, question: str, answer: str, source: str, tick: int) -> str | None:
        if not self.arm.mint:
            return None
        entry = self.store.add(
            MemoryEntry(
                question=question,
                answer=answer,
                kind=EntryKind.EXPERIENCE,
                sources=[source],
                born_cycle=tick,
            )
        )
        return entry.id

    def tick(self, tick: int) -> dict[str, int]:
        """Upkeep, deaths, periodic consolidation. No-op for memory_off."""
        if self.arm.inject == "none":
            return {"deaths": 0, "merges": 0}
        dead = self.store.charge_upkeep()
        merges = 0
        every = self.config.consolidate_every
        if every and tick % every == 0:
            merges = consolidate(
                self.store, tick, threshold=self.config.merge_threshold
            )
        return {"deaths": len(dead), "merges": merges}


def retrieval_query(task: TaskRecord) -> str:
    """What lesson retrieval matches against for one task.

    The repo name is part of the query because it is part of the lesson
    vocabulary: ``mint_lesson`` phrases every question in repo terms so
    that future tasks IN THAT REPO can reach it past the lexical
    retriever's coverage floor. A bare problem statement that never
    names the repo would orphan every lesson the sequence minted.
    """
    return f"{task.repo} {task.problem_statement}"


def build_prompt(task: TaskRecord, injection: Injection, max_prompt_chars: int) -> str:
    parts = []
    if injection.entries:
        lines = "\n".join(f"- {_lesson_text(e)}" for e in injection.entries)
        parts.append(
            "Lessons recorded from earlier tasks in this repository:\n" + lines
        )
    statement = task.problem_statement[:max_prompt_chars]
    parts.append(
        f"Repository: {task.repo}\n"
        f"Task: {task.instance_id}\n\n"
        f"Issue:\n{statement}\n\n"
        "Produce the patch now."
    )
    return "\n\n".join(parts)


def run_sequence(
    tasks: list[TaskRecord],
    sequence_id: str,
    arm_name: str,
    endpoint: EndpointConfig,
    executor: Executor,
    seed: int = 0,
    k: int = 3,
    max_tasks: int | None = None,
    max_prompt_chars: int = MAX_PROMPT_CHARS,
    completer: Completer | None = None,
) -> list[dict[str, Any]]:
    """The pilot loop. Returns one run record per task, in order."""
    arm = ARMS[arm_name]
    memory = LessonMemory(arm, seed, SurvivalConfig(resource_scale=RESOURCE_SCALE))
    model: Completer = completer or ChatEndpoint(endpoint)
    runs: list[dict[str, Any]] = []
    for tick, task in enumerate(tasks[:max_tasks], start=1):
        start = time.perf_counter()
        injection = memory.select(retrieval_query(task), k=k)
        prompt = build_prompt(task, injection, max_prompt_chars)
        response = model.complete(prompt, system=SYSTEM_PROMPT)
        patch = extract_patch(response)
        reflection = extract_reflection(response)
        report = executor.evaluate(task, patch)
        delta = delta_from_eval(report)
        credited = memory.settle(injection, delta, tick)
        question, answer = mint_lesson(task, patch, reflection, report)
        minted = memory.mint(
            question, answer, source=f"swebench_cl:{task.instance_id}", tick=tick
        )
        upkeep = memory.tick(tick)
        runs.append(
            {
                "schema_version": SCHEMA_VERSION,
                "suite": SUITE,
                "arm": arm.name,
                "seed": seed,
                "sequence": sequence_id,
                "instance_id": task.instance_id,
                "order": task.order,
                "config": {
                    "endpoint": {
                        "base_url": endpoint.base_url,
                        "model": endpoint.model,
                    },
                    "executor": executor.mode,
                    "k": k,
                    "max_prompt_chars": max_prompt_chars,
                },
                "lessons": {
                    "injected": [e.id for e in injection.entries],
                    "tokens": injection.tokens,
                    "budget_tokens": injection.budget_tokens,
                    "credited": credited,
                    "minted": minted,
                },
                "model": {
                    "prompt_chars": len(prompt),
                    "response_chars": len(response),
                    "patch_chars": len(patch),
                    "reflection": reflection[:280],
                },
                "eval": report.to_dict(),
                "metrics": {
                    "delta": round(delta, 6),
                    "resolved": report.resolved,
                    "wall_time_s": round(time.perf_counter() - start, 4),
                },
                "store": {
                    "population": len(memory.store),
                    "graveyard": memory.store.dead_count(),
                    "total_energy": round(memory.store.total_energy(), 4),
                    "deaths_this_tick": upkeep["deaths"],
                    "merges_this_tick": upkeep["merges"],
                },
                "meta": {
                    "python": platform.python_version(),
                    "platform": sys.platform,
                    "darwin_memo": darwin_memo.__version__,
                },
            }
        )
    return runs
