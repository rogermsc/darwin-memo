from darwin_memo import EntryKind, MemoryEntry, MemoryStore


def test_upkeep_kills_unused_entries():
    store = MemoryStore(upkeep=0.05)
    entry = store.add(
        MemoryEntry(question="What is X?", answer="X is a thing.", energy=0.1)
    )
    assert len(store) == 1

    dead_first = store.charge_upkeep()
    assert dead_first == []
    dead_second = store.charge_upkeep()

    assert [e.id for e in dead_second] == [entry.id]
    assert len(store) == 0
    assert store.graveyard()[0].id == entry.id


def test_credit_caps_at_max_energy():
    store = MemoryStore(max_energy=2.0)
    entry = store.add(MemoryEntry(question="Q?", answer="A."))
    store.credit(entry.id, 10.0, cycle=3)
    assert entry.energy == 2.0
    assert entry.uses == 1
    assert entry.last_used_cycle == 3


def test_retrieve_ranks_by_lexical_match():
    store = MemoryStore()
    relevant = store.add(
        MemoryEntry(
            question="What about database files?",
            answer="Database files must be retained.",
        )
    )
    store.add(
        MemoryEntry(
            question="What about log files?",
            answer="Old log files may be deleted.",
        )
    )

    hits = store.retrieve("Is it safe to delete the database file?", k=2)
    assert hits
    assert hits[0][0].id == relevant.id


def test_retrieve_ignores_dead_entries():
    store = MemoryStore()
    entry = store.add(
        MemoryEntry(question="What about caches?", answer="Cache files are disposable.")
    )
    store.bury(entry.id)
    assert store.retrieve("caches") == []


def test_load_tolerates_unknown_config_keys(tmp_path):
    """Files saved by other versions of the package must still load."""
    import json

    store = MemoryStore(upkeep=0.05)
    store.add(MemoryEntry(question="Q?", answer="A."))
    path = tmp_path / "memory.json"
    store.save(path)

    payload = json.loads(path.read_text())
    payload["config"]["initial_energy"] = 1.0  # removed in 0.1.0 cleanup
    payload["some_future_key"] = {"x": 1}
    path.write_text(json.dumps(payload))

    loaded = MemoryStore.load(path)
    assert len(loaded) == 1
    assert loaded.upkeep == 0.05


def test_save_and_load_roundtrip(tmp_path):
    store = MemoryStore(upkeep=0.07)
    store.add(
        MemoryEntry(
            question="Q1?", answer="A1.", kind=EntryKind.ENTITY, sources=["doc-1"]
        )
    )
    dead = store.add(MemoryEntry(question="Q2?", answer="A2."))
    store.bury(dead.id)

    path = tmp_path / "memory.json"
    store.save(path)
    loaded = MemoryStore.load(path)

    assert loaded.upkeep == 0.07
    assert len(loaded) == 1
    assert loaded.alive()[0].kind == EntryKind.ENTITY
    assert len(loaded.graveyard()) == 1


def test_energy_share_by_kind():
    store = MemoryStore()
    store.add(
        MemoryEntry(question="Q1?", answer="A1.", kind=EntryKind.EXPLICIT, energy=3.0)
    )
    store.add(
        MemoryEntry(question="Q2?", answer="A2.", kind=EntryKind.EXPERIENCE, energy=1.0)
    )
    shares = store.energy_share_by_kind()
    assert abs(shares["explicit"] - 0.75) < 1e-9
    assert abs(shares["experience"] - 0.25) < 1e-9
