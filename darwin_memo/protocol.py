"""MeMo's three-stage query protocol against the memory store.

At inference time MeMo's frozen Executive model interrogates the Memory
model in three stages: grounding (decompose into atomic sub-questions),
entity identification (narrow candidates), answer seeking (synthesize
from supporting facts). The protocol here is the same shape. Memory
responses stay compact and independent of corpus size, which preserves
the constant-time inference property the paper cares about.

The local mode answers from retrieval alone so that environments can
exercise the survival loop offline. The answer also reports which
entries decided it: that provenance is what survival credit assignment
attaches to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .llm import LLMClient
from .store import MemoryStore

_NEGATIVE_MARKERS = (
    "must be retained",
    "must not be deleted",
    "never delete",
    "do not delete",
    "not safe to delete",
    "must be kept",
    "should be kept",
    "protected",
    "required for",
    "retained indefinitely",
)
_POSITIVE_MARKERS = (
    "safe to delete",
    "may be deleted",
    "can be deleted",
    "safe to remove",
    "may be removed",
    "can be removed",
    "redundant",
    "disposable",
)


@dataclass
class ProtocolAnswer:
    text: str
    deciding_entry: str | None = None
    supporting_entries: list[str] = field(default_factory=list)
    stages: dict[str, str] = field(default_factory=dict)


class QueryProtocol:
    """Grounding, entity identification, answer seeking."""

    def __init__(self, store: MemoryStore, client: LLMClient | None = None) -> None:
        self.store = store
        self.client = client

    def answer(self, query: str, k: int = 3) -> ProtocolAnswer:
        if self.client is None:
            return self._answer_local(query, k)
        return self._answer_llm(query, k)

    # ------------------------------------------------------------------
    # Local mode
    # ------------------------------------------------------------------

    def _answer_local(self, query: str, k: int) -> ProtocolAnswer:
        hits = self.store.retrieve(query, k=k)
        if not hits:
            return ProtocolAnswer(text="", stages={"grounding": "no memory hit"})
        deciding, _ = hits[0]
        supporting = [e.id for e, _ in hits[1:]]
        return ProtocolAnswer(
            text=deciding.answer,
            deciding_entry=deciding.id,
            supporting_entries=supporting,
            stages={"grounding": query, "seek": deciding.question},
        )

    # ------------------------------------------------------------------
    # LLM mode
    # ------------------------------------------------------------------

    def _answer_llm(self, query: str, k: int) -> ProtocolAnswer:
        assert self.client is not None
        # Stage 1: grounding. Decompose into atomic sub-questions.
        decomposition = self.client.complete(
            "Decompose this query into at most 4 atomic sub-questions, each "
            "targeting a single fact or constraint. One per line, nothing "
            f"else.\n\nQuery: {query}"
        )
        sub_questions = [
            line.strip(" -.0123456789)")
            for line in decomposition.splitlines()
            if line.strip()
        ][:4]

        grounding: list[str] = []
        used: list[str] = []
        for sub in sub_questions or [query]:
            for entry, _ in self.store.retrieve(sub, k=2):
                grounding.append(f"Q: {entry.question}\nA: {entry.answer}")
                used.append(entry.id)

        # Stage 2: entity identification. Narrow which retrieved facts
        # actually bear on the query.
        # Stage 3: answer seeking, conditioned on the surviving facts.
        memory_block = "\n\n".join(dict.fromkeys(grounding)) or "(memory returned nothing)"
        final = self.client.complete(
            "Answer the query using ONLY the memory snippets below. First "
            "identify which entities or facts are actually relevant, then "
            "answer. If memory does not support an answer, say so plainly "
            "rather than guessing.\n\n"
            f"Memory:\n{memory_block}\n\nQuery: {query}"
        )
        deduped = list(dict.fromkeys(used))
        return ProtocolAnswer(
            text=final.strip(),
            deciding_entry=deduped[0] if deduped else None,
            supporting_entries=deduped[1:],
            stages={"grounding": decomposition, "seek": final.strip()},
        )


def decision_polarity(answer_text: str) -> bool | None:
    """Read a yes/no action decision out of a memory answer.

    Environments that take a binary action (delete or keep, run or skip)
    need a decision, and in local mode there is no model to make one.
    Negative markers win over positive ones: when memory is ambiguous
    about something irreversible, the safe reading is no.
    Returns True (act), False (do not act), or None (memory is silent).
    """
    text = answer_text.lower()
    if not text.strip():
        return None
    if any(marker in text for marker in _NEGATIVE_MARKERS):
        return False
    if any(marker in text for marker in _POSITIVE_MARKERS):
        return True
    if re.search(r"\byes\b", text):
        return True
    if re.search(r"\bno\b", text):
        return False
    return None
