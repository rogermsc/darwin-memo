"""Settle this repo's lesson-store tickets from a merged PR.

Invoked by .github/workflows/memory.yml with:

    PR_BODY        the merged pull request body (tickets ride in it as
                   `darwin-memo-ticket: <id>` lines)
    PASSES_BEFORE  passing-test count at the PR's base commit
    PASSES_AFTER   passing-test count at the merge commit
    RUN_URL        the Actions run, recorded as settlement detail

The delta is a measurement (tests passing after minus before), never a
grade; that is the whole contract. After settling, one tick runs
(upkeep, expiry, consolidation) and the store is saved for the
workflow to commit. Exits zero even when no tickets are present, since
ticking on every merged PR is the store's heartbeat.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from darwin_memo import Ledger

STORE = Path(__file__).parent / "lessons.json"
TICKET_RE = re.compile(r"darwin-memo-ticket:\s*([0-9a-f]{12})")


def main() -> int:
    ledger = Ledger.load(STORE, resource_scale=2.0)
    delta = float(
        int(os.environ.get("PASSES_AFTER", 0)) - int(os.environ.get("PASSES_BEFORE", 0))
    )
    detail = os.environ.get("RUN_URL", "")

    tickets = TICKET_RE.findall(os.environ.get("PR_BODY") or "")
    for ticket_id in tickets:
        landed = ledger.settle(ticket_id, delta, detail=detail)
        print(
            f"settled {ticket_id} at delta {delta:+g}"
            if landed
            else f"NOT settled: {ticket_id} unknown, already settled, or expired"
        )

    stats = ledger.tick()
    ledger.save(STORE)
    print(f"tick: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
