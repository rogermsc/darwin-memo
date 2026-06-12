"""Environments: where selection pressure comes from.

The survival paper's design constraint is that the selection signal is a
conserved, physically measurable resource, never a model's judgment of
success. Its reference environment scores agents by non-volatile storage
freed inside a procedurally generated sandbox. ``StorageEnv`` reproduces
that setup at demo scale with real files in a real temp directory, and
regenerates the sandbox every cycle exactly as the paper regenerates its
containers, so nothing can overfit to one filesystem instance.

Implement the :class:`Environment` protocol to plug in your own pressure:
tests passing, requests served under budget, rows deduplicated. The
environment owns the whole contract: it phrases the task, it reads the
answer (including what to do when memory is silent), it acts, and it
measures. The one rule is that ``verify`` must measure, never grade.
"""

from __future__ import annotations

import hashlib
import random
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .types import Outcome


def cycle_rng(seed: int, cycle: int, stream: str = "") -> random.Random:
    """Deterministic RNG for one (seed, cycle) world, independent across seeds.

    The obvious ``random.Random(seed + cycle)`` makes adjacent seeds
    shifted windows of one another: seed 3 at cycle 5 IS seed 4 at
    cycle 4, so "10 seeds" are overlapping rather than independent
    draws and across-seed spreads read smoother than they should.
    Hashing the triple instead gives every (seed, cycle) pair its own
    statistically independent stream while staying fully deterministic:
    the same seed always reproduces the same world. ``stream`` separates
    consumers that must not share draws at the same (seed, cycle), e.g.
    flaky-measurement marks from the file generation they decorate.
    """
    digest = hashlib.sha256(f"{stream}:{seed}:{cycle}".encode()).digest()
    return random.Random(int.from_bytes(digest, "big"))


@dataclass
class Task:
    """A question the agent must act on, plus opaque environment context."""

    prompt: str
    context: dict[str, Any]


class Environment(Protocol):
    resource_scale: float

    def tasks(self, cycle: int) -> list[Task]: ...

    def verify(self, task: Task, answer_text: str) -> Outcome: ...


# ---------------------------------------------------------------------------
# Reading an action out of a memory answer
# ---------------------------------------------------------------------------

# The default vocabulary speaks the bundled environments' dialect:
# delete/remove (StorageEnv) and apply/keep (TestSuiteEnv). If your
# environment's actions use different verbs (cancel, restart, migrate),
# you MUST extend these or the reader returns None on every answer and
# your whole population silently starves. Pass extra markers rather
# than relying on the defaults.
NEGATIVE_MARKERS = (
    "must be retained",
    "must not be deleted",
    "never delete",
    "do not delete",
    "not safe to delete",
    "must be kept",
    "should be kept",
    "keep it",
    "keep this",
    "protected",
    "required for",
    "retained indefinitely",
    "must not be applied",
    "should not be applied",
    "do not apply",
    "load-bearing",
    "never cancel",
    "do not cancel",
)
POSITIVE_MARKERS = (
    "safe to delete",
    "may be deleted",
    "can be deleted",
    "safe to remove",
    "may be removed",
    "can be removed",
    "redundant",
    "disposable",
    "should be applied",
    "safe to apply",
    "may be applied",
)


_NEGATION_TAIL_RE = re.compile(
    r"(?:\bnot\b|\bnever\b|\bisn't\b|\baren't\b|\bdon't\b|\bdo not\b|"
    r"\bno longer\b|\bwouldn't\b)\s*(?:\w+\s+){0,2}$"
)


def _marker_present(text: str, marker: str, guard_negation: bool) -> bool:
    """Whole-word marker match, so 'keep it' never fires inside 'keep
    iterating' and 'protected' never fires inside 'unprotected'.

    With ``guard_negation``, a match immediately preceded by a negation
    ("it is NOT safe to cancel") does not count; used for positive
    markers, where a negated match acting would be the dangerous misread.
    """
    pattern = r"\b" + re.escape(marker.lower()) + r"\b"
    for match in re.finditer(pattern, text):
        if guard_negation and _NEGATION_TAIL_RE.search(text[: match.start()]):
            continue
        return True
    return False


def decision_polarity(
    answer_text: str,
    extra_positive: tuple[str, ...] = (),
    extra_negative: tuple[str, ...] = (),
) -> bool | None:
    """Read a yes/no action decision out of a memory answer.

    This lives in the environment layer because the vocabulary is the
    environment's own: the env phrased the task, so the env knows how to
    read an answer to it. Negative markers win over positive ones: when
    memory is ambiguous about something irreversible, the safe reading
    is no. Returns True (act), False (do not act), or None (memory is
    silent).

    Markers match on word boundaries, and positive markers do not fire
    when directly negated ("it is not safe to cancel" reads as silence,
    not as act). The built-in vocabulary covers delete/remove and
    apply/keep, the dialects of the bundled environments. For any other
    action verb, pass your own markers::

        decision_polarity(text,
            extra_positive=("safe to cancel", "should be cancelled"),
            extra_negative=("do not cancel", "keep paying"))

    A None result fed to a conservative environment means "do not act",
    which earns zero. If every answer in your environment reads as None,
    nothing ever earns and the population starves: extend the vocabulary
    before blaming the selection mechanics.
    """
    text = answer_text.lower()
    if not text.strip():
        return None
    for marker in (*NEGATIVE_MARKERS, *extra_negative):
        if _marker_present(text, marker, guard_negation=False):
            return False
    for marker in (*POSITIVE_MARKERS, *extra_positive):
        if _marker_present(text, marker, guard_negation=True):
            return True
    if re.search(r"\byes\b", text):
        return True
    if re.search(r"\bno\b", text):
        return False
    return None


# ---------------------------------------------------------------------------
# StorageEnv
# ---------------------------------------------------------------------------

# Category name, filename pattern, size range in KiB, safe to delete.
# Protected files carry a restore cost: destroying one forces a restore
# from backup that consumes three times the freed space, so the resource
# delta is genuinely negative, not a bolted-on penalty score.
_FILE_SPECS = [
    ("old_log", "logs/app-{i}.log", (40, 120), True),
    ("cache", "cache/chunk-{i}.cache", (30, 90), True),
    ("tmp_artifact", "tmp/build-{i}.tmp", (20, 60), True),
    ("database", "data/store-{i}.db", (50, 150), False),
    ("report", "reports/quarterly-{i}.pdf", (30, 80), False),
]


class StorageEnv:
    """A disk-cleanup sandbox where the reward IS bytes freed.

    Each cycle procedurally generates a fresh directory tree, then asks
    the agent file by file: is this safe to delete? Acting on a
    disposable file frees its real size. Acting on a protected file
    triggers a restore that costs three times the size. When memory is
    silent or ambiguous the file is kept, the conservative reading of
    an irreversible action, and the delta is zero. No judge anywhere in
    the loop.
    """

    resource_scale = 100_000.0  # bytes, normalization hint for credit

    def __init__(
        self,
        root: str | Path | None = None,
        files_per_cycle: int = 12,
        seed: int = 7,
    ) -> None:
        self.root = (
            Path(root) if root else Path(tempfile.mkdtemp(prefix="darwin-memo-"))
        )
        self.files_per_cycle = files_per_cycle
        self.seed = seed
        self._sandbox: Path | None = None

    def tasks(self, cycle: int) -> list[Task]:
        rng = cycle_rng(self.seed, cycle)
        if self._sandbox and self._sandbox.exists():
            shutil.rmtree(self._sandbox)
        self._sandbox = self.root / f"cycle-{cycle}"

        tasks: list[Task] = []
        for i in range(self.files_per_cycle):
            category, pattern, (lo, hi), safe = rng.choice(_FILE_SPECS)
            path = self._sandbox / pattern.format(i=i)
            path.parent.mkdir(parents=True, exist_ok=True)
            size = rng.randint(lo, hi) * 1024
            path.write_bytes(rng.randbytes(size))
            tasks.append(
                Task(
                    prompt=(
                        f"Is it safe to delete the file {path.name} "
                        f"(a {category.replace('_', ' ')} file "
                        f"under {path.parent.name}/)?"
                    ),
                    context={
                        "path": path,
                        "safe": safe,
                        "size": size,
                        "category": category,
                    },
                )
            )
        return tasks

    def verify(self, task: Task, answer_text: str) -> Outcome:
        act = decision_polarity(answer_text)
        if not act:
            return Outcome(delta=0.0, detail="kept")
        path: Path = task.context["path"]
        size: int = task.context["size"]
        path.unlink(missing_ok=True)
        if task.context["safe"]:
            return Outcome(delta=float(size), detail=f"freed {size} bytes")
        # Restore from backup: the file comes back and the restore
        # process consumes three times its size in scratch space.
        path.write_bytes(b"\0" * size)
        return Outcome(
            delta=-3.0 * size,
            detail=f"destroyed protected data, restore cost {3 * size} bytes",
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


# ---------------------------------------------------------------------------
# VerifiableQAEnv
# ---------------------------------------------------------------------------


class VerifiableQAEnv:
    """Tasks with deterministic, checkable answers.

    Verification is exact containment of a known token in the answer.
    That is weaker grounding than real resources, but it is still a
    measurement rather than a judgment: no model scores anything.
    Useful for testing memory quality on QA corpora.
    """

    resource_scale = 1.0

    def __init__(
        self, qa_pairs: list[tuple[str, str]], per_cycle: int = 5, seed: int = 7
    ) -> None:
        self.qa_pairs = qa_pairs
        self.per_cycle = per_cycle
        self.seed = seed

    def tasks(self, cycle: int) -> list[Task]:
        rng = cycle_rng(self.seed, cycle)
        sample = rng.sample(self.qa_pairs, k=min(self.per_cycle, len(self.qa_pairs)))
        return [Task(prompt=q, context={"expected": a}) for q, a in sample]

    def verify(self, task: Task, answer_text: str) -> Outcome:
        expected: str = task.context["expected"]
        if expected.lower() in answer_text.lower():
            return Outcome(delta=1.0, detail="verified")
        return Outcome(delta=-0.5, detail=f"expected '{expected}'")
