from __future__ import annotations

import math

from darwin_memo import MemoryEntry, MemoryStore, SurvivalConfig, assign_credit

RULES = ("single_run", "any_pass", "majority_vote", "survival")


def keep(
    reported: list[bool],
    rule: str,
    *,
    credit_gain: float = 0.6,
    spawn: float = 1.0,
    scale: float = 1.0,
) -> bool:
    if not reported:
        return False
    if rule == "single_run":
        return bool(reported[0])
    if rule == "any_pass":
        return any(reported)
    if rule == "majority_vote":
        return sum(reported) >= math.ceil(len(reported) / 2)
    if rule == "survival":
        store = MemoryStore()
        entry = store.add(MemoryEntry(question="c", answer="c", energy=spawn))
        cfg = SurvivalConfig(credit_gain=credit_gain)
        for i, passed in enumerate(reported):
            delta = 1.0 if passed else -1.0
            assign_credit(store, entry.id, [], delta, scale, cfg, i)
        got = store.get(entry.id)
        return got is not None and got.alive
    raise ValueError(f"unknown rule {rule!r}")
