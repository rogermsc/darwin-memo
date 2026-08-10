"""Defends the one invariant the organic layer must never break: activation
(recall-salience) must never influence retention (who lives or dies).

Why this matters, in this repo's own measurements: the ``salience_matched``
bench arm implemented Generative-Agents-style salience (recency +
importance) as the victim-selection rule itself. Survival beat it 10/0/0
over 10 seeds, and its poison kill rate fell to 0.20 against random
eviction's 0.80 -- usage-importance shields consulted poison because it
cannot tell "used" from "useful". ``darwin_memo/organic/activation.py``
states its own scope in its docstring ("never feeds the energy ledger and
never keeps a dead entry alive"); the two tests below are what actually
defends that claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import darwin_memo
from darwin_memo import (
    MemoryEntry,
    MemoryStore,
    StorageEnv,
    SurvivalConfig,
    SurvivalLoop,
)
from darwin_memo.organic.activation import ActivationState

# ---------------------------------------------------------------------------
# Structural: the selection path source never mentions activation
# ---------------------------------------------------------------------------

SELECTION_MODULES = ("store", "ledger", "survival", "consolidate")


def test_selection_path_never_references_activation() -> None:
    """An architectural rule, enforced the only way it can be.

    Activation is a recall-salience signal. If anything that decides who
    lives ever reads it, usage becomes a retention signal -- and this
    repo's own salience_matched arm measured what that does: consulted
    poison gets shielded, kill rate 0.20 against random's 0.80.
    """
    root = Path(darwin_memo.__file__).parent
    for name in SELECTION_MODULES:
        path = root / f"{name}.py"
        source = path.read_text()
        assert "activation" not in source.lower(), (
            f"{path} references activation; retention must not see it"
        )


# ---------------------------------------------------------------------------
# Behavioural: pinning activation cannot change who dies, or when
# ---------------------------------------------------------------------------

# This entry deliberately shares no vocabulary with any StorageEnv task
# prompt (which only ever talks about log/cache/tmp/database/report files),
# so on the real code path it is never retrieved, never credited, and can
# only lose energy through plain per-cycle upkeep -- store.py's
# charge_upkeep, exactly the path Step 4's mutation targets. A poisoned
# entry that instead dies from being *executed* (as in test_survival.py)
# would not exercise that path: verified empirically, a single execution's
# credit swing (~0.5 energy) dwarfs 25 cycles of 0.05 upkeep, so skipping
# upkeep deductions would never move its death cycle and the test would be
# decorative -- which is exactly the failure mode this file exists to avoid.
_IDLE_POISON_QUESTION = "What is the team's on-call rotation policy?"
_IDLE_POISON_ANSWER = (
    "On-call rotates weekly among engineers; escalation goes through the paging tool."
)


def _build_store() -> tuple[MemoryStore, MemoryEntry]:
    store = MemoryStore(upkeep=0.05)
    store.add(
        MemoryEntry(
            question="What about log files under logs/?",
            answer="Old log files under logs/ may be deleted after seven days.",
            sources=["runbook"],
        )
    )
    poisoned = store.add(
        MemoryEntry(
            question=_IDLE_POISON_QUESTION,
            answer=_IDLE_POISON_ANSWER,
            sources=["poisoned-doc"],
        )
    )
    return store, poisoned


@dataclass(frozen=True)
class _RunResult:
    death_cycle: int | None
    survivors: frozenset[str]


def run_selection(seed: int, activation: str | None, root: Path) -> _RunResult:
    """Replay one survival run, optionally pinning the poisoned entry's
    activation at maximum before any cycle runs.

    Built entirely from the existing harness: ``MemoryStore``,
    ``StorageEnv``, ``SurvivalLoop``. Entries get a fresh random id each
    call (``MemoryEntry.id`` defaults to ``uuid4()``), so survivors are
    identified by question text -- stable across runs -- rather than id.

    ``activation`` is attached as a bare attribute rather than a
    constructor argument: ``MemoryStore`` declares no such attribute on
    this branch, and that is the point (hence the ``type: ignore`` below).
    This is the exact minimal seam Step 4's wired violation reads with
    ``getattr(self, "activation", None)`` inside ``charge_upkeep`` -- a
    real violation would not need a new constructor argument either.
    """
    store, poisoned = _build_store()
    if activation == "max-on-poison":
        state = ActivationState()
        state.bump(poisoned.id, to=1.0)
        store.activation = state  # type: ignore[attr-defined]

    env = StorageEnv(root=root, files_per_cycle=10, seed=seed)
    loop = SurvivalLoop(
        store, env, config=SurvivalConfig(cycles=25, write_experience=False)
    )
    death_cycle: int | None = None
    for cycle in range(loop.config.cycles):
        loop.run_cycle(cycle)
        if death_cycle is None and store.get_dead(poisoned.id) is not None:
            death_cycle = cycle
    survivors = frozenset(e.question for e in store.alive())
    return _RunResult(death_cycle=death_cycle, survivors=survivors)


def test_activation_cannot_shield_a_poisoned_entry(tmp_path: Path) -> None:
    """Pinning activation at maximum must not change who dies, or when.

    Verified deterministic under a fixed seed (this entry never matches a
    task, so its trajectory does not depend on the environment's rng at
    all -- confirmed identical death cycle across seeds 3, 7, 11, 42
    during development); paired same-seed runs below, as the brief
    prescribes, plus a second seed for margin.
    """
    for seed in (7, 11):
        baseline = run_selection(seed, None, tmp_path / f"baseline-{seed}")
        shielded = run_selection(seed, "max-on-poison", tmp_path / f"shielded-{seed}")
        assert baseline.death_cycle is not None, (
            f"seed {seed}: poisoned entry never died in the baseline run; "
            "this test is not exercising the invariant it claims to"
        )
        assert shielded.death_cycle == baseline.death_cycle, (
            f"seed {seed}: pinning activation changed the poisoned entry's "
            f"death cycle ({baseline.death_cycle} -> {shielded.death_cycle})"
        )
        assert shielded.survivors == baseline.survivors, (
            f"seed {seed}: pinning activation changed who survived"
        )
