"""Lesson minting: a deterministic template, never an LLM judge.

After each task the memory arms write one lesson. The TEXT may quote
the model's own final reflection (that is the only model-authored part,
and it is clearly attributed), but the verdict baked into the lesson
and the settlement that follows come purely from the evaluation
result. No model ever grades a lesson; selection does.

The question is phrased in the repository's own vocabulary (repo name
plus the files the model's patch touched), because lexical retrieval
must connect FUTURE task statements to it. A lesson nobody can retrieve
never earns and starves on upkeep, which is the correct fate for one
that taught nothing reusable.
"""

from __future__ import annotations

import re

from .dataset import TaskRecord
from .executor import EvalReport

_REFLECTION_CAP = 280
# House rule (no em or en dashes), enforced mechanically because the
# text is model-authored. Unicode escapes keep the banned characters
# out of this file's own source.
_DASH_RE = re.compile("[\u2014\u2013]")
_FILE_RE = re.compile(r"^diff --git a/(\S+)", re.MULTILINE)


def patched_files(patch: str, limit: int = 3) -> list[str]:
    """Files the model's own patch touched. Never reads gold data."""
    return _FILE_RE.findall(patch)[:limit]


def sanitize(text: str) -> str:
    """One line, capped, no em or en dashes."""
    text = _DASH_RE.sub(", ", " ".join(text.split()))
    return text[:_REFLECTION_CAP]


def mint_lesson(
    task: TaskRecord, patch: str, reflection: str, report: EvalReport
) -> tuple[str, str]:
    """(question, answer) for the lesson store. Deterministic template."""
    files = patched_files(patch)
    where = ", ".join(files) if files else "the repository"
    question = (
        f"What is known about working on {where} in {task.repo} "
        f"(from task {task.instance_id})?"
    )
    if report.resolved:
        verdict = (
            f"Worked: resolved, {report.f2p_passed}/{report.f2p_total} "
            "fail-to-pass tests fixed."
        )
    elif report.empty_patch:
        verdict = "Failed: no patch was produced."
    elif not report.patch_applied:
        verdict = "Failed: the patch did not apply."
    else:
        verdict = (
            f"Failed: {report.f2p_passed}/{report.f2p_total} fail-to-pass "
            f"tests fixed, {report.p2p_total - report.p2p_passed} regressions."
        )
    answer = verdict
    cleaned = sanitize(reflection)
    if cleaned:
        answer = f"{verdict} Model reflection: {cleaned}"
    return question, answer
