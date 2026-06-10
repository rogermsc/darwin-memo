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

## The three commands

Run all of these before pushing; CI enforces them:

```bash
ruff check . && ruff format .
mypy
pytest -q --cov
```

The examples must keep running offline with zero API keys:
`for ex in examples/0*.py; do python "$ex"; done`.

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
