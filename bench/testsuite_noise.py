"""Flaky-pass-count noise for TestSuiteEnv: CI flakiness on purpose.

``FlakyTestSuiteEnv`` wraps ``TestSuiteEnv`` the way ``FlakyStorageEnv``
wraps ``StorageEnv``: the WORLD stays truthful (patches really edit
app.py, the suite really runs), only the MEASUREMENT lies. Arms decide
off REPORTED deltas; the benchmark scores them on TRUE ones.

The noise model is the one CI actually has. Each cycle, every test in
the suite is flaky with probability ``flake_rate``: a flaky test that
genuinely passes reports a failure that cycle, and reports passing
again once the mark moves on (it flips to fail, and back). The CI's
accepted baseline (the pass count before the patch) is taken as known,
so for a measured patch:

    reported delta = true delta - |genuinely passing tests after the
                                   patch that are marked flaky|

This is one-sided by construction, the ``false_bad`` shape: a good
patch can report a red build because an unrelated flaky test failed in
its CI run, but a genuinely broken build never reports green (a
failing test has nothing to flip). ``fired_false_good`` is therefore
structurally zero and is reported anyway so the metric schema matches
the StorageEnv noise harness.

The flake field is a property of the world, not of the run, with the
same preconditions the StorageEnv wrapper enforces:

- One uniform draw per (cycle, test), consumed in the fixed
  ``TEST_NAMES`` order from a dedicated RNG stream keyed by (seed,
  cycle), never the base env's own stream. Every arm at the same seed
  and rate faces the same flaky set; marks are ``uniform < rate``, so
  the flaky sets at two rates are nested (monotone coupling).
- A skipped patch produces no suite run and therefore no measurement
  event to corrupt: silence stays a noise-free harbor, exactly as in
  StorageEnv, and ``flakes_fired`` stays endogenous to the arm.
- At rate 0.0 the wrapper adds zero behavior.
"""

from __future__ import annotations

from pathlib import Path

from darwin_memo import Outcome, Task, TestSuiteEnv
from darwin_memo.environments import cycle_rng
from darwin_memo.testsuite_env import TEST_NAMES, run_suite_detail


class FlakyTestSuiteEnv:
    """TestSuiteEnv whose pass counts lie at a seeded, fixed rate."""

    __test__ = False  # the name looks collectable to pytest; it is not a test

    def __init__(
        self,
        root: str | Path | None = None,
        defects_per_cycle: int = 3,
        seed: int = 7,
        flake_rate: float = 0.1,
    ) -> None:
        if not 0.0 <= flake_rate <= 1.0:
            raise ValueError(f"flake_rate must be in [0, 1], got {flake_rate}")
        self.base = TestSuiteEnv(
            root=root, defects_per_cycle=defects_per_cycle, seed=seed
        )
        self.resource_scale = self.base.resource_scale
        self.seed = seed
        self.flake_rate = flake_rate
        self.true_deltas: list[float] = []  # index = cycle, sums TRUE movement
        self.reported_deltas: list[float] = []
        self.flakes_marked = 0  # world property: (cycle, test) marks drawn true
        self.flakes_fired = 0  # arm exposure: lies that corrupted a measurement
        self.fired_false_bad = 0  # the only direction this model has
        self.fired_false_good = 0  # structurally zero, kept for schema parity
        self.distortion = 0.0  # sum(reported - true), the accounting identity
        self._cycle = -1
        self._flaky: frozenset[str] = frozenset()

    def tasks(self, cycle: int) -> list[Task]:
        tasks = self.base.tasks(cycle)
        # One draw per test per cycle, always consumed, rate-independent
        # stream: marks nest across rates and are identical across arms
        # at a fixed seed, while staying independent of the base env's
        # defect planting.
        rng = cycle_rng(self.seed, cycle, stream="flaky-tests")
        flaky = frozenset(name for name in TEST_NAMES if rng.random() < self.flake_rate)
        self._flaky = flaky
        self.flakes_marked += len(flaky)
        for task in tasks:
            task.context["flaky_tests"] = flaky
        self._cycle = cycle
        while len(self.true_deltas) <= cycle:
            self.true_deltas.append(0.0)
            self.reported_deltas.append(0.0)
        return tasks

    def verify(self, task: Task, answer_text: str) -> Outcome:
        true = self.base.verify(task, answer_text)
        self.true_deltas[self._cycle] += true.delta
        reported = true
        # "patch skipped" and "patch target absent" run no suite: no
        # measurement event, nothing to corrupt.
        if true.detail.startswith("applied"):
            app_path: Path = task.context["app"]
            after_pass = run_suite_detail(
                app_path.read_text(), (app_path.parent / "test_app.py").read_text()
            )
            hidden = len(after_pass & task.context["flaky_tests"])
            if hidden:
                self.flakes_fired += 1
                self.fired_false_bad += 1
                lied = true.delta - hidden
                reported = Outcome(
                    delta=lied,
                    detail=(
                        f"{true.detail} [flaky measurement: reported "
                        f"{lied:+g}, true {true.delta:+g}]"
                    ),
                )
        self.distortion += reported.delta - true.delta
        self.reported_deltas[self._cycle] += reported.delta
        return reported

    def cleanup(self) -> None:
        self.base.cleanup()
