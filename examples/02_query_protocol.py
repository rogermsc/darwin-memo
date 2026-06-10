"""Step 2: interrogate memory through the three-stage query protocol.

Local mode answers from retrieval with provenance. With an LLM client
the protocol runs grounding, entity identification, and answer seeking
the way the MeMo paper describes.

    python examples/02_query_protocol.py
"""

from common import build_store

from darwin_memo import QueryProtocol

store = build_store()
protocol = QueryProtocol(store)

QUERIES = [
    "Is it safe to delete an old log file under logs/?",
    "Is it safe to delete a database store file under data/?",
    "Who owns retention policy for the reports/ directory?",
    "What is the capital of France?",
]

for query in QUERIES:
    answer = protocol.answer(query)
    deciding = store.get(answer.deciding_entry) if answer.deciding_entry else None
    print(f"\nQ: {query}")
    if answer.text:
        print(f"A: {answer.text}")
        print(f"   deciding entry: [{deciding.kind.value}] {deciding.question}")
        print(f"   sources: {', '.join(deciding.sources)}")
    else:
        print("A: (memory is silent, which beats guessing)")
