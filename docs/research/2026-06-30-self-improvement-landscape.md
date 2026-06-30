# Environment-mediated self-improvement: 2025–2026 landscape & where darwin-memo fits

**Date:** 2026-06-30. Source: deep-research run (106 agents, 24 primary sources, 25/25 claims verified). All numbers as-of each paper's publication — **re-pull live leaderboards before claiming a beat (SOTA drifts monthly).**

## The headline insight (and it validates our finding)

The field has converged: **methods that actually move real-benchmark numbers change WEIGHTS (RL-from-verifiable-rewards / rejection-sampling SFT on execution outcomes) or synthesize RUNTIME TOOLS — not advisory context.** This independently confirms darwin-memo's measured result. SWE-Gym went further and found *pure on-policy self-improvement regressed* (Lite 15.3%→8.7%). The field is independently arriving at our conclusion (StuLife/ELL: "rather than merely retrieving past experiences, agents must abstract generalizable skills").

So the question isn't "does memory help" — it's **where learning should live: parameters or tools, not context.**

## Verified reference points on SWE-bench Verified (the canonical target)

| Method | arXiv | Signal | Result | Fit to our constraints |
|---|---|---|---|---|
| **SWE-Gym** (rejection-sampling SFT on 491 unit-test-verified trajectories) | 2412.21139 | unit-test pass/fail | 32B Coder **7%→20.6%** Verified (+13.6); +verifier rerank → 32% | **Cheapest published no-RL, no-judge win.** Caveat: 491 trajectories were *teacher*-generated (gpt-4o/claude-3.5) then test-filtered, not self-generated |
| Nebius pure execution RL | 2508.03501 | terminal test pass=1/0 | Qwen-72B **11%→39%** | Cleanest no-judge, but needs real RL infra |
| Self-Play SWE-RL (SSR) | 2512.18552 | binary verifiable; self-play bug-inject/repair, no NL issues | **+10.4** Verified | Purest no-judge/no-RM fit; frontier-scale RL |
| Agent-RLVR | 2506.11425 | unit-test RLVR | 9.4%→**22.4%** | Partial fit (best 27.8% uses a reward model; train-time LLM guidance) |
| **Live-SWE-agent** (runtime tool synthesis) | 2511.13646 | reflection + execution, no weights/judge/RM | **75.4%** Verified (Claude 4.5); 65% vs DGM 53.3%/HGM 56.7% on the 60-problem self-improving-agent set, **zero offline cost** | Weight-free; tools are **within-issue only (not persisted cross-task)** → extension opening |
| "Survival is the Only Reward" (our lineage) | 2601.12310 | conserved resource, binary survival | proof-of-concept, **NO benchmark number** | Validates the regime; the missing piece IS the publishing bar |

## The white space (keeps darwin-memo's spirit: verifiable signal, no judge, cheap)

Two candidate pivots, both moving selection from advisory text to where it bites:

**(A) Parametric data-filter** — move the energy-ledger *selection* from text entries to **filtering trajectories for cheap rejection-sampling SFT**. This is literally an extension of darwin-memo's *existing* `bench/distill` arm (survivor-distillation, already shown to work on a toy corpus), scaled to a real benchmark. Cheap relative to RL (filtered SFT, not PPO/GRPO). Needs GPU SFT for a 32B base.

**(B) Persistent verified tool library** — extend Live-SWE-agent (which discards tools after each issue) into a **cross-task skill/tool library where a tool survives only if it demonstrably passes a conserved environmental check.** Weight-free (no GPU training), frontier API + tool synthesis. More agent engineering.

## The single cheapest, most publishable experiment (nobody has run it)

**A/B on the SWE-Gym 491-trajectory protocol:** darwin-memo's conserved-signal *survival* selection vs plain unit-test pass/fail rejection-sampling, same base 32B model, same trajectory budget, scored on SWE-bench Verified/Lite. Question: **does conserved-signal selection beat naive pass/fail filtering at fixed budget?** Reproducible baseline (SWE-Gym 7%→20.6%), real benchmark, novel unanswered question, keeps every constraint.

## The load-bearing open question (answer cheaply first)

**Does "capable agents override memory" also kill tools and distilled weights, or ONLY advisory text?** Live-SWE (tools) and Nebius/SSR (weights) both move numbers — strongly suggesting the override is specific to *context*, not tools/parameters. Confirming this decides A vs B. A cheap probe (does a *synthesized tool* get used where an *injected lesson* doesn't?) de-risks the whole direction.

## Hard caveats (carry into any claim)

- **SOTA drift:** SWE-Gym's 32% was open-weight SOTA Dec-2024; superseded by mid-2026 (~37%+: OpenHands-LM, R2E-Gym, Skywork-SWE). Re-pull the live leaderboard before claiming a beat.
- **Not apples-to-apples:** results mix base models, scaffolds, pass@1 vs pass@k, full vs subset. A 5.2-pt spread comes from scaffold alone on the same model.
- **The cheap SWE-Gym win used teacher trajectories** (distillation-under-verification), and the *self-generated* variant regressed. So our edge must be in the *selection rule*, not "self-generation."
- **SSR/Nebius need real RL infra** — not "cheap/small-team." The cheap darwin-memo-compatible path is rejection-sampling SFT (A), or weight-free tools (B).
