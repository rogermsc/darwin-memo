"""The advisory lock: contention is loud, release is unconditional.

flock locks belong to open file descriptions, not processes, so a
second ``os.open`` of the lock file contends with the first even
inside one test process: no subprocess choreography needed.
"""

import os

import pytest

from darwin_memo import Ledger, MemoryEntry, MemoryStore, StoreLockedError
from darwin_memo.store import store_lock

fcntl = pytest.importorskip("fcntl", reason="the advisory lock is POSIX-only")


def hold_lock(path):
    """Take the sidecar lock the way a competing process would."""
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def populated_store() -> MemoryStore:
    store = MemoryStore()
    store.add(MemoryEntry(question="Q?", answer="A."))
    return store


def test_save_refuses_while_lock_held(tmp_path):
    path = tmp_path / "memory.json"
    fd = hold_lock(path)
    try:
        with pytest.raises(StoreLockedError, match=r"memory\.json\.lock"):
            populated_store().save(path)
    finally:
        os.close(fd)
    assert not path.exists(), "the contended save must not have written"


def test_load_refuses_while_lock_held(tmp_path):
    path = tmp_path / "memory.json"
    populated_store().save(path)
    fd = hold_lock(path)
    try:
        with pytest.raises(StoreLockedError, match="single-writer"):
            MemoryStore.load(path)
    finally:
        os.close(fd)


def test_ledger_save_and_load_hold_the_lock(tmp_path):
    path = tmp_path / "memory.json"
    ledger = Ledger(populated_store())
    fd = hold_lock(path)
    try:
        with pytest.raises(StoreLockedError):
            ledger.save(path)
    finally:
        os.close(fd)

    ledger.save(path)  # holder gone: same call now lands
    fd = hold_lock(path)
    try:
        with pytest.raises(StoreLockedError):
            Ledger.load(path)
    finally:
        os.close(fd)
    assert len(Ledger.load(path).store) == 1


def test_lock_released_after_exception_mid_save(tmp_path, monkeypatch):
    """A crash inside the locked region must not leave the lock held."""
    path = tmp_path / "memory.json"

    def boom(path, payload):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("darwin_memo.store.write_json_atomic", boom)
    with pytest.raises(RuntimeError, match="disk on fire"):
        populated_store().save(path)
    monkeypatch.undo()

    fd = hold_lock(path)  # acquires immediately: the lock was released
    os.close(fd)
    populated_store().save(path)
    assert len(MemoryStore.load(path)) == 1


def test_lock_released_after_exception_in_context(tmp_path):
    path = tmp_path / "memory.json"
    with pytest.raises(RuntimeError, match="boom"), store_lock(path):
        raise RuntimeError("boom")
    with store_lock(path):
        pass  # reacquisition succeeds: no stale holder


def test_normal_persistence_unaffected(tmp_path):
    path = tmp_path / "memory.json"
    store = populated_store()
    store.save(path)
    loaded = MemoryStore.load(path)
    assert len(loaded) == 1

    # The sidecar stays behind by design (unlinking would race a
    # concurrent acquisition), and holds no lock between operations.
    sidecar = tmp_path / "memory.json.lock"
    assert sidecar.exists()
    fd = hold_lock(path)
    os.close(fd)
