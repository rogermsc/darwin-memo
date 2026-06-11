"""EVM settlement: an on-chain balance as the conserved resource.

On-chain environments are unusually good selection pressure because the
signals are conserved and judge-free by construction: a wallet's
balance delta, a transaction's success, and the gas it burned are
readable from any RPC node without anyone's permission. This module
turns those readings into ``Ledger.settle`` deltas with zero
dependencies (stdlib urllib JSON-RPC, same house style as the Ollama
client).

One settler measures ONE conserved resource for ONE address: the
chain's native currency in wei, or a single ERC-20 token's raw units
when ``token`` is given. Mixing assets into one number would not be a
measurement of anything; use one settler per resource.

The intended flow needs no archive node at all: snapshot when you
decide, snapshot when the outcome lands, settle the difference::

    settler = EvmSettler("0x...")          # Base mainnet by default
    before = settler.snapshot()
    ticket = ledger.decide("Should the agent take this job?")
    ...the agent acts on-chain, time passes...
    ledger.settle(ticket.id, settler.delta(before, settler.snapshot()))

Retroactive windows (``block_at``/``measure``) read historical state
and therefore need an archive-grade endpoint. Everything below was
verified by execution against Base mainnet on 2026-06-11:

- ``https://mainnet.base.org`` (the default) served full archive state
  back to block 1 in every probe, at ~300 ms per call, unauthenticated.
- ``base-rpc.publicnode.com`` SILENTLY serves historical state from the
  wrong block (minutes to days later than requested, HTTP 200, no
  error). Never use it for historical reads; a settler pointed there
  produces wrong deltas with no failure signal.
- ``1rpc.io/base`` round-robins archive and pruned backends: the same
  historical query alternates between a correct answer and a
  ``-32603 state ... is pruned`` error. Usable with retries, never as
  proof of anything.
- A custom User-Agent is mandatory: the default Python-urllib UA is
  rejected (HTTP 403, plain-text body) by the Cloudflare in front of
  every public endpoint tested.
- Gas conservation on OP-stack chains (Base, Optimism) requires the
  receipt's ``l1Fee`` on top of ``gasUsed * effectiveGasPrice``;
  ``tx_cost`` includes it. Reverted transactions still burn both.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_RPC = "https://mainnet.base.org"

# Public RPC fronts reject Python's default User-Agent outright
# (verified: HTTP 403 "error code: 1010" on every endpoint tested).
_USER_AGENT = "darwin-memo-evm/1"

_BALANCE_OF = "0x70a08231"  # balanceOf(address)
_DECIMALS = "0x313ce567"  # decimals()


class EvmRpcError(RuntimeError):
    """An RPC request failed, with the node's own message attached.

    Failures must be loud: public endpoints answer with plain-text
    Cloudflare bodies, JSON-RPC errors inside HTTP 200s (pruned state
    is ``-32603``), and JSON-RPC errors inside HTTP 403s. A swallowed
    error here would settle a wrong delta with no failure signal.
    """

    def __init__(self, message: str, code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.body = body


class EvmRpc:
    """Minimal JSON-RPC client over stdlib urllib."""

    def __init__(self, url: str = DEFAULT_BASE_RPC, timeout: float = 30.0) -> None:
        self.url = url
        self.timeout = timeout
        self._request_id = 0

    def call(self, method: str, params: list[Any]) -> Any:
        self._request_id += 1
        request = urllib.request.Request(
            self.url,
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": method,
                    "params": params,
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            # Some fronts wrap a JSON-RPC error in an HTTP error status.
            failure = self._rpc_error(body)
            if failure is not None:
                raise failure from error
            raise EvmRpcError(
                f"{self.url} returned HTTP {error.code} for {method}: "
                f"{body[:200] or error.reason}",
                code=error.code,
                body=body,
            ) from error
        except OSError as error:
            # URLError (DNS, refused, TLS) and raw read timeouts are
            # both OSError subclasses; the loud-failure contract says
            # every transport failure surfaces as EvmRpcError, never a
            # bare socket exception a caller did not sign up to catch.
            raise EvmRpcError(
                f"network error calling {method} on {self.url}: {error}"
            ) from error

        failure = self._rpc_error(body)
        if failure is not None:
            raise failure
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise EvmRpcError(
                f"non-JSON response from {self.url} for {method}: {body[:200]}",
                body=body,
            ) from error
        if "result" not in payload:
            raise EvmRpcError(
                f"no result from {self.url} for {method}: {body[:200]}", body=body
            )
        return payload["result"]

    def _rpc_error(self, body: str) -> EvmRpcError | None:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            error = payload["error"]
            return EvmRpcError(
                f"RPC error from {self.url}: {error.get('message', '')} "
                f"(code {error.get('code', 0)})",
                code=int(error.get("code", 0)),
                body=body,
            )
        return None

    # ------------------------------------------------------------------

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def block_timestamp(self, block: int) -> int:
        result = self.call("eth_getBlockByNumber", [hex(block), False])
        if result is None:
            raise EvmRpcError(f"block {block} not found on {self.url}")
        return int(result["timestamp"], 16)


def _decode_uint(raw: str, contract: str, call: str) -> int:
    """Decode an eth_call uint256, loudly.

    A call to an address with no deployed code returns "0x" (empty
    data), and ``int("0x", 16)`` is a ValueError; a wrong token address
    must read as a measurement failure, not a Python crash.
    """
    if raw in ("0x", "", None):
        raise EvmRpcError(
            f"empty return data from {call} on {contract}: no contract "
            "code at that address?"
        )
    return int(raw, 16)


def _validate_address(address: str) -> str:
    addr = address.lower()
    if not addr.startswith("0x") or len(addr) != 42:
        raise ValueError(f"not an EVM address: {address!r}")
    int(addr, 16)
    return addr


class EvmSettler:
    """Measure one conserved on-chain resource for one address.

    ``token=None`` measures the native currency in wei; passing an
    ERC-20 contract address measures that token's raw units (scale
    ``resource_scale`` accordingly: USDC has 6 decimals, most tokens
    18 — see ``token_decimals``).
    """

    def __init__(
        self,
        address: str,
        rpc: EvmRpc | None = None,
        token: str | None = None,
    ) -> None:
        self.rpc = rpc or EvmRpc()
        self.address = _validate_address(address)
        self.token = _validate_address(token) if token else None

    # ------------------------------------------------------------------
    # Snapshots: the no-archive-needed path
    # ------------------------------------------------------------------

    def snapshot(self, block: int | None = None) -> dict[str, int]:
        """The measured balance, pinned to a concrete block number.

        ``block=None`` resolves the current head FIRST and reads at that
        height, so two snapshots are always comparable measurements of
        specific moments, never floating 'latest' reads.
        """
        if block is None:
            block = self.rpc.block_number()
        tag = hex(block)
        if self.token is None:
            balance = int(self.call_balance(tag), 16)
        else:
            data = _BALANCE_OF + self.address[2:].rjust(64, "0")
            raw = self.rpc.call("eth_call", [{"to": self.token, "data": data}, tag])
            balance = _decode_uint(raw, self.token, "balanceOf")
        return {"block": block, "balance": balance}

    def call_balance(self, tag: str) -> str:
        result: str = self.rpc.call("eth_getBalance", [self.address, tag])
        return result

    @staticmethod
    def delta(before: dict[str, int], after: dict[str, int]) -> float:
        """The conserved-resource movement between two snapshots.

        Float because that is ``Ledger.settle``'s signature. Exact up
        to 2**53 raw units; above that (about 0.009 of an 18-decimals
        token) float64 rounds, which is harmless for credit (tanh
        normalizes) but means wei-true accounting should read the
        snapshots' int balances directly. ``measure`` inherits this.
        """
        return float(after["balance"] - before["balance"])

    # ------------------------------------------------------------------
    # Historical windows: archive-dependent
    # ------------------------------------------------------------------

    def block_at(self, timestamp: int) -> int:
        """The last block at or before ``timestamp``, by bisection.

        Clamped to the current head (asking past the head is a
        ``block not found`` error on real nodes, measured), and to
        block 0 for timestamps before the chain.
        """
        head = self.rpc.block_number()
        if self.rpc.block_timestamp(head) <= timestamp:
            return head
        lo, hi = 0, head  # invariant: ts(lo) <= timestamp < ts(hi)
        if self.rpc.block_timestamp(0) > timestamp:
            return 0
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.rpc.block_timestamp(mid) <= timestamp:
                lo = mid
            else:
                hi = mid
        return lo

    def measure(self, start_timestamp: int, end_timestamp: int) -> float:
        """Balance delta over a wall-clock window. Needs archive state
        for the window's depth; the default endpoint served full
        archive when verified, but see the module docstring for the
        endpoints that lie or lotto about history."""
        before = self.snapshot(self.block_at(start_timestamp))
        after = self.snapshot(self.block_at(end_timestamp))
        return self.delta(before, after)

    # ------------------------------------------------------------------
    # Transaction-level measurement
    # ------------------------------------------------------------------

    def tx_cost(self, tx_hash: str) -> dict[str, Any]:
        """What one transaction measurably did: success, value, gas.

        ``gas_wei`` includes the OP-stack ``l1Fee`` when the receipt
        carries one (Base, Optimism); omitting it breaks conservation
        against the actual balance movement (verified to the wei). A
        reverted transaction still burns the full gas but moves no
        value.
        """
        receipt = self.rpc.call("eth_getTransactionReceipt", [tx_hash])
        if receipt is None:
            raise EvmRpcError(f"no receipt for {tx_hash} on {self.rpc.url}")
        tx = self.rpc.call("eth_getTransactionByHash", [tx_hash])
        if tx is None:
            raise EvmRpcError(f"no transaction body for {tx_hash} on {self.rpc.url}")
        status = int(receipt["status"], 16) == 1
        gas = int(receipt["gasUsed"], 16) * int(receipt["effectiveGasPrice"], 16)
        gas += int(receipt.get("l1Fee", "0x0"), 16)
        return {
            "status": status,
            "gas_wei": gas,
            "value_wei": int(tx["value"], 16) if status else 0,
        }

    def token_decimals(self) -> int:
        """The token's decimals, for choosing a sane resource_scale."""
        if self.token is None:
            return 18
        raw = self.rpc.call(
            "eth_call", [{"to": self.token, "data": _DECIMALS}, "latest"]
        )
        return _decode_uint(raw, self.token, "decimals")
