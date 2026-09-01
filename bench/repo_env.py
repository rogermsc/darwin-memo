"""Selection pressure from tests passing in real repositories.

Conserved resource: **net passing tests**, gained minus lost, exactly as
``darwin_memo/ci.py`` computes it for a real CI run. Acting means shipping a
candidate patch; the outcome is what the SWE-bench harness actually measured
when it ran that repository's suite against it.

The decision is triage, which is the decision a maintainer really faces: this
patch applied, do you take it? Taking a good one gains the tests it fixes.
Taking a bad one loses the previously-passing tests it breaks, and in this
data that is not hypothetical -- 94 of 423 evaluations broke something, one of
them 1,432 tests.

**The outcomes are replayed, not re-run.** Evaluating 141 instances in Docker
takes hours and an API budget, so this reads the committed per-instance
results under ``bench/results/swebench_cl*/``, which came from exactly that.
The environment is therefore offline and deterministic, and the numbers are
real measurements of real repositories (astropy, django, pytest, sympy) that
nobody here authored. What it cannot do is measure a patch that was never
evaluated, which is the honest limit of a replay.

**Why this is not the SWE-Bench-CL null again.** That experiment asked whether
a coding agent solves more tasks when given memory, and got no. This asks a
different question with a signal the data actually contains: indiscriminate
shipping is net-negative here (mean -6.7 tests per patch), because a few
catastrophic regressions dominate, so the value is entirely in *discriminating*.
Discrimination is what a memory of lessons is for, and the discriminating rule
is learnable from the surface of the patch:

======================  =====  =========================================
candidate               mean   what it is
======================  =====  =========================================
empty patch             0.00   nothing to gain, nothing to break
clean apply, small      +1.20  46 of 48 outcomes non-negative
clean apply, large      ~-8.5  where every catastrophic regression is
======================  =====  =========================================

Which is the three death modes on real data: advice that earns, advice that
gets executed for the damage it causes, and advice nothing ever punishes that
simply starves.

**Two things this measured that were not the point, and are reported anyway.**

*The useless lesson free-rides.* "An empty patch is worth shipping" decides
tasks whose delta is always exactly zero, so it earns nothing by deciding --
and it still finishes 30 cycles alive, at 0.19 energy, because supporting
entries take 25% of the credit on answers they merely contributed to. Run it
as the only entry in the store and it dies. It survives on the profitable
lesson's winnings, and no measurement it is party to ever contradicts it.

*Killing the specific lesson widens the general one.* On one seed of six the
narrow lesson died too, and not from bad luck: its own draws summed to +53.
Once the sprawling lesson died at cycle 3, the narrow lesson became the
top-ranked entry for sprawling candidates -- it clears the relevance floor on
them -- and was executed for damage it never advised. It logged 47 uses
against 35 narrow draws. Removing a narrowly-true entry's competitor makes it
answer questions it was never true of, which is a property of retrieval with a
floor, not of this corpus.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from darwin_memo import EntryKind, MemoryEntry, Outcome, Task
from darwin_memo.environments import cycle_rng, decision_polarity

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "bench" / "results"

# A patch at or below this many characters is "small". Chosen from the data
# (mean +1.20 at 500 chars, +0.22 by 1500, and negative beyond), and it is a
# threshold on the corpus rather than a claim about patches in general.
SMALL_PATCH_CHARS = 500

SHIP = ("worth shipping", "safe to ship", "ship it")
HOLD = ("do not ship", "never ship", "hold it back", "discard it")


@dataclass(frozen=True)
class Candidate:
    """One evaluated patch: its pre-decision shape and its measured outcome."""

    instance_id: str
    repo: str
    seed: int
    empty: bool
    applied: bool
    edits_failed: int
    patch_chars: int
    f2p_passed: int
    p2p_lost: int

    @property
    def shape(self) -> str:
        """What is knowable before deciding. Never mentions the outcome."""
        if self.empty or not self.applied:
            return "empty"
        if self.edits_failed:
            return "failed-edits"
        return "small" if self.patch_chars <= SMALL_PATCH_CHARS else "large"

    @property
    def delta(self) -> float:
        """Net passing tests. Gained minus lost, no weighting to defend."""
        return float(self.f2p_passed - self.p2p_lost)


def _rows(arm: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(RESULTS.glob("swebench_cl*/*.json")):
        if path.name == "MANIFEST.json":
            continue
        for run in json.loads(path.read_text()).get("runs", []):
            if run.get("arm") == arm:
                out.append(run)
    return out


def load_candidates(arm: str = "memory_off") -> list[Candidate]:
    """Every evaluated instance for one arm of the committed matrix.

    ``memory_off`` by default: it is the arm with no lesson store in the loop,
    so its outcomes are a property of the model and the repository rather than
    of a curation policy this environment is about to test.
    """
    candidates = []
    for run in _rows(arm):
        ev, model = run["eval"], run["model"]
        candidates.append(
            Candidate(
                instance_id=run["instance_id"],
                repo=run["sequence"].removesuffix("_sequence"),
                seed=run["seed"],
                empty=bool(ev.get("empty_patch")),
                applied=bool(ev.get("patch_applied")),
                edits_failed=int(model.get("edits_failed", 0)),
                patch_chars=int(model.get("patch_chars", 0)),
                f2p_passed=int(ev.get("f2p_passed", 0)),
                p2p_lost=int(ev.get("p2p_total", 0)) - int(ev.get("p2p_passed", 0)),
            )
        )
    if not candidates:
        raise RuntimeError(f"no committed rows for arm {arm!r}")
    return candidates


# The seed lessons. Two are true of this data, one is true of nothing, and the
# fourth is the poison: it is the plausible over-generalisation of the first.
LESSONS = [
    (
        "small",
        "Should a narrow patch be shipped?",
        "A narrow patch is worth shipping: it fixes what it targets and "
        "touches too little to break the rest of the suite.",
    ),
    (
        "large",
        "Should a sprawling patch be shipped?",
        "A sprawling patch is worth shipping, because applying cleanly is "
        "what shows the change is coherent.",
    ),
    (
        "empty",
        "Should an empty patch be shipped?",
        "An empty patch is worth shipping; it changes nothing, so it is safe.",
    ),
    (
        "failed-edits",
        "Should a rejected patch be shipped?",
        "A rejected patch is worth shipping; the parts that landed are still "
        "an improvement.",
    ),
]


def lesson_entries() -> list[MemoryEntry]:
    return [
        MemoryEntry(
            question=question,
            answer=answer,
            kind=EntryKind.EXPLICIT,
            sources=[f"repo-lesson:{shape}"],
        )
        for shape, question, answer in LESSONS
    ]


class RepoEnv:
    """Ship a candidate patch or hold it; the repository's suite settles it."""

    # A typical good outcome. The median positive delta in this data is 1 test
    # and the mean of the small-patch class is +1.2, so deltas of a few tests
    # should earn most of the available credit rather than saturating on the
    # rare 400-test instance.
    resource_scale = 3.0

    def __init__(
        self, seed: int = 0, per_cycle: int = 8, arm: str = "memory_off"
    ) -> None:
        self.seed = seed
        self.per_cycle = per_cycle
        self.candidates = load_candidates(arm)
        self._by_key = {(c.instance_id, c.seed): c for c in self.candidates}

    def tasks(self, cycle: int) -> list[Task]:
        rng = cycle_rng(self.seed, cycle, "repo-env")
        chosen = rng.sample(self.candidates, min(self.per_cycle, len(self.candidates)))
        return [
            Task(
                prompt=self._prompt(c),
                context={"key": [c.instance_id, c.seed], "repo": c.repo},
            )
            for c in chosen
        ]

    @staticmethod
    def _prompt(c: Candidate) -> str:
        """Short, and distinctive per class.

        Two rounds of the relevance floor, both worth recording. First
        version: every candidate read "the candidate patch applied cleanly and
        is small/large", and the shared eight words outweighed the one that
        mattered, so the narrow lesson decided sprawling candidates and was
        executed for damage it never advised. Second version fixed the
        vocabulary but also led with the repository name, which tokenises to a
        rare term carrying most of the query mass -- every class then fell
        below the floor and the whole population starved silent.

        So: one distinctive content word per class, the same verb form the
        lessons use ("shipped", not "ship it"), and nothing in the prompt that
        no lesson can match. The repository lives in ``context``, where the
        outcome lookup needs it and retrieval does not have to pay for it.
        """
        described = {
            "empty": "An empty patch",
            "failed-edits": "A rejected patch",
            "small": "A narrow patch applied cleanly",
            "large": "A sprawling patch applied cleanly",
        }[c.shape]
        return f"{described}. Should it be shipped?"

    def verify(self, task: Task, answer_text: str) -> Outcome:
        act = decision_polarity(answer_text, extra_positive=SHIP, extra_negative=HOLD)
        if not act:
            return Outcome(delta=0.0, detail="held back")
        instance_id, seed = task.context["key"]
        c = self._by_key[(instance_id, seed)]
        return Outcome(
            delta=c.delta,
            detail=(
                f"shipped {c.instance_id}: +{c.f2p_passed} fixed, -{c.p2p_lost} broken"
            ),
        )
