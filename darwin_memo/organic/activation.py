"""Activation: a fast recall-salience signal + lossless gist<->detail surfacing.

Organic-only and in-memory: the darwin-memo core is untouched. Recall (bump) and
decay are explicit calls the consumer wires, exactly like the survival loop.
Activation gates SURFACING only; it never feeds the energy ledger and never
keeps a dead entry alive. Surfacing is lossless: the MemoryEntry is never
mutated; a cold memory shows only its gist (question), a hot one its full detail.
"""

from __future__ import annotations

from darwin_memo import MemoryEntry

BUMP_TO = 1.0
DECAY_FACTOR = 0.5
SURFACE_THRESHOLD = 0.5
_PRUNE_EPSILON = 1e-3


class ActivationState:
    """In-memory id -> activation in [0, 1]. Recall raises it; idle decays it."""

    def __init__(self) -> None:
        self._levels: dict[str, float] = {}

    def bump(self, entry_id: str, to: float = BUMP_TO) -> None:
        """Recall: raise the entry's activation to ``to`` (never lowers it)."""
        self._levels[entry_id] = max(self._levels.get(entry_id, 0.0), to)

    def decay(self, factor: float = DECAY_FACTOR) -> None:
        """One idle cycle: scale every activation by ``factor``; prune ~0."""
        for entry_id in list(self._levels):
            value = self._levels[entry_id] * factor
            if value < _PRUNE_EPSILON:
                del self._levels[entry_id]
            else:
                self._levels[entry_id] = value

    def level(self, entry_id: str) -> float:
        return self._levels.get(entry_id, 0.0)


def detail(entry: MemoryEntry) -> str:
    """The full retained detail of a memory (the explicit 'remind me' surface)."""
    text = f"{entry.question} {entry.answer}"
    if entry.sources:
        text += f" (sources: {', '.join(entry.sources)})"
    return text


def surface(
    entry: MemoryEntry, state: ActivationState, threshold: float = SURFACE_THRESHOLD
) -> str:
    """Gist when the memory is cold (activation < threshold), else full detail.

    Lossless: reads only; never mutates ``entry`` or ``state``.
    """
    if state.level(entry.id) < threshold:
        return entry.question
    return detail(entry)
