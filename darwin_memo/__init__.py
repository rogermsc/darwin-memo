"""darwin-memo: self-curating memory for LLM agents.

External memory in the shape of MeMo (arXiv:2605.15156), curated by
environment-mediated selection in the shape of "Survival is the Only
Reward" (arXiv:2601.12310). Entries pay upkeep, earn energy only from
real measured outcomes, and die when they stop earning. No reward
models, no judges, no human curation.
"""

from .consolidate import DEFAULT_MERGE_THRESHOLD, consolidate
from .encode import Document, LocalEncoder, ReflectionEncoder, demo_corpus
from .environments import (
    Environment,
    StorageEnv,
    Task,
    VerifiableQAEnv,
    decision_polarity,
)
from .evm import DEFAULT_BASE_RPC, EvmRpc, EvmRpcError, EvmSettler
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
from .store import MemoryStore, StoreLockedError
from .survival import (
    SurvivalConfig,
    SurvivalLoop,
    SurvivalReport,
    advance_lifecycle,
    assign_credit,
    death_cause,
    is_silent,
)
from .temporal import (
    CONFLICT_HEADER,
    age_annotation,
    conflict_clusters,
    newest_first,
    recency_weight,
)
from .testsuite_env import TestSuiteEnv
from .types import CycleStats, EntryKind, MemoryEntry, Outcome, Trajectory

__version__ = "0.6.0"

__all__ = [
    "CONFLICT_HEADER",
    "DEFAULT_BASE_RPC",
    "DEFAULT_MERGE_THRESHOLD",
    "EMBEDDING_MERGE_THRESHOLD",
    "CycleStats",
    "Document",
    "EmbeddingFn",
    "EmbeddingRetriever",
    "EntryKind",
    "Environment",
    "EvmRpc",
    "EvmRpcError",
    "EvmSettler",
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
    "StoreLockedError",
    "SurvivalConfig",
    "SurvivalLoop",
    "SurvivalReport",
    "Task",
    "TestSuiteEnv",
    "Ticket",
    "Trajectory",
    "VerifiableQAEnv",
    "__version__",
    "advance_lifecycle",
    "age_annotation",
    "assign_credit",
    "conflict_clusters",
    "consolidate",
    "death_cause",
    "decision_polarity",
    "demo_corpus",
    "is_silent",
    "newest_first",
    "ollama_available",
    "recency_weight",
]
