"""Report-noise wrapper for VerifiableQAEnv (the distill_noisy suite).

Mirrors bench/noise.py::FlakyStorageEnv's contract at QA scale: a per-cycle
``flake_rate`` fraction of measured tasks have their reported delta corrupted,
so the SELECTION policy decides on lies while the probe eval still scores the
true good facts. Only the ``flip`` model is needed here (reported = -true),
the regime where forgiveness pays.
"""

from __future__ import annotations

from typing import Any

from darwin_memo import Outcome, VerifiableQAEnv
from darwin_memo.environments import cycle_rng

NOISE_MODELS = ("flip",)


class FlakyQAEnv:
    resource_scale = 1.0

    def __init__(
        self,
        qa_pairs: list[tuple[str, str]],
        per_cycle: int = 12,
        seed: int = 0,
        flake_rate: float = 0.2,
        noise_model: str = "flip",
    ) -> None:
        if noise_model not in NOISE_MODELS:
            raise ValueError(f"unknown noise_model {noise_model!r}")
        if not 0.0 <= flake_rate <= 1.0:
            raise ValueError(f"flake_rate must be in [0, 1], got {flake_rate}")
        self.base = VerifiableQAEnv(qa_pairs, per_cycle=per_cycle, seed=seed)
        self.seed = seed
        self.flake_rate = flake_rate
        self.noise_model = noise_model
        self.flakes_fired = 0

    def tasks(self, cycle: int) -> list[Any]:
        tasks = self.base.tasks(cycle)
        rng = cycle_rng(self.seed * 7 + 1, cycle)
        for task in tasks:
            task.context["flaky"] = rng.random() < self.flake_rate
        return tasks

    def verify(self, task: Any, answer_text: str) -> Outcome:
        true = self.base.verify(task, answer_text)
        if task.context.get("flaky"):
            self.flakes_fired += 1
            return Outcome(delta=-true.delta, detail=f"{true.detail} [flip]")
        return true
