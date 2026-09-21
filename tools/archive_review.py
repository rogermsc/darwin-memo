"""Create a checksummed local review snapshot. This does not publish an archive."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    checksum = args.output.with_suffix(args.output.suffix + ".sha256")
    if args.output.exists() or checksum.exists():
        parser.error("Archive or checksum already exists; choose another output")
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    roots = {
        "darwin_memo",
        "bench",
        "paper",
        "tools",
        "docs",
        "examples",
        "ui",
        ".github",
    }
    files = sorted(
        {
            p
            for p in paths
            if p
            and (Path(p).parts[0] in roots or len(Path(p).parts) == 1)
            and (ROOT / p).is_file()
            and not (ROOT / p).is_symlink()
        }
    )
    manifest = {
        "status": "development review; not submitted or independently reproduced",
        "base_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
        ),
        "files": {
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(path)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (ROOT / path).read_bytes())
        archive.writestr("REVIEW-MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    with checksum.open("x") as stream:
        stream.write(f"{digest}  {args.output.name}\n")
    print(
        json.dumps({"archive": str(args.output), "sha256": digest, "files": len(files)})
    )


if __name__ == "__main__":
    main()
