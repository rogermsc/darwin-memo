"""Core data types shared across the package."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EntryKind(str, Enum):
    """How a memory entry came to exist.

    The first five kinds mirror the MeMo reflection-QA synthesis steps.
    EXPERIENCE entries are written from successful trajectories, the
    memory-layer analog of the survival paper's fine-tuning on surviving
    behaviors. CONSOLIDATED entries are produced by Negative-Space
    consolidation merges.
    """

    EXPLICIT = "explicit"
    INFERRED = "inferred"
    ENTITY = "entity"
    CROSS_DOC = "cross_doc"
    EXPERIENCE = "experience"
    CONSOLIDATED = "consolidated"


@dataclass
class MemoryEntry:
    """A single unit of memory, stored as a self-contained QA pair.

    Energy is the survival currency: every cycle charges upkeep, and the
    only way to earn energy back is to contribute to a task whose outcome
    persists in the environment. There is no quality score and no judge.
    """

    question: str
    answer: str
    kind: EntryKind = EntryKind.EXPLICIT
    sources: list[str] = field(default_factory=list)
    energy: float = 1.0
    born_cycle: int = 0
    last_used_cycle: int = -1
    uses: int = 0
    lineage: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def alive(self) -> bool:
        return self.energy > 1e-9

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["kind"] = self.kind.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryEntry":
        d = dict(d)
        d["kind"] = EntryKind(d["kind"])
        return cls(**d)


@dataclass
class Outcome:
    """What the environment reports after a task is acted on.

    ``delta`` is a change in a conserved, externally measurable resource
    (bytes freed, tests passing, budget remaining). It is the outcome
    itself, never a model's opinion of the outcome. This is the survival
    paper's central design constraint and the reason proxy optimization
    and reward hacking have nothing to attach to.
    """

    delta: float
    detail: str = ""


@dataclass
class Trajectory:
    """One task attempt: which entries were consulted and what happened."""

    cycle: int
    task: str
    answer: str
    deciding_entry: str | None
    supporting_entries: list[str]
    outcome: Outcome


@dataclass
class CycleStats:
    """Population accounting for one survival cycle."""

    cycle: int
    population: int
    births: int
    deaths: int
    merges: int
    total_energy: float
    resource_delta: float
    dead_ids: list[str] = field(default_factory=list)
