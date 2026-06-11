# Animoca Minds (EVM settler shipped; Minds driver pending access)

Animoca Minds (animocaminds.ai, launched February 2026 with Ethoswarm)
runs persistent cloud agents ("Minds") with on-chain wallets. Its
Builder API shipped June 2026 and currently covers messaging only.

## Why it is interesting for darwin-memo

On-chain environments are unusually good selection pressure, because
the signals are conserved and judge-free by construction: balance
deltas, transaction success or failure, and gas spent are readable from
any RPC node without anyone's permission. That is precisely the
`settle(measured_delta)` shape the Ledger wants, and it needs nothing
from the Minds API at all: only a wallet address.

## Shipped: the generic EVM settler

The durable, platform-agnostic piece from the original plan exists:
`darwin_memo.EvmSettler` (zero dependencies, stdlib JSON-RPC). One
settler measures one conserved resource for one address — native wei,
or one ERC-20's raw units. The intended flow needs no archive node:

```python
from darwin_memo import EvmSettler

settler = EvmSettler("0xWALLET")            # Base mainnet by default
before = settler.snapshot()
ticket = ledger.decide("Should the agent take this job?")
# ...the agent acts, the outcome lands on-chain...
ledger.settle(ticket.id, settler.delta(before, settler.snapshot()))
```

`examples/08_evm_settler.py` runs the loop offline against an
in-process fake chain (`--live` reads real Base). `block_at`/`measure`
support retroactive wall-clock windows via timestamp bisection, which
needs archive state; `tx_cost` measures a single transaction (status,
value, and gas — including the OP-stack `l1Fee`, without which gas
does not conserve against the actual balance movement).

What was verified by execution on 2026-06-11, and is documented in the
module docstring because it is load-bearing:

- `https://mainnet.base.org` (the default RPC) served full archive
  state back to block 1, unauthenticated, ~300 ms per call.
- `base-rpc.publicnode.com` silently serves historical state from the
  WRONG block (minutes to days late, HTTP 200, no error): never use it
  for historical reads. `1rpc.io/base` alternates archive and pruned
  backends nondeterministically. `base.llamarpc.com` was down.
- Public RPC fronts reject Python's default User-Agent (HTTP 403); the
  client sends its own.
- The chain is configurable (`EvmRpc(url)`): Minds documentation says
  "chains like Ethereum and Base" without pinning one.

## The Minds Builder API, as measured (2026-06-11)

Base URL `https://api.build.hellominds.ai` (the `api.hellominds.ai`
host does not resolve). Live OpenAPI spec, no auth required:
`https://api.build.hellominds.ai/docs/openapi.json` (v2.2.0). Auth is
an API key from the Builder console (shown once, default TTL 90 days)
sent as `X-Builder-Api-Key` — the spec still documents the deprecated
`X-Access-Key`, and the official client sends both, so send both.
Messaging endpoints exist (list Minds, send message, SSE event
stream); the SSE stream has no event names, echoes your own messages
back, and emits `: ping` comment lines that naive parsers choke on.

What still does not exist, verified: `/v1/wallets`, `/v1/credits`, and
`/v1/memory` all 404, and the Mind object carries no wallet field. So
**a Mind's wallet address must come out-of-band** (the consumer app's
profile/top-up flow, asking the Mind, or programme access) — once you
have it, the settler above needs nothing else. The official npm client
remains UNLICENSED with no public repo; do not depend on it.

## Remaining steps

1. **Builder API driver** (REST + SSE from Python): deferred until
   there is a key to test against — the surface is days old and
   already drifting (header rename mid-flight); building blind against
   it would be guesswork with an expiry date.
2. **Apply to the builder programme** (build.hellominds.ai/program):
   the realistic route to wallet/credit endpoints, and the unblock for
   the driver. This step is a human's.
3. Wire the Ledger once 1-2 land: `decide()` on dispatching a task to
   a Mind, `settle()` from the EVM settler, `tick()` on cron — the
   same three calls as every other integration.

The original honest assessment stands: the platform-specific work can
churn or die; the settler cannot, because chains do not retire their
RPCs.
