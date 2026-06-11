# Animoca Minds (plan)

Animoca Minds (animocaminds.ai, launched February 2026 with Ethoswarm)
runs persistent cloud agents ("Minds") with on-chain wallets on Base.
Its Builder API, npm client, and CLI shipped in June 2026 and currently
cover messaging only: list Minds, converse, stream events. No wallet,
credits, or memory endpoints exist yet, and there is no MCP support.

## Why it is interesting for darwin-memo

On-chain environments are unusually good selection pressure, because
the signals are conserved and judge-free by construction: token balance
deltas, transaction success or failure, and gas spent are readable from
any Base RPC without anyone's permission. That is precisely the
`settle(measured_delta)` shape the Ledger wants, and it needs nothing
from the Minds API at all: only the Mind's wallet address.

## The plan (a 2-3 day spike, not a deep bet yet)

1. **Generic EVM settler** (the durable piece, Minds-agnostic): given a
   wallet address and a ticket window, compute the measured delta from
   Base RPC: native and ERC-20 balance changes, receipt status, gas.
   This component works for any on-chain agent, not just Minds.
2. **Builder API driver**: plain REST + SSE from Python (send message,
   wait for reply). The official npm client is UNLICENSED with no
   public repo, so darwin-memo will not depend on it; the HTTP surface
   is small and documented.
3. **Wire the Ledger**: `decide()` when dispatching a task to the Mind,
   `settle()` from the EVM settler, `tick()` on cron.
4. Apply to the Minds $10M builder programme: outcome-settled agent
   memory is squarely inside their stated thesis, and programme access
   is the realistic route to the missing wallet and credit endpoints.

## Honest assessment

Real corporate commitment (Animoca's stated top priority, real
engineering artifacts, a $10M programme already writing checks) AND a
two-day-old, messaging-only, token-adjacent developer surface with an
UNLICENSED SDK. The platform-specific work can churn or die; the EVM
settler cannot, because chains do not retire their RPCs. Build the
settler first, treat Minds as the first of several EVM-agent targets,
and re-evaluate when wallet and credit endpoints land in the Builder
API.
