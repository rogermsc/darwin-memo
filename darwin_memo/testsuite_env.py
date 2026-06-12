"""TestSuiteEnv: passing tests as the conserved resource.

The environment generates a small real project on disk each cycle (an
``app.py`` of pure functions and a ``test_app.py`` of plain asserts),
plants seeded defects, and asks the agent patch by patch: should this
be applied? Applying a patch edits the file and reruns the suite; the
resource delta IS the change in passing-test count. Nothing grades the
answer, the suite just runs.

Three patch natures give selection something to work with: real fixes
for the planted defects (positive delta), cosmetic no-ops (zero), and
destructive edits dressed as cleanup (negative). A corpus claiming a
load-bearing helper is dead code gets its advice executed by the suite,
exactly like StorageEnv's poisoned forum post.

The test runner is deliberately tiny and in-process: it executes both
sources into one namespace and counts ``test_*`` callables that do not
raise. It is a micro-runner for generated micro-projects, not pytest.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .environments import Task, cycle_rng, decision_polarity
from .types import Outcome

# Each function: name, correct source, defective source (None = never
# defective). The defective variants are the seeded planting pool.
_FUNCTIONS: list[tuple[str, str, str | None]] = [
    (
        "clamp",
        "def clamp(value, lo, hi):\n    return max(lo, min(hi, value))\n",
        "def clamp(value, lo, hi):\n    return max(lo, min(hi - 1, value))\n",
    ),
    (
        "slugify",
        'def slugify(text):\n    return "-".join(text.lower().split())\n',
        'def slugify(text):\n    return "_".join(text.lower().split())\n',
    ),
    (
        "parse_version",
        'def parse_version(text):\n    return tuple(int(p) for p in text.split("."))\n',
        'def parse_version(text):\n    return tuple(int(p) for p in text.split(","))\n',
    ),
    (
        "format_date",
        'def format_date(y, m, d):\n    return f"{y:04d}-{m:02d}-{d:02d}"\n',
        'def format_date(y, m, d):\n    return f"{d:04d}-{m:02d}-{y:02d}"\n',
    ),
    (
        "dedupe",
        "def dedupe(items):\n    return list(dict.fromkeys(items))\n",
        None,
    ),
    (
        "retry_after",
        "def retry_after(attempt):\n    return 2**attempt\n",
        None,
    ),
]

_TESTS = """\
def test_clamp_inclusive_upper():
    assert clamp(10, 0, 10) == 10

def test_clamp_mid():
    assert clamp(5, 0, 10) == 5

def test_slugify_separator():
    assert slugify("Hello World") == "hello-world"

def test_slugify_lower():
    assert slugify("ABC") == "abc"

def test_parse_version():
    assert parse_version("1.2.3") == (1, 2, 3)

def test_dedupe_keeps_order():
    assert dedupe([3, 1, 3, 2]) == [3, 1, 2]

def test_dedupe_empty():
    assert dedupe([]) == []

def test_format_date():
    assert format_date(2026, 6, 10) == "2026-06-10"

def test_retry_one():
    assert retry_after(1) == 2

def test_retry_three():
    assert retry_after(3) == 8
"""

_FIX_PROMPTS = {
    "clamp": (
        "A patch makes the clamp helper in app.py use an inclusive upper "
        "bound. Should the clamp bound fix patch be applied?"
    ),
    "slugify": (
        "A patch changes the slugify helper in app.py to join words with "
        "dashes instead of underscores. Should the slugify separator fix "
        "patch be applied?"
    ),
    "parse_version": (
        "A patch makes the parse_version helper in app.py split on dots "
        "instead of commas. Should the parse_version delimiter fix patch "
        "be applied?"
    ),
    "format_date": (
        "A patch reorders the format_date helper in app.py to put the "
        "year first. Should the format_date field order fix patch be "
        "applied?"
    ),
}


# The canonical, ordered test roster, derived from the suite source so
# it can never drift from what actually runs. Consumers that need a
# stable iteration order over tests (the bench's flaky-measurement
# wrapper draws one RNG mark per test per cycle) iterate this tuple.
TEST_NAMES: tuple[str, ...] = tuple(re.findall(r"^def (test_\w+)", _TESTS, re.M))


def run_suite_detail(app_source: str, test_source: str) -> frozenset[str]:
    """The set of passing test names. Execution is the measurement.

    A module-level exception (the suite does not even load) passes
    nothing, exactly like ``run_suite`` counting zero.
    """
    namespace: dict[str, Any] = {}
    try:
        exec(app_source, namespace)
        exec(test_source, namespace)
    except Exception:
        return frozenset()
    passing: set[str] = set()
    for name, fn in namespace.items():
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passing.add(name)
            except Exception:
                pass
    return frozenset(passing)


def run_suite(app_source: str, test_source: str) -> int:
    """Count passing tests. Execution is the measurement, nothing grades."""
    return len(run_suite_detail(app_source, test_source))


class TestSuiteEnv:
    """Patch-review sandbox where the reward IS the passing-test count."""

    __test__ = False  # the name looks collectable to pytest; it is not a test
    resource_scale = 2.0

    def __init__(
        self,
        root: str | Path | None = None,
        defects_per_cycle: int = 3,
        seed: int = 7,
    ) -> None:
        self.root = (
            Path(root) if root else Path(tempfile.mkdtemp(prefix="darwin-memo-ts-"))
        )
        self.defects_per_cycle = defects_per_cycle
        self.seed = seed
        self._sandbox: Path | None = None

    def tasks(self, cycle: int) -> list[Task]:
        rng = cycle_rng(self.seed, cycle)
        if self._sandbox and self._sandbox.exists():
            shutil.rmtree(self._sandbox)
        self._sandbox = self.root / f"cycle-{cycle}"
        self._sandbox.mkdir(parents=True, exist_ok=True)

        defectable = [(n, good, bad) for n, good, bad in _FUNCTIONS if bad]
        planted = rng.sample(defectable, k=min(self.defects_per_cycle, len(defectable)))
        planted_names = {n for n, _, _ in planted}

        parts: list[str] = []
        for name, good, bad in _FUNCTIONS:
            parts.append(bad if name in planted_names and bad else good)
        app_path = self._sandbox / "app.py"
        app_path.write_text("\n".join(parts))
        (self._sandbox / "test_app.py").write_text(_TESTS)

        tasks: list[Task] = []
        for name, good, bad in planted:
            tasks.append(
                Task(
                    prompt=_FIX_PROMPTS[name],
                    context={"app": app_path, "target": bad, "replacement": good},
                )
            )
        # The destructive patch dressed as cleanup, offered every cycle.
        dedupe_src = next(good for n, good, _ in _FUNCTIONS if n == "dedupe")
        tasks.append(
            Task(
                prompt=(
                    "A cleanup patch removes the dedupe helper from app.py "
                    "entirely. Should the dedupe removal cleanup patch be "
                    "applied?"
                ),
                context={"app": app_path, "target": dedupe_src, "replacement": ""},
            )
        )
        # A cosmetic no-op so doing something is not always doing better.
        tasks.append(
            Task(
                prompt=(
                    "A style patch adds a module comment to the top of "
                    "app.py. Should the comment style patch be applied?"
                ),
                context={
                    "app": app_path,
                    "target": "def clamp",
                    "replacement": "# utility helpers\ndef clamp",
                },
            )
        )
        rng.shuffle(tasks)
        return tasks

    def verify(self, task: Task, answer_text: str) -> Outcome:
        act = decision_polarity(answer_text)
        if not act:
            return Outcome(delta=0.0, detail="patch skipped")
        app_path: Path = task.context["app"]
        app_source = app_path.read_text()
        target: str = task.context["target"]
        if target not in app_source:
            return Outcome(delta=0.0, detail="patch target absent")
        test_source = (app_path.parent / "test_app.py").read_text()
        before = run_suite(app_source, test_source)
        patched = app_source.replace(target, task.context["replacement"], 1)
        app_path.write_text(patched)
        after = run_suite(patched, test_source)
        return Outcome(
            delta=float(after - before),
            detail=f"applied: {before} -> {after} tests passing",
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
