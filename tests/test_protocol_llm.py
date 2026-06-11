"""LLM-mode protocol: citation-based attribution with a scripted client."""

from darwin_memo import MemoryEntry, MemoryStore, QueryProtocol
from darwin_memo.protocol import _split_citations


class ScriptedClient:
    """Returns canned completions in order."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str, system: str = "") -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def seeded_store() -> MemoryStore:
    store = MemoryStore()
    store.add(
        MemoryEntry(
            question="What about database files?",
            answer="Database files must be retained.",
        )
    )
    store.add(
        MemoryEntry(
            question="What about log files?",
            answer="Old log files may be deleted after seven days.",
        )
    )
    return store


def test_citations_carry_attribution():
    store = seeded_store()
    client = ScriptedClient(
        [
            "What is the policy for database files?",
            "Database files must be retained.\nSOURCES: [1]",
        ]
    )
    protocol = QueryProtocol(store, client)

    answer = protocol.answer("Can I delete the database files?")

    assert "SOURCES" not in answer.text
    assert answer.deciding_entry is not None, "single citation becomes the decider"
    cited = store.get(answer.deciding_entry)
    assert cited is not None
    assert "database" in cited.question.lower()
    # The snippet block was numbered.
    assert "[1]" in client.prompts[-1]


def test_multiple_citations_become_supporting():
    store = seeded_store()
    client = ScriptedClient(
        [
            "database policy\nlog policy",
            "Retain databases, delete old logs.\nSOURCES: [1] [2]",
        ]
    )
    answer = QueryProtocol(store, client).answer("database and log policy?")
    assert answer.deciding_entry is None
    assert len(answer.supporting_entries) == 2


def test_unparseable_citations_fall_back_to_even_spread():
    store = seeded_store()
    client = ScriptedClient(
        [
            "database policy",
            "Databases must be retained.",  # no SOURCES line at all
        ]
    )
    answer = QueryProtocol(store, client).answer("database policy?")
    assert answer.deciding_entry is None
    assert answer.supporting_entries, "falls back to everything consulted"


def test_split_citations_handles_noise():
    text, cited, none = _split_citations("Answer.\nSOURCES: none", ["a", "b"])
    assert text == "Answer." and cited == [] and none is True
    text, cited, none = _split_citations("Answer.\nsources: [2] [2] [9]", ["a", "b"])
    assert cited == ["b"], "dedupes and ignores out-of-range numbers"
    assert none is False


def test_split_citations_takes_the_last_sources_line():
    """The contract says SOURCES ends the answer; earlier prose that
    happens to start with 'Sources:' (or an echoed instruction) must not
    shadow the real citation line."""
    raw = (
        "Sources: the runbook and the platform notes both cover this.\n"
        "Databases must be retained.\n"
        "SOURCES: [2]"
    )
    text, cited, none = _split_citations(raw, ["a", "b"])
    assert cited == ["b"]
    assert none is False
    assert "SOURCES: [2]" not in text
    assert "Sources: the runbook" in text, "earlier prose stays in the text"


def test_explicit_none_attaches_no_provenance():
    """'SOURCES: none' is the model disclaiming its memory; the fallback
    must not attribute every consulted entry to that answer."""
    store = seeded_store()
    client = ScriptedClient(
        [
            "anything",
            "Memory does not support an answer to that.\nSOURCES: none",
        ]
    )
    answer = QueryProtocol(store, client).answer("capital of France?")
    assert answer.deciding_entry is None
    assert answer.supporting_entries == []


def test_split_citations_strips_think_blocks():
    """Reasoning models must not cite from inside their thinking."""
    raw = (
        "<think>Snippet [1] looks wrong, but [2] settles it.</think>\n"
        "Retain the database files.\nSOURCES: [2]"
    )
    text, cited, none = _split_citations(raw, ["a", "b"])
    assert text == "Retain the database files."
    assert cited == ["b"]
    assert none is False
    assert "<think>" not in text
