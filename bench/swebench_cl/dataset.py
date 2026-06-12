"""The pinned SWE-Bench-CL dataset and the committed task manifest.

SWE-Bench-CL ships as one JSON file in its authors' GitHub repository
(thomasjoshi/agents-never-forget). It has no releases and no registry
mirror, so the pin is a (commit, sha256) pair: the manifest records
both, ``load_dataset`` refuses a file whose hash does not match, and
``fetch_dataset`` downloads the exact blob at the pinned commit. A
manifest whose dataset can drift is not a manifest.

The committed manifest (``manifests/pilot.json``) holds only task
IDENTITY per sequence: instance id, order, repo, base commit. Problem
statements, gold patches, and test lists stay in the (pinned) dataset
file and are joined in at run time, so the repo does not re-vendor
5.8 MB of upstream text it can verify instead.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DatasetPin:
    """Where the dataset lives and exactly which bytes are valid."""

    name: str
    repo: str
    commit: str
    path: str
    sha256: str

    @property
    def url(self) -> str:
        return (
            f"https://raw.githubusercontent.com/{self.repo}/{self.commit}/{self.path}"
        )


# The pin: SWE-Bench-CL v1.0.0 (metadata.version inside the file), the
# only copy upstream publishes. Commit is the repository HEAD that this
# pilot was built against; the sha256 is of the raw file at that commit.
DATASET_PIN = DatasetPin(
    name="SWE-Bench-CL-Curriculum",
    repo="thomasjoshi/agents-never-forget",
    commit="74a38a90baace25635f3827ee2f98caff24b3768",
    path="data/SWE-Bench-CL-Curriculum.json",
    sha256="91bc39a769b6218419bd44308650e5d2c846ecd3e6f7a6c086f74a37b6db90f7",
)

# The two pilot sequences, chosen for size: the smallest sequences in
# the dataset keep a full-sequence pilot affordable while still giving
# the lesson store enough tasks to reach its population budget.
PILOT_SEQUENCES = (
    "pytest-dev_pytest_sequence",
    "astropy_astropy_sequence",
)


@dataclass
class TaskRecord:
    """One task, joined from the manifest and the pinned dataset."""

    instance_id: str
    order: int
    repo: str
    base_commit: str
    problem_statement: str = ""
    gold_patch: str = ""
    test_patch: str = ""
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    difficulty: str = ""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path: Path, pin: DatasetPin = DATASET_PIN) -> dict[str, Any]:
    """Load and verify the dataset file against the pin. Loud on drift."""
    actual = file_sha256(path)
    if actual != pin.sha256:
        raise ValueError(
            f"{path} sha256 {actual} does not match the pinned dataset "
            f"{pin.sha256} ({pin.repo}@{pin.commit[:10]}:{pin.path}); "
            "refusing to run against unverified data"
        )
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def fetch_dataset(dest: Path, pin: DatasetPin = DATASET_PIN) -> Path:
    """Download the pinned dataset blob, verify it, return the path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(pin.url, timeout=120) as response:
        dest.write_bytes(response.read())
    try:
        load_dataset(dest, pin)  # verify or raise; never keep a bad file
    except ValueError:
        dest.unlink(missing_ok=True)
        raise
    return dest


def _sequence(dataset: dict[str, Any], sequence_id: str) -> dict[str, Any]:
    for seq in dataset.get("sequences", []):
        if seq.get("id") == sequence_id:
            return dict(seq)
    known = [s.get("id") for s in dataset.get("sequences", [])]
    raise KeyError(f"sequence {sequence_id!r} not in dataset (have {known})")


def build_manifest(
    dataset: dict[str, Any],
    sequence_ids: tuple[str, ...] = PILOT_SEQUENCES,
    pin: DatasetPin = DATASET_PIN,
) -> dict[str, Any]:
    """Pin sequences into a committed manifest: identity fields only.

    Validates what the runner will later rely on: orders are exactly
    1..N with no gaps (the dataset's ``sequence_position`` is the
    curriculum order, and a hole would silently reorder the curve), and
    instance ids are unique across the pinned sequences.
    """
    sequences = []
    seen: set[str] = set()
    for sequence_id in sequence_ids:
        seq = _sequence(dataset, sequence_id)
        tasks = []
        for task in seq["tasks"]:
            meta = task["metadata"]
            order = int(task["continual_learning"]["sequence_position"])
            instance_id = str(meta["instance_id"])
            if instance_id in seen:
                raise ValueError(f"duplicate instance id {instance_id}")
            seen.add(instance_id)
            tasks.append(
                {
                    "instance_id": instance_id,
                    "order": order,
                    "repo": str(meta["repo"]),
                    "base_commit": str(meta["base_commit"]),
                }
            )
        tasks.sort(key=lambda t: int(str(t["order"])))
        orders = [t["order"] for t in tasks]
        if orders != list(range(1, len(tasks) + 1)):
            raise ValueError(
                f"{sequence_id}: sequence_position is not contiguous 1..N: {orders}"
            )
        sequences.append(
            {
                "id": sequence_id,
                "repo": str(seq["repo"]),
                "num_tasks": len(tasks),
                "tasks": tasks,
            }
        )
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset": {
            "name": pin.name,
            "repo": pin.repo,
            "commit": pin.commit,
            "path": pin.path,
            "sha256": pin.sha256,
            "url": pin.url,
            "version": str(dataset.get("metadata", {}).get("version", "unknown")),
        },
        "sequences": sequences,
    }


def load_manifest(path: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(path.read_text())
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"{path}: manifest schema {manifest.get('schema_version')!r}, "
            f"this code reads {MANIFEST_SCHEMA_VERSION}"
        )
    return manifest


def sequence_tasks(
    manifest: dict[str, Any], dataset: dict[str, Any], sequence_id: str
) -> list[TaskRecord]:
    """Join manifest identity with dataset content, in curriculum order.

    The join is strict both ways: a manifest task missing from the
    dataset, or a base commit that moved, means the pin and the data
    have diverged, and the run must not start.
    """
    pinned = next((s for s in manifest["sequences"] if s["id"] == sequence_id), None)
    if pinned is None:
        raise KeyError(f"sequence {sequence_id!r} not in manifest")
    by_id: dict[str, dict[str, Any]] = {}
    for task in _sequence(dataset, sequence_id)["tasks"]:
        by_id[str(task["metadata"]["instance_id"])] = task
    records = []
    for entry in pinned["tasks"]:
        task = by_id.get(entry["instance_id"])
        if task is None:
            raise ValueError(
                f"{entry['instance_id']} pinned in manifest but absent "
                f"from dataset sequence {sequence_id}"
            )
        meta = task["metadata"]
        if str(meta["base_commit"]) != entry["base_commit"]:
            raise ValueError(
                f"{entry['instance_id']}: manifest base commit "
                f"{entry['base_commit'][:10]} != dataset "
                f"{str(meta['base_commit'])[:10]}"
            )
        evaluation = task["evaluation"]
        records.append(
            TaskRecord(
                instance_id=entry["instance_id"],
                order=int(entry["order"]),
                repo=str(meta["repo"]),
                base_commit=entry["base_commit"],
                problem_statement=str(task["task"]["problem_statement"]),
                gold_patch=str(evaluation.get("patch", "")),
                test_patch=str(evaluation.get("test_patch", "")),
                fail_to_pass=[str(t) for t in evaluation.get("FAIL_TO_PASS", [])],
                pass_to_pass=[str(t) for t in evaluation.get("PASS_TO_PASS", [])],
                difficulty=str(meta.get("difficulty", "")),
            )
        )
    return records
