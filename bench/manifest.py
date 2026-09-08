"""Manifest for committed benchmark results: what, how, reproduce-with.

Committed raw results are only auditable evidence if the repo also
states exactly what produced them. ``MANIFEST.json`` sits next to the
result files and records, per file: the suite, the seeds, a hash of the
full run configuration grid, the exact reproduction command, the
library version that ran, and the producing git commit. The commit
matters because ``__version__`` only moves at release time: a results
file regenerated from an unreleased checkout can carry the released
version string while the world-generation code has moved on, and the
commit is the pointer that stays honest. ``python -m bench.report
<file> --check`` validates the file against its manifest entry, so CI
catches a result file and its manifest drifting apart (results
regenerated without the manifest, manifest edited by hand, a different
config grid committed under an old name).

The config hash covers identity fields only (suite, arm, seed, label,
config), never metrics or wall times, so the same grid hashes the same
on every machine.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

MANIFEST_NAME = "MANIFEST.json"
SCHEMA_VERSION = 1


def _git_commit(repo_dir: Path, produced: tuple[Path, ...] = ()) -> str:
    """Best-effort commit of the producing CODE, "unknown" outside git.

    A ``-dirty`` suffix means the code that produced these runs had
    uncommitted changes, so the named commit brackets it rather than
    pinning it. What it must not mean is "this tool just wrote its own
    output": a re-run on a spotless checkout always rewrites the results
    file (metrics are byte-identical, ``wall_time_s`` is not), so every
    pin came back dirty and re-running could never produce a clean one.
    Paths in ``produced`` -- the results file and the manifest beside it
    -- are therefore excluded from the check, and nothing else is.

    A squash merge still rewrites the commit this names, so the repin
    after landing remains a manual step; that part is not fixable here.
    """
    ignored = {path.resolve() for path in produced}
    try:
        root = Path(
            subprocess.run(
                ["git", "-C", str(repo_dir), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        head = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "unknown"

    dirty = False
    for line in status.splitlines():
        if not line.strip():
            continue
        # "XY path", and a rename is "XY old -> new"; the new path is the
        # one that exists, and the only one that could be an artifact.
        entry = line[3:].split(" -> ")[-1].strip().strip('"')
        if (root / entry).resolve() not in ignored:
            dirty = True
            break
    return head + ("-dirty" if dirty else "")


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
    results_path: Path,
    runs: list[dict[str, Any]],
    command: str,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write or refresh this result file's entry in the sibling manifest.

    ``extra`` carries suite-specific evidence (the LLM suite records
    ollama model digests, so the entry names exact weights rather than
    mutable tags). Extra fields are documentation: validation reads
    only the identity fields it computes itself.
    """
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
        "source_commit": _git_commit(
            results_path.parent, (results_path, manifest_path)
        ),
        **(extra or {}),
    }
    manifest["files"] = dict(sorted(manifest["files"].items()))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest_path


def manifest_failures(
    results_path: Path,
    runs: list[dict[str, Any]],
    require_entry: bool = False,
) -> list[str]:
    """Validate a results file against its manifest entry, if one exists.

    A missing manifest, or a file with no entry (smoke runs written next
    to committed results), is not a failure by default: the manifest
    only binds the files it names. For committed evidence pass
    ``require_entry=True``, so deleting the manifest (or its entry)
    reads as a failure instead of a silent pass. Once named, the entry
    must match the file exactly.
    """
    manifest_path = results_path.parent / MANIFEST_NAME
    if not manifest_path.exists():
        if require_entry:
            return [f"{results_path.name}: no {MANIFEST_NAME} next to results"]
        return []
    manifest = json.loads(manifest_path.read_text())
    entry = manifest.get("files", {}).get(results_path.name)
    if entry is None:
        if require_entry:
            return [f"{results_path.name}: no entry in {MANIFEST_NAME}"]
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
