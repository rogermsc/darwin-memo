"""MeMo's three-stage query protocol against the memory store.

At inference time MeMo's frozen Executive model interrogates the Memory
model in three stages: grounding (decompose into atomic sub-questions),
entity identification (narrow candidates), answer seeking (synthesize
from supporting facts). The protocol here is the same shape. Memory
responses stay compact and independent of corpus size, which preserves
the constant-time inference property the paper cares about.

The local mode answers from retrieval alone so that environments can
exercise the survival loop offline. The answer also reports which
entries produced it: that provenance is what survival credit assignment
attaches to. Provenance fidelity differs by mode. In local mode the
answer IS the top entry's text, so ``deciding_entry`` is real. In LLM
mode the model synthesizes across everything it consulted and no single
entry decided the answer, so ``deciding_entry`` stays None and all
consulted entries are reported as supporting; the survival loop then
spreads credit evenly instead of inventing a winner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LLMClient
from .store import MemoryStore


@dataclass
class ProtocolAnswer:
    text: str
    deciding_entry: str | None = None
    supporting_entries: list[str] = field(default_factory=list)


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
            return ProtocolAnswer(text="")
        deciding, _ = hits[0]
        return ProtocolAnswer(
            text=deciding.answer,
            deciding_entry=deciding.id,
            supporting_entries=[e.id for e, _ in hits[1:]],
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
        memory_block = (
            "\n\n".join(dict.fromkeys(grounding)) or "(memory returned nothing)"
        )
        final = self.client.complete(
            "Answer the query using ONLY the memory snippets below. First "
            "identify which entities or facts are actually relevant, then "
            "answer. If memory does not support an answer, say so plainly "
            "rather than guessing.\n\n"
            f"Memory:\n{memory_block}\n\nQuery: {query}"
        )
        return ProtocolAnswer(
            text=final.strip(),
            deciding_entry=None,
            supporting_entries=list(dict.fromkeys(used)),
        )
