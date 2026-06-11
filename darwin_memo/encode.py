"""Reflection-QA encoding, following the MeMo data synthesis pipeline.

MeMo turns a corpus into a "reflection QA dataset" through five steps,
then trains a small memory model on it. This module implements the same
five steps and writes the result into a :class:`MemoryStore` instead:

1. Fact extraction: explicit and inferred facts per document.
2. Consolidation: related facts in shared context merge into
   multi-fact entries.
3. Verification: every QA pair must be self-contained, understandable
   with no access to the source document.
4. Entity surfacing: attribute and relationship QAs in both directions,
   the paper's counter to the reversal curse.
5. Cross-document synthesis: converging clues that only make sense when
   two or more documents are combined.

With an :class:`~darwin_memo.llm.LLMClient` the steps are model-driven.
Without one, ``LocalEncoder`` does a rule-based approximation so the
whole package runs offline.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from .llm import LLMClient, parse_json_array
from .types import EntryKind, MemoryEntry

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_ENTITY_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*)\b")


@dataclass
class Document:
    doc_id: str
    text: str


class LocalEncoder:
    """Rule-based reflection encoding. No network, no models.

    Deliberately simple: declarative sentences become explicit-fact QAs,
    capitalized terms become entity QAs in both directions, and entities
    shared across documents become cross-document QAs. It exists so that
    the survival mechanics can be exercised end to end offline. For real
    corpora, use :class:`ReflectionEncoder` with an LLM client.
    """

    def encode(self, documents: list[Document]) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        seen_qa: set[tuple[str, str]] = set()
        entity_docs: dict[str, set[str]] = {}
        entity_sentences: dict[str, list[str]] = {}
        entity_mid_sentence: set[str] = set()

        for doc in documents:
            for sentence in self._sentences(doc.text):
                # Step 1 + 3: each declarative sentence is an explicit fact,
                # kept self-contained by storing the full sentence as answer.
                # Identical QA pairs dedupe at encode time; repeated text in
                # a document must not multiply the population.
                subject = self._subject_of(sentence)
                question = f"What is known about {subject}?"
                if (question, sentence) not in seen_qa:
                    seen_qa.add((question, sentence))
                    entries.append(
                        MemoryEntry(
                            question=question,
                            answer=sentence,
                            kind=EntryKind.EXPLICIT,
                            sources=[doc.doc_id],
                        )
                    )
                # Step 4: surface entities, both directions.
                for entity, mid_sentence in self._entities(sentence):
                    entity_docs.setdefault(entity, set()).add(doc.doc_id)
                    entity_sentences.setdefault(entity, []).append(sentence)
                    if mid_sentence:
                        entity_mid_sentence.add(entity)

        # Sentence-initial single words are usually capitalization artifacts
        # ("Old log files..."), so an entity must be multi-word or show up
        # mid-sentence at least once across the corpus to count.
        valid = {e for e in entity_sentences if " " in e or e in entity_mid_sentence}
        entity_docs = {e: d for e, d in entity_docs.items() if e in valid}
        entity_sentences = {e: s for e, s in entity_sentences.items() if e in valid}

        for entity, sentences in entity_sentences.items():
            joined = " ".join(dict.fromkeys(sentences[:2]))
            entries.append(
                MemoryEntry(
                    question=f"What do we know about {entity}?",
                    answer=joined,
                    kind=EntryKind.ENTITY,
                    sources=sorted(entity_docs[entity]),
                )
            )

        # Step 5: converging clues, entities mentioned in several documents.
        for entity, docs in entity_docs.items():
            if len(docs) >= 2:
                deduped = list(dict.fromkeys(entity_sentences[entity]))
                entries.append(
                    MemoryEntry(
                        question=(
                            "Combining all sources, what is the full "
                            f"picture on {entity}?"
                        ),
                        answer=" ".join(deduped[:3]),
                        kind=EntryKind.CROSS_DOC,
                        sources=sorted(docs),
                    )
                )
        return entries

    @staticmethod
    def _sentences(text: str) -> list[str]:
        return [
            s.strip()
            for s in _SENTENCE_RE.split(text.replace("\n", " "))
            if len(s.split()) >= 4
        ]

    @staticmethod
    def _subject_of(sentence: str) -> str:
        words = sentence.rstrip(".!?").split()
        return " ".join(words[:6]).lower()

    @staticmethod
    def _entities(sentence: str) -> list[tuple[str, bool]]:
        words = sentence.split()
        first_word = words[0] if words else ""
        results: list[tuple[str, bool]] = []
        for candidate in _ENTITY_RE.findall(sentence):
            mid_sentence = not candidate.startswith(first_word)
            # "The Platform Team" and "Platform Team" are the same entity.
            normalized = re.sub(r"^(?:The|A|An)\s+", "", candidate)
            if normalized:
                results.append((normalized, mid_sentence))
        return results


_EXTRACTION_PROMPT = """\
You are building a reflection QA dataset from a document, following the MeMo
pipeline (fact extraction, consolidation, verification, entity surfacing).

Document {doc_id}:
---
{text}
---

Produce QA pairs that satisfy ALL of these rules:
- Cover every explicit fact, plus facts that are clearly inferable.
- Merge facts that share context into single multi-fact QAs.
- Every question must be self-contained: answerable with zero access to the
  document, no pronouns without referents, no "according to the text".
- For each named entity, add attribute and relationship QAs in BOTH
  directions (entity to attribute, attribute to entity).

Return a JSON array of objects:
{{"question": str, "answer": str, "kind": "explicit"|"inferred"|"entity"}}
"""

_CROSS_DOC_PROMPT = """\
You are doing cross-document synthesis for a reflection QA dataset.
Find converging clues: complementary facts about the same entity, and
parallel properties shared across entities. Only produce QAs that genuinely
require combining the documents.

{documents}

Return a JSON array of objects: {{"question": str, "answer": str}}
Every question must be self-contained. Return [] if nothing converges.
"""


class ReflectionEncoder:
    """Model-driven reflection encoding, steps 1 through 5 of MeMo.

    Calls are independent per document and per document pair, so they run
    on a thread pool. The output order is deterministic regardless.
    """

    def __init__(self, client: LLMClient, max_workers: int = 4) -> None:
        self.client = client
        self.max_workers = max_workers

    def encode(self, documents: list[Document]) -> list[MemoryEntry]:
        def encode_document(doc: Document) -> list[MemoryEntry]:
            raw = self.client.complete(
                _EXTRACTION_PROMPT.format(doc_id=doc.doc_id, text=doc.text)
            )
            return [
                _entry_from_item(item, sources=[doc.doc_id])
                for item in parse_json_array(raw)
            ]

        def encode_pair(pair: tuple[Document, Document]) -> list[MemoryEntry]:
            doc_a, doc_b = pair
            block = (
                f"Document {doc_a.doc_id}:\n{doc_a.text}\n\n"
                f"Document {doc_b.doc_id}:\n{doc_b.text}"
            )
            raw = self.client.complete(_CROSS_DOC_PROMPT.format(documents=block))
            return [
                _entry_from_item(
                    item, sources=[doc_a.doc_id, doc_b.doc_id], kind=EntryKind.CROSS_DOC
                )
                for item in parse_json_array(raw)
            ]

        entries: list[MemoryEntry] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for batch in pool.map(encode_document, documents):
                entries.extend(batch)
            for batch in pool.map(encode_pair, combinations(documents, 2)):
                entries.extend(batch)

        return [e for e in entries if e.question and e.answer]


def _entry_from_item(
    item: dict[str, Any], sources: list[str], kind: EntryKind | None = None
) -> MemoryEntry:
    """Coerce one parsed JSON object from the model into a MemoryEntry."""
    if kind is None:
        try:
            kind = EntryKind(item.get("kind", "explicit"))
        except ValueError:
            kind = EntryKind.EXPLICIT
    return MemoryEntry(
        question=str(item.get("question", "")).strip(),
        answer=str(item.get("answer", "")).strip(),
        kind=kind,
        sources=sources,
    )
