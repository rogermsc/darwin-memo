from darwin_memo import (
    EmbeddingRetriever,
    HashingEmbedder,
    LexicalRetriever,
    MemoryEntry,
    MemoryStore,
    Retriever,
)


def seeded_store(retriever: Retriever | None = None) -> MemoryStore:
    store = MemoryStore(retriever=retriever)
    store.add(
        MemoryEntry(
            question="What about database files?",
            answer="Database files under data/ must be retained.",
        )
    )
    store.add(
        MemoryEntry(
            question="What about log files?",
            answer="Old log files may be deleted after seven days.",
        )
    )
    return store


def test_hashing_embedder_is_deterministic_and_normalized():
    embedder = HashingEmbedder(dims=64)
    a = embedder("database files under data/")
    b = embedder("database files under data/")
    assert a == b
    norm = sum(x * x for x in a) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_hashing_embedder_frozen_vector():
    """Cross-process determinism: crc32, not the salted builtin hash."""
    vec = HashingEmbedder(dims=8)("database")
    expected = [
        -0.1690308509457033,
        -0.3380617018914066,
        -0.1690308509457033,
        -0.3380617018914066,
        0.6761234037828132,
        -0.3380617018914066,
        -0.1690308509457033,
        -0.3380617018914066,
    ]
    assert all(abs(a - b) < 1e-9 for a, b in zip(vec, expected, strict=True))


def test_embedding_retriever_handles_typos():
    """Hashing n-grams retrieve through a typo that defeats lexical match."""
    lexical = seeded_store()
    hashing = seeded_store(EmbeddingRetriever(HashingEmbedder(), min_similarity=0.2))

    query = "Is it safe to delete the databse files?"  # typo: databse
    lexical_hits = {e.answer for e, _ in lexical.retrieve(query)}
    hashing_hits = [e for e, _ in hashing.retrieve(query)]

    assert hashing_hits, "hashing embedder should survive the typo"
    assert "database" in hashing_hits[0].answer.lower()
    assert not any("database" in a.lower() for a in lexical_hits)


def test_embedding_retriever_silence_floor():
    store = seeded_store(EmbeddingRetriever(HashingEmbedder(), min_similarity=0.35))
    assert store.retrieve("what is the capital of France?") == []


def test_vectors_persist_and_skip_reembedding(tmp_path):
    calls = {"n": 0}

    def counting_embed(text: str) -> list[float]:
        calls["n"] += 1
        return HashingEmbedder(dims=32)(text)

    store = seeded_store(EmbeddingRetriever(counting_embed, min_similarity=0.1))
    store.retrieve("database files")  # embeds 2 entries + 1 query
    embed_calls_before_save = calls["n"]
    assert embed_calls_before_save == 3

    path = tmp_path / "memory.json"
    store.save(path)

    loaded = MemoryStore.load(
        path, retriever=EmbeddingRetriever(counting_embed, min_similarity=0.1)
    )
    loaded.retrieve("database files")
    # Only the query embeds; entry vectors came from the file.
    assert calls["n"] == embed_calls_before_save + 1


def test_lexical_retriever_state_roundtrip_is_empty():
    retriever = LexicalRetriever()
    assert retriever.dump_state() == {}
    retriever.load_state({})  # must not raise


def test_buried_entries_drop_from_retriever_cache():
    retriever = EmbeddingRetriever(HashingEmbedder(), min_similarity=0.1)
    store = seeded_store(retriever)
    entry = store.alive()[0]
    store.retrieve("database files")
    assert entry.id in retriever._vectors
    store.bury(entry.id)
    assert entry.id not in retriever._vectors


def test_one_unembeddable_entry_does_not_blind_every_query():
    """_entry_vector raises on an empty vector (correct: never cache a
    degenerate one), but rank must skip that entry, not let it take down
    retrieval for the whole store. Mutation: drop the try/except and this
    raises instead of returning the good entry."""
    from darwin_memo import EmbeddingRetriever, MemoryEntry

    good = MemoryEntry(question="cache files", answer="caches are disposable")
    bad = MemoryEntry(question="", answer="")

    def embed(text: str) -> list[float]:
        return [] if not text.strip() else [float(len(text)), 1.0]

    r = EmbeddingRetriever(embed, min_similarity=0.0)
    ranked = r.rank("cache", [good, bad])
    assert [e.id for e, _ in ranked] == [good.id], "good entry survives, bad goes dark"


def test_unembeddable_entry_does_not_crash_consolidation_or_warm():
    """The rank() guard is not enough: similarity() (consolidation) and warm()
    (pre-embed) call _entry_vector too. Mutation: drop the try/except in either
    and one degenerate entry aborts a whole consolidation pass or warm sweep."""
    from darwin_memo import EmbeddingRetriever, MemoryEntry

    good = MemoryEntry(question="cache files", answer="caches are disposable")
    bad = MemoryEntry(question="", answer="")

    def embed(text: str) -> list[float]:
        return [] if not text.strip() else [float(len(text)), 1.0]

    r = EmbeddingRetriever(embed, min_similarity=0.0)
    assert r.similarity(good, bad) == 0.0, (
        "un-embeddable pair is dissimilar, not a crash"
    )
    EmbeddingRetriever(embed, min_similarity=0.0).warm([good, bad])  # must not raise
