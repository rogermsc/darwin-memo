from darwin_memo import EntryKind, MemoryEntry, MemoryStore, consolidate


def test_similar_entries_merge_and_energy_pools():
    store = MemoryStore(max_energy=10.0)
    a = store.add(
        MemoryEntry(
            question="What about old log files under logs/?",
            answer="Old log files under logs/ may be deleted after seven days.",
            energy=2.0,
        )
    )
    b = store.add(
        MemoryEntry(
            question="What about log files under logs/?",
            answer="Log files under logs/ may be deleted after seven days of age.",
            energy=1.5,
        )
    )
    unrelated = store.add(
        MemoryEntry(
            question="Who maintains the quarterly reports?",
            answer="The finance team maintains quarterly report pdf files.",
            energy=1.0,
        )
    )

    merges = consolidate(store, cycle=4, threshold=0.5)

    assert merges == 1
    alive = {e.id: e for e in store.alive()}
    assert unrelated.id in alive
    merged = [e for e in alive.values() if e.kind == EntryKind.CONSOLIDATED]
    assert len(merged) == 1
    assert abs(merged[0].energy - 3.5) < 1e-9
    assert set(merged[0].lineage) == {a.id, b.id}
    assert a.id not in alive and b.id not in alive


def test_dissimilar_entries_do_not_merge():
    store = MemoryStore()
    store.add(MemoryEntry(question="What about caches?", answer="Caches are disposable."))
    store.add(MemoryEntry(question="Who runs payroll?", answer="Finance runs payroll monthly."))
    assert consolidate(store, cycle=1, threshold=0.5) == 0
    assert len(store) == 2


def test_merged_entry_retrievable_for_original_query():
    store = MemoryStore()
    store.add(
        MemoryEntry(
            question="What about database store files?",
            answer="Database store files must be retained.",
            energy=2.0,
        )
    )
    store.add(
        MemoryEntry(
            question="What about the database store files under data/?",
            answer="Database store files under data/ must be retained always.",
            energy=2.0,
        )
    )
    consolidate(store, cycle=2, threshold=0.5)
    hits = store.retrieve("Is it safe to delete this database store file?")
    assert hits
    assert hits[0][0].kind == EntryKind.CONSOLIDATED
