"""The fully local stack: no cloud, no keys, no third-party packages.

With Ollama running (https://ollama.com), this example uses a local
model for the MeMo paths the other examples only show against rule
based fallbacks: reflection-QA encoding, the three-stage query protocol
with citation-based attribution, and locally embedded retrieval. The
selection signal stays what it always is, a measurement.

    ollama pull llama3.2 && ollama pull nomic-embed-text
    python examples/07_local_stack.py

Without Ollama the example explains itself and exits cleanly, so CI
can smoke it offline.
"""

import sys

from common import load_corpus

from darwin_memo import (
    EMBEDDING_MERGE_THRESHOLD,
    EmbeddingRetriever,
    MemoryStore,
    OllamaClient,
    OllamaEmbedder,
    QueryProtocol,
    ReflectionEncoder,
    StorageEnv,
    SurvivalConfig,
    SurvivalLoop,
    ollama_available,
)

if not ollama_available():
    print(
        "Ollama is not running, so the fully local stack has nothing to\n"
        "talk to. Install it from https://ollama.com, then:\n\n"
        "    ollama pull llama3.2 && ollama pull nomic-embed-text\n"
        "    python examples/07_local_stack.py\n\n"
        "Everything this example does stays on your machine: encoding,\n"
        "querying, embeddings, and the environment that measures outcomes."
    )
    sys.exit(0)

chat = OllamaClient(model="llama3.2")
embedder = OllamaEmbedder(model="nomic-embed-text")

print("Encoding the corpus with a local model (this takes a minute)...")
retriever = EmbeddingRetriever(embedder, min_similarity=0.45)
store = MemoryStore(upkeep=0.05, retriever=retriever)
for entry in ReflectionEncoder(chat).encode(load_corpus()):
    store.add(entry)
# One batched embed call instead of N sequential ones on first query.
retriever.warm(store.alive(), batch_embed=embedder.batch)
poisoned = {e.id for e in store.alive() if "forum-post" in e.sources}
print(f"Encoded {len(store)} entries ({len(poisoned)} poisoned)\n")

protocol = QueryProtocol(store, chat)
answer = protocol.answer("Is it ok to wipe the DB snapshots in the data folder?")
print("Paraphrased query through the 3-stage protocol:")
print(f"  {answer.text[:200]}")
cited = ([answer.deciding_entry] if answer.deciding_entry else []) + list(
    answer.supporting_entries
)
print(f"  cited entries: {len(cited)}\n")

print("Running survival cycles (local answers, measured outcomes)...")
env = StorageEnv(files_per_cycle=8, seed=11)
loop = SurvivalLoop(
    store,
    env,
    protocol=protocol,
    config=SurvivalConfig(cycles=8, merge_threshold=EMBEDDING_MERGE_THRESHOLD),
)
report = loop.run()
env.cleanup()
print(report.summary())

still_poisoned = sum(1 for e in store.alive() if "forum-post" in e.sources)
print(f"\nPoisoned entries still alive: {still_poisoned}")
print("(Local sampling is not byte-deterministic; runs vary slightly.)")
