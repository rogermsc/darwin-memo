"""Noisy-measurement environment: the flaky-CI test for forgiveness.

The deterministic headline benchmark honestly reports that
evict_on_negative, a one-line heuristic, ties the energy ledger on
outcomes. The ledger's designed advantage is tolerance of noisy
measurements (bounded per-event credit plus an energy buffer plus
earn-back, so one lying measurement does not execute an entry that was
right ninety-nine times), and a deterministic environment never
exercises it. This module makes measurements lie on purpose,
deterministically, so the noisy suite can test forgiveness instead of
asserting it.

``FlakyStorageEnv`` wraps ``StorageEnv``. The WORLD stays truthful:
files are really created, deletions really free bytes, restores really
cost three times the size. Only the MEASUREMENT lies. Arms decide off
REPORTED deltas; the benchmark scores them on TRUE ones, which is
exactly the position of any system whose CI sometimes lies to it.

Two preconditions make the cross-arm comparison valid, and the unit
tests enforce both:

- The flake field is a property of the world, not of the run. Each task
  gets its marks at generation time from a dedicated RNG stream (never
  the base env's own stream, which also generates the files), keyed by
  (seed, cycle) and consumed in task order. Every arm at the same seed
  and rate therefore faces the same potentially-lying measurements.
  Marks are drawn as ``uniform < rate`` from a rate-independent stream,
  so the flaky sets at two rates are nested (monotone coupling), and
  the same draws are consumed under every noise model, so the field is
  model-independent too. Whether a lie actually FIRES still depends on
  the arm's behavior, because a measurement that never happens cannot
  lie; that conditioning is the semantics of measurement noise, not a
  confound, which is why ``flakes_fired`` is reported per arm next to
  the world-level ``flakes_marked``.
- At rate 0.0 the wrapper adds zero behavior: same tasks, same
  outcomes, same metrics as the bare ``StorageEnv``.

Noise models:

- ``flip``: reported = -true. Symmetric. Good deletions sometimes read
  as disasters AND poisoned deletions sometimes read as wins, so this
  model also prices forgiveness's known cost: tolerance for lying
  measurements is tolerance for guilty entries. Note the magnitude
  asymmetry inherited from StorageEnv's payoff convention: a lie about
  a good deletion reports -size, while a lie about a destroyed
  protected file reports +3*size (a large, tanh-saturated reward).
- ``false_bad``: only positive true deltas flip. The flaky-CI shape: a
  good change sometimes reports a red build, but a genuinely broken
  build does not report green. The clean headline case for the
  forgiveness question.
- ``magnitude``: sign preserved, size lied about: reported =
  true * m with m in [0.25, 4], drawn deterministically per task.
  Sign-driven heuristics (the evict_on_negative family) are immune to
  this model by construction; only credit that reads magnitudes can
  move. Included so the one model where ONLY the ledger can degrade is
  run rather than skipped.

The corrupted detail string names both deltas for the event record.
Nothing in the noisy suite feeds detail strings back into memory
(experience writes are rejected under noise by the runner), and the
tag's vocabulary contains no ``decision_polarity`` markers, so the
truth in the detail cannot leak into selection.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from darwin_memo import Outcome, StorageEnv, Task

NOISE_MODELS = ("flip", "false_bad", "magnitude")


class FlakyStorageEnv:
    """StorageEnv whose measurements lie at a seeded, fixed rate."""

    def __init__(
        self,
        root: str | Path | None = None,
        files_per_cycle: int = 12,
        seed: int = 7,
        flake_rate: float = 0.1,
        noise_model: str = "flip",
    ) -> None:
        if noise_model not in NOISE_MODELS:
            raise ValueError(
                f"unknown noise_model {noise_model!r}; expected one of {NOISE_MODELS}"
            )
        if not 0.0 <= flake_rate <= 1.0:
            raise ValueError(f"flake_rate must be in [0, 1], got {flake_rate}")
        self.base = StorageEnv(root=root, files_per_cycle=files_per_cycle, seed=seed)
        self.resource_scale = self.base.resource_scale
        self.seed = seed
        self.flake_rate = flake_rate
        self.noise_model = noise_model
        self.true_deltas: list[float] = []  # index = cycle, sums TRUE movement
        self.reported_deltas: list[float] = []
        self.flakes_marked = 0  # world property: marks drawn true
        self.flakes_fired = 0  # arm exposure: lies that corrupted a measurement
        self.fired_false_bad = 0  # positive truth reported worse
        self.fired_false_good = 0  # negative truth reported better
        self.distortion = 0.0  # sum(reported - true), the accounting identity
        self._cycle = -1

    def tasks(self, cycle: int) -> list[Task]:
        tasks = self.base.tasks(cycle)
        # Dedicated stream, independent of the base env's file generation
        # and of both the rate and the noise model. Two draws per task,
        # always consumed: u1 marks the flake (u1 < rate), u2 seeds the
        # magnitude lie. Identical fields across rates (nested), models,
        # and arms at a fixed seed.
        rng = random.Random(self.seed * 1_000_003 + cycle * 7_919 + 13)
        for task in tasks:
            u1, u2 = rng.random(), rng.random()
            task.context["flaky"] = u1 < self.flake_rate
            # Log-uniform in [0.25, 4]: lies shrink and exaggerate evenly.
            task.context["flake_magnitude"] = math.exp((2 * u2 - 1) * math.log(4.0))
            if task.context["flaky"]:
                self.flakes_marked += 1
        self._cycle = cycle
        while len(self.true_deltas) <= cycle:
            self.true_deltas.append(0.0)
            self.reported_deltas.append(0.0)
        return tasks

    def verify(self, task: Task, answer_text: str) -> Outcome:
        true = self.base.verify(task, answer_text)
        self.true_deltas[self._cycle] += true.delta
        reported = true
        if task.context.get("flaky") and true.delta != 0:
            lied = self._lie(true.delta, task.context["flake_magnitude"])
            if lied is not None:
                self.flakes_fired += 1
                if lied < true.delta:
                    self.fired_false_bad += 1
                else:
                    self.fired_false_good += 1
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

    def _lie(self, true_delta: float, magnitude: float) -> float | None:
        """The reported delta for a marked, measured task; None = no lie."""
        if self.noise_model == "flip":
            return -true_delta
        if self.noise_model == "false_bad":
            return -true_delta if true_delta > 0 else None
        return true_delta * magnitude  # "magnitude": sign kept, size lied

    def cleanup(self) -> None:
        self.base.cleanup()
