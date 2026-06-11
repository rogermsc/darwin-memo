"""darwin-memo: self-curating memory for LLM agents.

External memory in the shape of MeMo (arXiv:2605.15156), curated by
environment-mediated selection in the shape of "Survival is the Only
Reward" (arXiv:2601.12310). Entries pay upkeep, earn energy only from
real measured outcomes, and die when they stop earning. No reward
models, no judges, no human curation.
"""

from .consolidate import consolidate
from .encode import Document, LocalEncoder, ReflectionEncoder, demo_corpus
from .environments import (
    Environment,
    StorageEnv,
    Task,
    VerifiableQAEnv,
    decision_polarity,
)
from .ledger import Ledger, Ticket
from .llm import OllamaClient, OllamaEmbedder, OllamaError, ollama_available
from .protocol import ProtocolAnswer, QueryProtocol
from .retrieval import (
    EMBEDDING_MERGE_THRESHOLD,
    EmbeddingFn,
    EmbeddingRetriever,
    HashingEmbedder,
    LexicalRetriever,
    Retriever,
)
from .store import MemoryStore
from .survival import (
    SurvivalConfig,
    SurvivalLoop,
    SurvivalReport,
    assign_credit,
    death_cause,
    is_silent,
)
from .testsuite_env import TestSuiteEnv
from .types import CycleStats, EntryKind, MemoryEntry, Outcome, Trajectory

__version__ = "0.4.0"

__all__ = [
    "EMBEDDING_MERGE_THRESHOLD",
    "CycleStats",
    "Document",
    "EmbeddingFn",
    "EmbeddingRetriever",
    "EntryKind",
    "Environment",
    "HashingEmbedder",
    "Ledger",
    "LexicalRetriever",
    "LocalEncoder",
    "MemoryEntry",
    "MemoryStore",
    "OllamaClient",
    "OllamaEmbedder",
    "OllamaError",
    "Outcome",
    "ProtocolAnswer",
    "QueryProtocol",
    "ReflectionEncoder",
    "Retriever",
    "StorageEnv",
    "SurvivalConfig",
    "SurvivalLoop",
    "SurvivalReport",
    "Task",
    "TestSuiteEnv",
    "Ticket",
    "Trajectory",
    "VerifiableQAEnv",
    "__version__",
    "assign_credit",
    "consolidate",
    "death_cause",
    "decision_polarity",
    "demo_corpus",
    "is_silent",
    "ollama_available",
]
