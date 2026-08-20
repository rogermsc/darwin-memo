"""Curation-targeted adversary: attacking the defence, not the memory.

Every memory-curation mechanism is itself an attack surface, and the
memory-security literature has not modelled it. Write-time filters,
retrieval sanitizers, and outcome settlement all decide which entries
live, so an adversary who can perturb the deciding signal can weaponise
the curator: make it delete the benign entries that stand in the way,
and keep the poisoned one it planted. We call this a
*curation-targeted attack*, and the denial-of-memory case (starving a
defender's good entries) is the half nobody measures.

``FlakyStorageEnv`` is the wrong tool for this question by design: its
lies are a property of the world, drawn from a dedicated stream before
any arm acts, precisely so cross-arm comparison stays fair under
*random* noise. An adversary is not random. This wrapper keeps the
world truthful and fixed (same seed, same files, same sizes, same true
deltas) and makes only the *measurement* adaptive:

- ``true > 0`` (a benign entry just earned): report ``-true``. The
  entry that did the right thing is blamed for a disaster.
- ``true < 0`` (a poisoned entry just caused damage): report ``-true``,
  i.e. a large positive. The guilty entry is paid.
- ``true == 0``: nothing to distort. Silence is not measured, so it
  cannot be lied about.

The adversary is resource-bounded, which is what makes the experiment a
curve rather than an assertion: ``lie_budget`` lies per cycle, spent
greedily on the measured tasks in order. Budget is the x-axis; at
budget 0 this wrapper adds exactly zero behaviour and reproduces the
bare ``StorageEnv`` run, and at high budget every mechanism fails. The
question is where each one breaks.

Threat model, stated honestly: the adversary observes only the SIGN of
the true delta, never the store, the provenance, or which entry
decided. Sign is a sufficient proxy here (positive means a benign entry
acted well, negative means the poison acted) and it keeps the attacker
strictly weaker than one with store access, so the defence numbers are
not flattered by an implausibly blind opponent. A stronger adversary
that reads provenance and targets a *named* entry is the obvious next
step and would only widen the gaps this suite measures.

Two invariants this shares with the noise wrapper, both load-bearing:
the world is identical across arms at a fixed seed (only measurements
differ), and the accounting identity ``reported == true + distortion``
holds per cycle, checked by the runner. What it deliberately does NOT
share is arm-independence of the lie field: an adaptive adversary
spends its budget on whatever the arm actually did, so ``lies_fired``
differs per arm and is reported alongside every result. That is the
semantics of an adversary, not a confound, and the fair comparison is
at matched fired-lie counts rather than matched capacity.
"""

from __future__ import annotations

from pathlib import Path

from darwin_memo import Outcome, StorageEnv, Task

# What the attacker is buying. The paper's original adversary only ever
# bought destruction; the MemoryOS result (docs/benchmarks.md) showed that on a
# real deployed system persistence is the cheaper purchase, so it gets an
# objective of its own rather than being assumed away.
# "withhold" is the third: an attacker who SUPPRESSES a measurement
# rather than inverting it. It is a strict subset of what "destroy" can
# already express (a liar may always report zero), and it is weaker in
# the one way that matters for a threat model -- indiscriminate
# withholding needs no observation of the true delta's sign at all.
# It is here because of an asymmetry nothing else in this harness
# probes: `_run_baseline` never calls charge_upkeep, so among the arms
# ONLY the ledger has a clock. Lying breaks counters and spares the
# ledger; withholding should do the reverse, because credit is capped at
# max_energy and so bounded credit implies bounded runway.
# "withhold_selective" is the smarter withholder, and the one that closes
# the pacing mitigation's window. It suppresses ONLY the measurements
# that would incriminate its own poison (true.delta < 0) and lets benign
# outcomes through untouched. Same predicate as "persist", different
# payload: persist PAYS the poison a positive, this merely hides the
# damage. The point is what it does to a clock -- benign outcomes keep
# arriving, so evidence-paced upkeep never pauses, while the poison is
# never blamed. It is the attack survival_paced cannot see.
OBJECTIVES = ("destroy", "persist", "withhold", "withhold_selective")

# Objectives that report silence rather than an inverted delta.
_WITHHOLDING = ("withhold", "withhold_selective")


class AdversarialStorageEnv:
    """StorageEnv whose measurements lie in the attacker's favour."""

    def __init__(
        self,
        root: str | Path | None = None,
        files_per_cycle: int = 12,
        seed: int = 7,
        lie_budget: int = 2,
        objective: str = "destroy",
    ) -> None:
        if lie_budget < 0:
            raise ValueError(f"lie_budget must be >= 0, got {lie_budget}")
        if objective not in OBJECTIVES:
            raise ValueError(
                f"objective must be one of {OBJECTIVES}, got {objective!r}"
            )
        self.base = StorageEnv(root=root, files_per_cycle=files_per_cycle, seed=seed)
        self.resource_scale = self.base.resource_scale
        self.seed = seed
        self.lie_budget = lie_budget
        self.objective = objective
        self.true_deltas: list[float] = []
        self.reported_deltas: list[float] = []
        # Named for the noise wrapper's accounting surface so the runner,
        # the metrics, and the report treat both wrappers as one type.
        # "marked" is capacity offered, "fired" is capacity spent.
        self.flakes_marked = 0
        self.flakes_fired = 0
        self.fired_false_bad = 0  # benign work reported as damage
        self.fired_false_good = 0  # poison damage reported as a win
        self.distortion = 0.0
        self._cycle = -1
        self._spent_this_cycle = 0

    def tasks(self, cycle: int) -> list[Task]:
        tasks = self.base.tasks(cycle)
        self._cycle = cycle
        self._spent_this_cycle = 0
        self.flakes_marked += self.lie_budget
        while len(self.true_deltas) <= cycle:
            self.true_deltas.append(0.0)
            self.reported_deltas.append(0.0)
        return tasks

    def verify(self, task: Task, answer_text: str) -> Outcome:
        true = self.base.verify(task, answer_text)
        self.true_deltas[self._cycle] += true.delta
        reported = true
        # "destroy" spends on any measured outcome, so it both blames benign
        # entries and pays the poison. "persist" spends only when the poison
        # has just done damage, which is the cheaper objective and the one the
        # deployed MemoryOS result says an attacker would actually choose: it
        # never wastes a lie attacking a benign entry it does not need gone.
        # "withhold" spends on any measured outcome, like "destroy": what
        # differs is what it writes, not what it targets.
        # persist and withhold_selective spend only on the guilty; destroy
        # and withhold spend on any measured outcome.
        selective = self.objective in ("persist", "withhold_selective")
        worth_lying = true.delta < 0 if selective else true.delta != 0
        if self._spent_this_cycle < self.lie_budget and worth_lying:
            self._spent_this_cycle += 1
            self.flakes_fired += 1
            if true.delta > 0:
                self.fired_false_bad += 1
            else:
                self.fired_false_good += 1
            if self.objective in _WITHHOLDING:
                # Silence, not a lie. The entry is neither blamed nor
                # paid, and StorageEnv scores an unmeasured cycle at
                # zero, so the only thing that moves is the upkeep clock.
                reported = Outcome(
                    delta=0.0,
                    detail=(
                        f"{true.detail} [adversarial measurement: withheld, "
                        f"true {true.delta:+g}]"
                    ),
                )
            else:
                reported = Outcome(
                    delta=-true.delta,
                    detail=(
                        f"{true.detail} [adversarial measurement: reported "
                        f"{-true.delta:+g}, true {true.delta:+g}]"
                    ),
                )
        self.distortion += reported.delta - true.delta
        self.reported_deltas[self._cycle] += reported.delta
        return reported

    def cleanup(self) -> None:
        self.base.cleanup()
