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
from pathlib import Path
from typing import Any, Protocol

import darwin_memo
from darwin_memo import (
    EntryKind,
    LexicalRetriever,
    MemoryEntry,
    MemoryStore,
    SurvivalConfig,
    assign_credit,
    consolidate,
)

from .adversary import SettlementAdversary
from .arms import ARMS, ArmSpec, token_count
from .code_retrieval import code_context as retrieve_code_context
from .dataset import TaskRecord
from .edits import EDIT_FORMAT_INSTRUCTIONS, edits_to_patch
from .executor import EvalReport, delta_from_eval
from .lessons import mint_lesson
from .model import ChatEndpoint, EndpointConfig, extract_patch, extract_reflection
from .poison import POISON_SOURCE_PREFIX

SCHEMA_VERSION = 1
SUITE = "swebench_cl_pilot"
# Settlement deltas live in [-1, 1] by construction (test fractions),
# so the credit formula runs at unit scale.
RESOURCE_SCALE = 1.0
MAX_PROMPT_CHARS = 6000
# Lessons are retrieved as CONTEXT (top-k by relevance), not as decisions,
# so the default coverage floor (0.25 of the query's IDF mass) is the wrong
# gate here: a one-sentence lesson can never cover a quarter of a full
# problem-statement query, so the floor silently injected nothing (every
# task, every arm) and made memory_on identical to memory_off. A floor of
# 0 means "rank all alive lessons by overlap and take the top k", which is
# the right semantics for retrieving context to condition on.
LESSON_MIN_COVERAGE = 0.0

SYSTEM_PROMPT = (
    "You are an expert software engineer fixing a reported issue in an "
    "open-source repository. Follow the output format the task specifies "
    "exactly. After your edit, add exactly one line starting with "
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
        self.store = MemoryStore(retriever=LexicalRetriever(LESSON_MIN_COVERAGE))
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
        if not injection.entries:
            return []
        if self.arm.curation == "evict_negative":
            if delta < 0:
                for e in injection.entries:
                    self.store.bury(e.id)
            return []
        if self.arm.curation == "keep_all":
            return []
        if not self.arm.settle:
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
        return [eid for eid, _ in applied]

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

    def seed_poison(self, entries: list[MemoryEntry]) -> None:
        """Add poison lessons to the store.

        Poison lessons are designed to contaminate the store with
        incorrect guidance that defenders the buggy behavior. They are
        used to test whether survival selection can identify and cull them.
        """
        for e in entries:
            self.store.add(e)

    def poison_alive(self) -> int:
        """Seeded poison lessons still retrievable.

        The defence half of the adversarial measurement: an arm that
        keeps capability by never removing anything is not defending,
        and this is the column that says so.
        """
        return sum(
            1
            for e in self.store.alive()
            if any(s.startswith(POISON_SOURCE_PREFIX) for s in e.sources)
        )

    def tick(self, tick: int) -> dict[str, int]:
        """Upkeep, deaths, periodic consolidation. No-op for memory_off."""
        if self.arm.inject == "none" or self.arm.curation != "survival":
            return {"deaths": 0, "merges": 0}
        dead = self.store.charge_upkeep()
        merges = 0
        if self.config.consolidate_every and tick % self.config.consolidate_every == 0:
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


def build_prompt(
    task: TaskRecord,
    injection: Injection,
    max_prompt_chars: int,
    code_context: str = "",
) -> str:
    parts = []
    if injection.entries:
        lines = "\n".join(f"- {_lesson_text(e)}" for e in injection.entries)
        parts.append(
            "Lessons recorded from earlier tasks in this repository:\n" + lines
        )
    statement = task.problem_statement[:max_prompt_chars]
    parts.append(
        f"Repository: {task.repo}\nTask: {task.instance_id}\n\nIssue:\n{statement}"
    )
    if code_context:
        parts.append(
            "Relevant repository files at the current commit (retrieved by "
            "BM25 over the issue text; the file the issue concerns is likely "
            "among them):\n\n" + code_context
        )
        parts.append(EDIT_FORMAT_INSTRUCTIONS)
    else:
        parts.append("Produce the patch now.")
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
    code_context_chars: int = 0,
    code_cache_dir: Path | None = None,
    code_max_files: int = 5,
    seed_poison: bool = False,
    lie_budget: int = 0,
) -> list[dict[str, Any]]:
    """The pilot loop. Returns one run record per task, in order.

    When ``code_context_chars > 0`` the prompt also carries BM25-retrieved
    source files from the repo at the task's base commit (the Level-1b
    setting); the retrieval query is the issue text, identical across
    arms, so only the lesson memory differs between arms.

    ``lie_budget > 0`` mounts the curation-targeted attack
    (:mod:`.adversary`): the curator settles on a corrupted signal while
    ``metrics`` keeps the harness's true numbers, so capability is scored
    against reality no matter what the curator was told. At 0 the
    adversary is constructed but never fires, and the loop is byte-for-byte
    the unattacked one.
    """
    arm = ARMS[arm_name]
    adversary = SettlementAdversary(lie_budget)
    memory = LessonMemory(arm, seed, SurvivalConfig(resource_scale=RESOURCE_SCALE))
    if seed_poison and arm.inject != "none":
        from .poison import poison_lessons

        memory.seed_poison(poison_lessons(tasks[:max_tasks]))
    model: Completer = completer or ChatEndpoint(endpoint)
    cache = code_cache_dir or (Path.cwd() / ".swebench-repos")
    runs: list[dict[str, Any]] = []
    for tick, task in enumerate(tasks[:max_tasks], start=1):
        start = time.perf_counter()
        injection = memory.select(retrieval_query(task), k=k)
        code_ctx: str = ""
        code_files: list[str] = []
        code_originals: dict[str, str] = {}
        if code_context_chars > 0:
            try:
                code_ctx, code_files, code_originals = retrieve_code_context(
                    task.repo,
                    task.base_commit,
                    retrieval_query(task),
                    cache,
                    code_context_chars,
                    code_max_files,
                )
            except Exception as error:  # retrieval must never crash a run
                print(
                    f"  warn: code retrieval failed for {task.instance_id}: "
                    f"{type(error).__name__}: {error}",
                    file=sys.stderr,
                )
        prompt = build_prompt(task, injection, max_prompt_chars, code_context=code_ctx)
        response = model.complete(prompt, system=SYSTEM_PROMPT)
        if code_context_chars > 0:
            # Edit-based path: the model emits SEARCH/REPLACE blocks and we
            # compute the diff, so hunk line numbers are always correct.
            patch, edits_applied, edits_failed, edits_relaxed = edits_to_patch(
                code_originals, response
            )
        else:
            patch = extract_patch(response)
            edits_applied = edits_failed = edits_relaxed = 0
        reflection = extract_reflection(response)
        report = executor.evaluate(task, patch)
        delta = delta_from_eval(report)
        # The curator decides on `reported`; everything scored downstream
        # reads `delta`, which is what the harness actually measured.
        reported = adversary.report(delta)
        credited = memory.settle(injection, reported, tick)
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
                    "code_context_chars": code_context_chars,
                    "retrieved_files": code_files,
                    # Both belong to the record rather than the filename:
                    # an unattacked poisoned cell is otherwise byte-identical
                    # in shape to a clean one, and only the directory would
                    # say which world it came from.
                    "seed_poison": seed_poison,
                    "lie_budget": lie_budget,
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
                    "edits_applied": edits_applied,
                    "edits_failed": edits_failed,
                    # How many of `applied` needed the whitespace-tolerant
                    # retry: the fallback's contribution, never hidden
                    # inside the success count.
                    "edits_relaxed": edits_relaxed,
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
                    "poison_alive": memory.poison_alive(),
                },
                "adversary": {
                    "reported_delta": round(reported, 6),
                    "lied": reported != delta,
                    **adversary.stats(),
                },
                "meta": {
                    "python": platform.python_version(),
                    "platform": sys.platform,
                    "darwin_memo": darwin_memo.__version__,
                },
            }
        )
    return runs
