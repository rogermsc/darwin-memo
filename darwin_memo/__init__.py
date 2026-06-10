"""darwin-memo: self-curating memory for LLM agents.

External memory in the shape of MeMo (arXiv:2605.15156), curated by
environment-mediated selection in the shape of "Survival is the Only
Reward" (arXiv:2601.12310). Entries pay upkeep, earn energy only from
real measured outcomes, and die when they stop earning. No reward
models, no judges, no human curation.
"""

from .consolidate import consolidate
from .encode import Document, LocalEncoder, ReflectionEncoder
from .environments import Environment, StorageEnv, Task, VerifiableQAEnv
from .protocol import ProtocolAnswer, QueryProtocol, decision_polarity
from .store import MemoryStore
from .survival import SurvivalConfig, SurvivalLoop, SurvivalReport
from .types import CycleStats, EntryKind, MemoryEntry, Outcome, Trajectory

__version__ = "0.1.0"

__all__ = [
    "consolidate",
    "Document",
    "LocalEncoder",
    "ReflectionEncoder",
    "Environment",
    "StorageEnv",
    "Task",
    "VerifiableQAEnv",
    "ProtocolAnswer",
    "QueryProtocol",
    "decision_polarity",
    "MemoryStore",
    "SurvivalConfig",
    "SurvivalLoop",
    "SurvivalReport",
    "CycleStats",
    "EntryKind",
    "MemoryEntry",
    "Outcome",
    "Trajectory",
    "__version__",
]
