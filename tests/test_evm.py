"""EVM settler against a stdlib fake RPC node. No network."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from darwin_memo.evm import EvmRpc, EvmRpcError, EvmSettler

ADDR = "0x" + "ab" * 20
TOKEN = "0x" + "cd" * 20
HEAD = 1000
GENESIS_TS = 1_700_000_000  # 2-second blocks: ts(n) = GENESIS_TS + 2n


class FakeRpc(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, Any]]] = []
    headers_seen: ClassVar[list[str]] = []
    balances: ClassVar[dict[int, int]] = {}  # block -> native wei
    token_balances: ClassVar[dict[int, int]] = {}
    receipts: ClassVar[dict[str, dict[str, Any]]] = {}
    txs: ClassVar[dict[str, dict[str, Any]]] = {}
    error_mode: ClassVar[str | None] = None  # "pruned" | "plaintext"

    def do_POST(self):
        self.headers_seen.append(self.headers.get("User-Agent", ""))
        if FakeRpc.error_mode == "plaintext":
            body = b"error code: 521"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeRpc.requests.append(payload)
        if FakeRpc.error_mode == "pruned":
            self._reply(
                {"error": {"code": -32603, "message": "state at block #7 is pruned"}}
            )
            return
        self._reply({"result": self._result(payload["method"], payload["params"])})

    def _result(self, method: str, params: list[Any]) -> Any:
        if method == "eth_blockNumber":
            return hex(HEAD)
        if method == "eth_getBalance":
            return hex(self.balances.get(int(params[1], 16), 0))
        if method == "eth_call":
            block = int(params[1], 16) if params[1] != "latest" else HEAD
            data = params[0]["data"]
            if data.startswith("0x313ce567"):
                return "0x" + hex(6)[2:].rjust(64, "0")
            assert data == "0x70a08231" + ADDR[2:].rjust(64, "0"), (
                "balanceOf calldata must be selector + zero-padded address"
            )
            return "0x" + hex(self.token_balances.get(block, 0))[2:].rjust(64, "0")
        if method == "eth_getBlockByNumber":
            number = int(params[0], 16)
            if number > HEAD:
                return None
            return {"timestamp": hex(GENESIS_TS + 2 * number)}
        if method == "eth_getTransactionReceipt":
            return self.receipts.get(params[0])
        if method == "eth_getTransactionByHash":
            return self.txs.get(params[0])
        raise AssertionError(f"unexpected method {method}")

    def _reply(self, payload: dict[str, Any]) -> None:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, **payload}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_rpc():
    FakeRpc.requests = []
    FakeRpc.headers_seen = []
    FakeRpc.balances = {HEAD: 5_000_000, 500: 1_000_000, 0: 0}
    FakeRpc.token_balances = {HEAD: 223_613_995_120, 500: 100}
    FakeRpc.receipts = {}
    FakeRpc.txs = {}
    FakeRpc.error_mode = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRpc)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield EvmRpc(f"http://127.0.0.1:{server.server_address[1]}", timeout=5.0)
    server.shutdown()


def test_user_agent_is_never_pythons_default(fake_rpc):
    """Public RPC fronts 403 the default urllib UA; ours must be custom."""
    fake_rpc.block_number()
    assert FakeRpc.headers_seen
    for agent in FakeRpc.headers_seen:
        assert "python-urllib" not in agent.lower()
        assert agent, "User-Agent header must be present"


def test_snapshot_pins_a_concrete_block(fake_rpc):
    settler = EvmSettler(ADDR, rpc=fake_rpc)
    snap = settler.snapshot()
    assert snap == {"block": HEAD, "balance": 5_000_000}
    # The read went to an explicit hex tag, never the floating 'latest'.
    balance_calls = [r for r in FakeRpc.requests if r["method"] == "eth_getBalance"]
    assert balance_calls[0]["params"][1] == hex(HEAD)


def test_delta_native_and_token(fake_rpc):
    native = EvmSettler(ADDR, rpc=fake_rpc)
    assert native.delta(native.snapshot(500), native.snapshot(HEAD)) == 4_000_000.0

    token = EvmSettler(ADDR, rpc=fake_rpc, token=TOKEN)
    before, after = token.snapshot(500), token.snapshot(HEAD)
    assert token.delta(before, after) == float(223_613_995_120 - 100)
    assert token.token_decimals() == 6


def test_block_at_bisects_clamped_to_head(fake_rpc):
    settler = EvmSettler(ADDR, rpc=fake_rpc)
    # ts of block 321 exactly, and one second into block 321's slot.
    assert settler.block_at(GENESIS_TS + 2 * 321) == 321
    assert settler.block_at(GENESIS_TS + 2 * 321 + 1) == 321
    # Beyond the head clamps to head; before genesis clamps to 0.
    assert settler.block_at(GENESIS_TS + 10 * HEAD) == HEAD
    assert settler.block_at(GENESIS_TS - 5) == 0


def test_measure_window(fake_rpc):
    settler = EvmSettler(ADDR, rpc=fake_rpc)
    delta = settler.measure(GENESIS_TS + 2 * 500, GENESIS_TS + 2 * HEAD)
    assert delta == 4_000_000.0


def test_tx_cost_includes_l1_fee_and_handles_reverts(fake_rpc):
    FakeRpc.receipts["0xgood"] = {
        "status": "0x1",
        "gasUsed": hex(21_000),
        "effectiveGasPrice": hex(1_000),
        "l1Fee": hex(500_000),
    }
    FakeRpc.txs["0xgood"] = {"value": hex(7)}
    FakeRpc.receipts["0xbad"] = {
        "status": "0x0",
        "gasUsed": hex(21_000),
        "effectiveGasPrice": hex(1_000),
        "l1Fee": hex(500_000),
    }
    FakeRpc.txs["0xbad"] = {"value": hex(7)}
    FakeRpc.receipts["0xnol1"] = {
        "status": "0x1",
        "gasUsed": hex(10),
        "effectiveGasPrice": hex(10),
    }
    FakeRpc.txs["0xnol1"] = {"value": hex(0)}

    settler = EvmSettler(ADDR, rpc=fake_rpc)
    good = settler.tx_cost("0xgood")
    assert good == {"status": True, "gas_wei": 21_000 * 1_000 + 500_000, "value_wei": 7}
    bad = settler.tx_cost("0xbad")
    assert bad["status"] is False
    assert bad["gas_wei"] == good["gas_wei"], "reverts still burn full gas"
    assert bad["value_wei"] == 0, "reverts move no value"
    assert settler.tx_cost("0xnol1")["gas_wei"] == 100, "l1Fee optional off OP-stack"

    with pytest.raises(EvmRpcError, match="no receipt"):
        settler.tx_cost("0xmissing")


def test_pruned_state_is_loud(fake_rpc):
    FakeRpc.error_mode = "pruned"
    with pytest.raises(EvmRpcError, match="pruned") as info:
        EvmSettler(ADDR, rpc=fake_rpc).snapshot(7)
    assert info.value.code == -32603


def test_plaintext_body_is_loud(fake_rpc):
    FakeRpc.error_mode = "plaintext"
    with pytest.raises(EvmRpcError, match="non-JSON"):
        fake_rpc.block_number()


def test_address_validation():
    with pytest.raises(ValueError, match="not an EVM address"):
        EvmSettler("0x123")
    with pytest.raises(ValueError, match="not an EVM address"):
        EvmSettler(ADDR, token="bogus")
    assert EvmSettler(ADDR.upper().replace("0X", "0x")).address == ADDR


def test_connection_failures_are_wrapped():
    """DNS/refused/timeout surface as EvmRpcError, never bare OSError."""
    dead = EvmRpc("http://127.0.0.1:9", timeout=0.3)
    with pytest.raises(EvmRpcError, match="network error"):
        dead.block_number()


def test_empty_eth_call_return_is_loud(tmp_path, fake_rpc):
    """balanceOf against a codeless address returns '0x'; must not crash."""

    class EmptyCallRpc(EvmRpc):
        def __init__(self):
            super().__init__("http://fake")

        def call(self, method, params):
            if method == "eth_blockNumber":
                return hex(HEAD)
            return "0x"

    settler = EvmSettler(ADDR, rpc=EmptyCallRpc(), token=TOKEN)
    with pytest.raises(EvmRpcError, match="no contract code"):
        settler.snapshot()
    with pytest.raises(EvmRpcError, match="no contract code"):
        settler.token_decimals()


def test_tx_cost_missing_tx_body_is_loud(fake_rpc):
    FakeRpc.receipts["0xorphan"] = {
        "status": "0x1",
        "gasUsed": hex(10),
        "effectiveGasPrice": hex(10),
    }
    # No matching entry in FakeRpc.txs: eth_getTransactionByHash -> null.
    with pytest.raises(EvmRpcError, match="no transaction body"):
        EvmSettler(ADDR, rpc=fake_rpc).tx_cost("0xorphan")


# ----------------------------------------------------------------------
# Round 3: the documented "lies at HTTP 200" failure, made detectable
# ----------------------------------------------------------------------


class _StubRpc(EvmRpc):
    """A minimal EvmRpc: enough for a native-balance snapshot, no socket.

    Serves one fixed balance for every block, so two stubs with different
    balances model two endpoints disagreeing about the same block -- which is
    exactly what a wrong-block-state endpoint looks like next to an honest one.
    Subclasses EvmRpc (whose __init__ only stores url/timeout, no network) so
    it is a real EvmRpc to the type checker.
    """

    def __init__(self, url: str, balance: int, head: int = 1000) -> None:
        super().__init__(url)
        self._balance = balance
        self._head = head

    def block_number(self) -> int:
        return self._head

    def call(self, method: str, params: list[Any]) -> Any:
        assert method == "eth_getBalance"
        return hex(self._balance)


def test_a_second_endpoint_that_disagrees_refuses_to_settle() -> None:
    """The module's docstring warns that some endpoints serve wrong-block state
    at HTTP 200; verify_rpc turns that silent lie into a hard error instead of
    a confidently wrong delta that credits or damages entries on fiction.

    Mutation: drop the verify_rpc comparison and this settles on the honest
    endpoint's number, never noticing the liar.
    """
    honest = _StubRpc("https://honest", balance=5_000)
    liar = _StubRpc("https://liar", balance=9_999)  # wrong-block state
    settler = EvmSettler(ADDR, rpc=honest, verify_rpc=liar)
    with pytest.raises(EvmRpcError, match="disagrees across endpoints"):
        settler.snapshot(block=1000)


def test_two_agreeing_endpoints_snapshot_normally() -> None:
    a = _StubRpc("https://a", balance=5_000)
    b = _StubRpc("https://b", balance=5_000)
    settler = EvmSettler(ADDR, rpc=a, verify_rpc=b)
    snap = settler.snapshot(block=1000)
    assert snap == {"block": 1000, "balance": 5_000}


def test_without_verify_rpc_behaviour_is_unchanged() -> None:
    """Opt-in: a single trusted endpoint still works with no second opinion."""
    snap = EvmSettler(ADDR, rpc=_StubRpc("https://solo", balance=42)).snapshot(block=7)
    assert snap == {"block": 7, "balance": 42}
