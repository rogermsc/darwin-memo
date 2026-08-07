"""Degeneracy rules shared by the batch loop and the event-driven ledger.

Both shapes hit the same failure modes and both used to diagnose them
separately (or, in the Ledger's case, not at all). One threshold set
lives here so a fix lands once and the two surfaces cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass

# A store that answers almost nothing cannot earn, whatever else is true.
SILENCE_LIMIT = 0.8
# Volume floors: three decisions are not evidence of a broken environment.
MIN_DECIDES = 10
MIN_SETTLES = 5
# Mirrors the ``expire_after`` default on Ledger.tick and the tick CLI.
STALE_TICKET_TICKS = 50
# Starvation reads as a population property, not a one-entry accident.
MIN_DEATHS = 3
STARVED_SHARE = 0.5


@dataclass(frozen=True)
class Finding:
    """One diagnosis: what fired, how bad, the evidence, and the fix.

    ``severity`` is "error" (the store is not working) or "warn" (an
    operational fault worth knowing about). Only errors set an exit code.
    """

    code: str
    severity: str
    summary: str
    evidence: str
    fix: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "summary": self.summary,
            "evidence": self.evidence,
            "fix": self.fix,
        }


def selection_findings(
    *, decides: int, silent: int, nonzero_outcomes: int, settles: int
) -> list[Finding]:
    """The two degeneracies a new environment hits, in priority order.

    Mutually exclusive by design: memory that never speaks obviously
    never earned, so reporting both diagnoses buries the actionable one.

    ``nonzero_outcomes`` is GROSS movement and must never be a net sum.
    A window whose payouts exactly cancel did pay out, and float
    equality against a net total would call a working environment dead.
    """
    if decides >= MIN_DECIDES and silent / decides > SILENCE_LIMIT:
        return [
            Finding(
                code="silent_majority",
                severity="error",
                summary=f"memory was silent on {silent}/{decides} decisions",
                evidence=f"silence rate {silent / decides:.0%}",
                fix=(
                    "task phrasing likely does not lexically overlap the "
                    "corpus (see min_coverage), so nothing can earn energy"
                ),
            )
        ]
    if settles >= MIN_SETTLES and nonzero_outcomes == 0:
        return [
            Finding(
                code="env_never_paid",
                severity="error",
                summary=f"none of {settles} settlements carried an outcome",
                evidence=f"{settles} settlements, every delta zero",
                fix=(
                    "the environment never paid out; check that verify() "
                    "reads your answers (is decision_polarity's vocabulary "
                    "right for your action verbs?)"
                ),
            )
        ]
    return []
