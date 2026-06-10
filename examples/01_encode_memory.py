"""Step 1 of the pipeline: encode a corpus into reflection-QA memory.

Runs offline with zero API keys. Set ANTHROPIC_API_KEY to encode with
Claude instead (pip install "darwin-memo[anthropic]").

    python examples/01_encode_memory.py
"""

from collections import Counter

from common import build_store

store = build_store()

print(f"\nEncoded {len(store)} memory entries\n")
kinds = Counter(e.kind.value for e in store.alive())
for kind, count in kinds.most_common():
    print(f"  {kind:>12}: {count}")

print("\nSample entries:")
for entry in store.alive()[:6]:
    print(f"\n  [{entry.kind.value}] {entry.question}")
    print(f"      -> {entry.answer[:100]}")
    print(f"      sources: {', '.join(entry.sources)}")

store.save("memory.json")
print("\nSaved population to memory.json")
