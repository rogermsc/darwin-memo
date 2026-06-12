"""Manifest for committed benchmark results: what, how, reproduce-with.

Committed raw results are only auditable evidence if the repo also
states exactly what produced them. ``MANIFEST.json`` sits next to the
result files and records, per file: the suite, the seeds, a hash of the
full run configuration grid, the exact reproduction command, and the
library version that ran. ``python -m bench.report <file> --check``
validates the file against its manifest entry, so CI catches a result
file and its manifest drifting apart (results regenerated without the
manifest, manifest edited by hand, a different config grid committed
under an old name).

The config hash covers identity fields only (suite, arm, seed, label,
config), never metrics or wall times, so the same grid hashes the same
on every machine.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

MANIFEST_NAME = "MANIFEST.json"
SCHEMA_VERSION = 1


def config_hash(runs: list[dict[str, Any]]) -> str:
    """Order-independent hash of the run grid's identity fields."""
    grid = sorted(
        json.dumps(
            {
                "suite": run.get("suite"),
                "arm": run.get("arm"),
                "seed": run.get("seed"),
                "label": run.get("label", ""),
                "config": run.get("config", {}),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        for run in runs
    )
    return "sha256:" + hashlib.sha256("\n".join(grid).encode()).hexdigest()


def update_manifest(
    results_path: Path, runs: list[dict[str, Any]], command: str
) -> Path:
    """Write or refresh this result file's entry in the sibling manifest."""
    manifest_path = results_path.parent / MANIFEST_NAME
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {"schema_version": SCHEMA_VERSION, "files": {}}
    suites = sorted({str(run.get("suite")) for run in runs})
    seeds = sorted({int(run["seed"]) for run in runs if "seed" in run})
    versions = sorted(
        {str(run.get("meta", {}).get("darwin_memo", "unknown")) for run in runs}
    )
    manifest["files"][results_path.name] = {
        "suite": suites[0] if len(suites) == 1 else suites,
        "seeds": seeds,
        "runs": len(runs),
        "config_hash": config_hash(runs),
        "command": command,
        "darwin_memo": versions[0] if len(versions) == 1 else versions,
    }
    manifest["files"] = dict(sorted(manifest["files"].items()))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest_path


def manifest_failures(results_path: Path, runs: list[dict[str, Any]]) -> list[str]:
    """Validate a results file against its manifest entry, if one exists.

    A missing manifest, or a file with no entry (smoke runs written next
    to committed results), is not a failure: the manifest only binds the
    files it names. Once named, the entry must match the file exactly.
    """
    manifest_path = results_path.parent / MANIFEST_NAME
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text())
    entry = manifest.get("files", {}).get(results_path.name)
    if entry is None:
        return []
    failures: list[str] = []
    if entry.get("runs") != len(runs):
        failures.append(f"manifest says {entry.get('runs')} runs, file has {len(runs)}")
    seeds = sorted({int(run["seed"]) for run in runs if "seed" in run})
    if entry.get("seeds") != seeds:
        failures.append(f"manifest seeds {entry.get('seeds')} != file seeds {seeds}")
    actual_hash = config_hash(runs)
    if entry.get("config_hash") != actual_hash:
        failures.append(
            f"manifest config_hash {entry.get('config_hash')} != "
            f"recomputed {actual_hash}"
        )
    versions = {str(run.get("meta", {}).get("darwin_memo", "unknown")) for run in runs}
    expected = entry.get("darwin_memo")
    if versions != ({expected} if isinstance(expected, str) else set(expected or [])):
        failures.append(
            f"manifest darwin_memo {expected!r} != file versions {sorted(versions)}"
        )
    if not entry.get("command"):
        failures.append("manifest entry has no reproduction command")
    return [f"{results_path.name}: {f}" for f in failures]
