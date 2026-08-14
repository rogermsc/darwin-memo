"""The curation-targeted attack, moved onto real software-engineering tasks.

``bench/adversary.py`` runs this attack inside a synthetic storage world.
That is where the paper's central claim currently lives, and a synthetic
world is a weak place for a central claim to live: the environment, the
tasks, and the outcome function were all written by the same hand that
wrote the defence. This module ports the same threat model to
SWE-Bench-CL, where the settled quantity is the passing-test delta
returned by the official docker harness and nobody involved chose it.

The attack is unchanged and deliberately so. The adversary injects no
poison of its own, reads only the SIGN of the true outcome, and never
touches the store, the prompt, the retrieval, or the repository. It
corrupts one thing: what the curator is told happened.

- ``true > 0`` (the injected lessons just helped fix an issue): report
  ``-true``. The lessons that worked are blamed for a regression.
- ``true < 0`` (the injected lessons just broke passing tests): report
  ``-true``. The lessons that did damage are paid for it.
- ``true == 0``: no movement, nothing to distort. A patch that failed to
  apply is not a measurement, so it cannot be lied about.

Budget is the x-axis, and it is denominated so the two environments are
comparable. ``StorageEnv`` offers ``lie_budget`` lies per cycle of
twelve files, so a budget of ``b`` corrupts at most ``b/12`` of the
measurements. Here a "cycle" is twelve *measured settlements* rather
than twelve tasks, because roughly forty percent of SWE-Bench tasks
produce no test movement at all: counting ticks instead would silently
inflate the real corruption rate by the fraction of tasks that happened
to fail to apply, which varies by arm. Counting settlements makes ``b``
mean the same fraction of the curator's evidence in both suites.

What the runner does with the result is the load-bearing half. The lie
goes to ``LessonMemory.settle`` and nowhere else; ``metrics.delta`` and
``metrics.resolved`` keep the harness's true numbers, so capability is
always scored against reality while the curator decides on the
corruption. Every existing analysis over ``metrics.delta`` therefore
measures what the arm actually achieved under attack, with no changes.
"""

from __future__ import annotations

# One cycle of measured settlements, mirroring ``StorageEnv``'s twelve
# files per cycle so that a budget of b is the same corruption rate in
# both suites and the two x-axes can be read against each other.
SETTLEMENTS_PER_CYCLE = 12


class SettlementAdversary:
    """Corrupts the settlement signal, ``lie_budget`` lies per cycle."""

    def __init__(self, lie_budget: int) -> None:
        if lie_budget < 0:
            raise ValueError(f"lie_budget must be >= 0, got {lie_budget}")
        self.lie_budget = lie_budget
        self.measured = 0  # settlements offered (true delta != 0)
        self.fired = 0  # settlements corrupted
        self.false_bad = 0  # a real fix reported as a regression
        self.false_good = 0  # real damage reported as a fix
        self.distortion = 0.0  # sum(reported - true), the accounting identity
        self._cycle = 0
        self._spent = 0

    def report(self, true_delta: float) -> float:
        """What the curator is told this task measured."""
        if true_delta == 0.0:
            return 0.0
        cycle = self.measured // SETTLEMENTS_PER_CYCLE
        if cycle != self._cycle:
            self._cycle = cycle
            self._spent = 0
        self.measured += 1
        if self._spent >= self.lie_budget:
            return true_delta
        self._spent += 1
        self.fired += 1
        if true_delta > 0:
            self.false_bad += 1
        else:
            self.false_good += 1
        self.distortion += -2.0 * true_delta
        return -true_delta

    def stats(self) -> dict[str, float | int]:
        """Cumulative accounting, written into every run record."""
        return {
            "lie_budget": self.lie_budget,
            "measured": self.measured,
            "lies_fired": self.fired,
            "false_bad": self.false_bad,
            "false_good": self.false_good,
            "distortion": round(self.distortion, 6),
        }
