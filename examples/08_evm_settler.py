"""On-chain settlement: a wallet balance as the conserved resource.

Runs fully offline against an in-process fake chain so CI needs no
network; pass --live to read real Base mainnet instead (read-only,
no keys). Either way the flow is the same three lines that matter:
snapshot when you decide, snapshot when the outcome lands, settle the
difference. No judge anywhere; the chain just responds.

    python examples/08_evm_settler.py [--live]
"""

import json
import sys
import threading
import typing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from darwin_memo import EvmRpc, EvmSettler, Ledger, MemoryEntry, MemoryStore

WALLET = "0x2d5cd0905f246688b75f57f2e88d2b18e67407cc"


class FakeChain(BaseHTTPRequestHandler):
    """Three RPC methods and a balance that grows: enough to settle."""

    head = 100
    balances: typing.ClassVar = {100: 10_000, 160: 14_500}  # job pays 4,500 wei

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method, params = payload["method"], payload["params"]
        if method == "eth_blockNumber":
            result = hex(FakeChain.head)
        elif method == "eth_getBalance":
            result = hex(self.balances.get(int(params[1], 16), 0))
        else:
            raise AssertionError(method)
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


live = "--live" in sys.argv
if live:
    settler = EvmSettler(WALLET)
    print(f"reading Base mainnet for {WALLET}")
else:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeChain)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    rpc = EvmRpc(f"http://127.0.0.1:{server.server_address[1]}")
    settler = EvmSettler(WALLET, rpc=rpc)
    print("running against an in-process fake chain (pass --live for Base)")

store = MemoryStore()
store.add(
    MemoryEntry(
        question="Is the indexing job worth taking?",
        answer="The indexing job is safe to apply and pays reliably.",
        sources=["operator-notes"],
    )
)
ledger = Ledger(store, resource_scale=1_000.0)

before = settler.snapshot()
ticket = ledger.decide("Should the agent take the indexing job?")
print(f"decide -> {ticket.answer[:60]!r} (ticket {ticket.id})")
print(f"snapshot before: block {before['block']}, balance {before['balance']}")

# ...the agent does the job; on the fake chain the payment lands...
if not live:
    FakeChain.head = 160

after = settler.snapshot()
delta = settler.delta(before, after)
ledger.settle(ticket.id, delta, detail=f"balance moved {delta:+.0f} wei on-chain")
print(f"snapshot after:  block {after['block']}, balance {after['balance']}")
print(f"settled at delta {delta:+.0f}")

entry = store.alive()[0]
print(f"entry energy now {entry.energy:.3f} (spawned at 1.0)")
