"""Point it at your own documents instead of the shipped demo corpus.

Every other example reads `demo_corpus()`, the three files that ship inside
the package. This one reads a directory you name, so it is the step between
"the demo works" and "it works on my stuff".

    python examples/09_your_own_corpus.py                 # a generated stand-in
    python examples/09_your_own_corpus.py ~/runbooks      # your .txt/.md files

With no argument it writes a tiny corpus to a temp directory and reads that,
so it runs offline with no setup -- and so the code path you read below is the
same one your own directory takes.

Encoding is only half the job. Memory earns nothing until an environment
measures an outcome it decided; see docs/custom-environments.md.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from darwin_memo import Document, LocalEncoder, MemoryStore, QueryProtocol

SUFFIXES = {".txt", ".md"}

_STAND_IN = {
    "runbook.txt": (
        "The nightly export job writes to /var/exports and is safe to rerun. "
        "Cache files under /var/cache/thumbs are regenerated on demand and "
        "may be deleted at any time. Database files under /var/lib/db are "
        "never safe to delete: restoring one costs a full replica rebuild."
    ),
    "onboarding.md": (
        "New engineers get read access to the staging cluster on day one. "
        "Production access requires a second reviewer and is granted per "
        "release, never standing."
    ),
}


def sample_directory() -> Path:
    """A stand-in corpus, so the no-argument path exercises the real one."""
    root = Path(tempfile.mkdtemp(prefix="darwin-memo-corpus-"))
    for name, text in _STAND_IN.items():
        (root / name).write_text(text)
    return root


def load(directory: Path) -> list[Document]:
    """Every text file in a directory, one Document each.

    One file per Document is the simple choice, and it is the right one until
    your files get long: an entry can only be as specific as the document it
    was encoded from, and the retrieval floor compares a whole document's
    vocabulary against a short task. If a file is more than a few pages, split
    it on its own headings and pass each section as its own Document with a
    doc_id like "runbook#rotation".
    """
    paths = sorted(p for p in directory.rglob("*") if p.suffix.lower() in SUFFIXES)
    if not paths:
        raise SystemExit(f"no {' or '.join(sorted(SUFFIXES))} files under {directory}")
    return [
        Document(doc_id=p.relative_to(directory).as_posix(), text=p.read_text())
        for p in paths
    ]


def main() -> int:
    given = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    directory = given or sample_directory()
    if given and not given.is_dir():
        raise SystemExit(f"not a directory: {given}")
    print(f"Reading {directory}" + ("" if given else "  (generated stand-in)"))

    docs = load(directory)
    print(f"  {len(docs)} document(s), {sum(len(d.text) for d in docs):,} chars")

    # LocalEncoder is offline and deterministic. Swap in ReflectionEncoder(client)
    # for LLM-authored QA pairs; see examples/common.py for the selection logic.
    store = MemoryStore(upkeep=0.05)
    for entry in LocalEncoder().encode(docs):
        store.add(entry)
    print(f"  {len(store.alive())} entries encoded")

    protocol = QueryProtocol(store)
    print("\n-- questions that share vocabulary with the corpus --")
    for question in (
        "What do cache files under /var/cache/thumbs need?",
        "What does production access require?",
    ):
        answer = protocol.answer(question)
        said = answer.text or "(silent -- nothing cleared the relevance floor)"
        print(f"\n  Q: {question}\n  A: {said[:150]}")

    # The single most common surprise on a new corpus, shown rather than
    # described. This asks about the same cache files, but shares only
    # structural words -- "safe", "delete", "files" -- with every entry at
    # once, so the ranking is decided by tokens that carry no topic. The
    # honest fix is not a better prompt: it is an embedding retriever
    # (EmbeddingRetriever), or corpus and questions that share real
    # vocabulary. An earlier version of this package let entries like this
    # decide, got them executed for it, and that is why the relevance floor
    # exists.
    print("\n-- the same topic, phrased in structural words --")
    question = "Are thumbnail cache files safe to delete?"
    answer = protocol.answer(question)
    print(f"\n  Q: {question}\n  A: {(answer.text or '(silent)')[:150]}")
    print("  ^ note this answers about the database files, not the caches.")

    out = Path("my-memory.json")
    store.save(out)
    print(f"\nSaved to {out}.  Inspect it with:  darwin-memo doctor {out}")
    print("Silence on a question you expected to answer is the relevance floor,")
    print("not a bug -- see the failure modes in docs/custom-environments.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
