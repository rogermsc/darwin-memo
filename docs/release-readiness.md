# Release and pilot record

Status on 2026-09-21: local implementation and artifact review. No external
pilot, paid study, user case study, community contact, or publication has run as
part of this work. The planning window is six to eight weeks from pilot approval,
subject to participant availability. Research spending is $0 of the $500 cap.

| Milestone | Target | Observed |
|---|---|---|
| Unaided activation | Four of five independent developers complete the example | Unknown; participants not recruited |
| Continued use | Three external repositories use it for four weeks | Unknown |
| Benefit traceability | Every advertised benefit links to a reproducible comparison | README makes no cost/success benefit claim |
| Independent reproduction | One independent reader reproduces the central table | Local reconstruction only; independent reader pending |
| Case studies | Two consenting users, including failures and reasons for continued use | Pending consent and observation |

Local observations are recorded in the [implementation verification record](implementation-verification.md).

## Sequence

1. Review the local reliability evidence and generated setup.
2. Authorize recruitment and collect setup effort, failures, and unaided completion.
3. Run the four-week observation period on participating repositories.
4. Authorize calibration and freeze the study before held-out evaluation.
5. Complete the paper's full claim and citation audit, independent reproduction, and archived artifact.
6. Select a later venue, apply its actual template, and check its publicity rules.
7. Record the demonstration and prepare two consented case studies.
8. Authorize publication and community contact separately.

Record an anonymous participant ID, repository ID or consented link, setup
minutes, assistance required, first completed task date, each active week,
setup failures, API and execution costs, retained/removed lessons, and continued
use or withdrawal reason. Track external contributions and citations. Stars are
a secondary attention metric. Do not install undisclosed telemetry.

## Draft demonstration script

Use [the fixed evaluation example](../examples/github-pytest/README.md). Show the
lesson and ticket, the authentication-retry defect, the one-line fix, the two
actual JUnit logs, the settlement report with commit/run identity, and the
updated dashboard. State that delta `1` is a test transition, not measured
savings or causal proof. Link the exact example and reviewed revision. A video
and public case studies are deferred until the initial external pilot.

## Draft technical launch post

> darwin-memo connects repository lessons to reported task outcomes and makes
> retention decisions inspectable. The Python/pytest example compares one fixed
> evaluation across two commits; CI settles the bound ticket and preserves its
> report hashes. The research artifact reconstructs a feedback-corruption table,
> including settings where a tuned counter competes and where the ledger fails.
> We have not established lower total coding cost with preserved task success.

Keep this as a draft until pilot evidence and venue publicity rules are reviewed.
