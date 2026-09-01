# Contributing

Thanks for looking under the hood. This is a small, deliberately
readable package; contributions that keep it that way are welcome.

## Setup

```bash
git clone https://github.com/rogermsc/darwin-memo
cd darwin-memo
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Repository size

`bench/results/` is 414 MB of committed evidence and that is not a mistake:
every number in the paper is re-derived from it in CI, so it has to be in
the tree. A clone is much smaller than the checkout, because git already
compresses it -- `.git` is about 64 MB.

Compressing the files on disk was considered and rejected. It would shrink
the checkout to roughly 23 MB, but gzip output does not delta-compress, so
every regeneration would add a full copy to history instead of a diff, the
repository would grow *faster* forever, and `reproduce.sh`'s offline check
plus every reader would need changing. If you only want the code:

```bash
git clone --filter=blob:none https://github.com/rogermsc/darwin-memo
```

That fetches blobs on demand and needs no change to the repository.

## The three commands

Run all of these before pushing; CI enforces them:

```bash
ruff check . && ruff format .
mypy
pytest -q --cov
```

The examples must keep running offline with zero API keys:
`for ex in examples/0*.py; do python "$ex"; done`.

## Dashboard

`darwin-memo ui` serves a small read-only operator dashboard. Its
frontend lives in `ui/` (Vite + React + TypeScript) and is built
separately from the Python package:

```bash
cd ui && npm install && npm run build
```

That emits static assets into `darwin_memo/data/ui/`, which is
gitignored and produced in CI at release time, never committed. Without
a built bundle, `darwin-memo ui` still serves a "no bundle" placeholder
page plus the live JSON API (`/api/state`, `/api/entry/<id>`,
`/api/events`) — Python-only contributors never need node installed.

## The one design rule

Environments measure, never grade. A `verify` implementation returns a
delta in a conserved, externally measurable resource (bytes, passing
tests, dollars). The moment a model's judgment becomes the selection
signal, the whole premise of the package collapses: that is the proxy
optimization both papers are built to avoid. Related corollaries:

- Retrieval scoring never reads entry energy (energy is a tie-break in
  the store, nothing more).
- Memory silence is preferred over guessing; environments decide what
  silence means.

If a change touches a claim in README or docs/benchmarks.md, rerun the
benchmark suite and update the numbers. Claims trace to tables, never
the other way around.

## Releasing (maintainer notes)

1. Bump `__version__` in `darwin_memo/__init__.py` (the only version
   location).
2. Move the CHANGELOG `[Unreleased]` content into a dated section and
   update the link references.
3. Commit, push, wait for CI green.
4. `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`. The
   release workflow builds, validates, publishes to PyPI via trusted
   publishing, and creates the GitHub release with the changelog
   section.
5. For a dry run, use an `rc` tag (for example `v0.2.0rc1` with the
   matching `__version__`): it routes to TestPyPI instead.
