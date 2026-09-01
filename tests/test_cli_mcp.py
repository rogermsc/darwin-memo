"""CLI commands and the MCP server (the latter skipped without the extra)."""

import json
import sys

import pytest

from darwin_memo.cli import main as cli_main


def test_cli_demo_kills_poison(tmp_path, capsys):
    out = tmp_path / "survivors.json"
    assert cli_main(["demo", "--cycles", "30", "-o", str(out)]) == 0
    output = capsys.readouterr().out
    assert "Poisoned entries still alive: 0" in output
    assert "executed" in output and "starved" in output
    assert out.exists()


def test_cli_encode_query_stats_roundtrip(tmp_path, capsys):
    doc = tmp_path / "notes.txt"
    doc.write_text(
        "The ingest queue may be drained after backfill completes. "
        "The ledger table is protected and must be retained."
    )
    memory = tmp_path / "m.json"

    assert cli_main(["encode", str(doc), "-o", str(memory)]) == 0
    assert cli_main(["query", str(memory), "can I drain the ingest queue?"]) == 0
    assert "drained" in capsys.readouterr().out

    assert cli_main(["stats", str(memory)]) == 0
    assert "alive:" in capsys.readouterr().out


def test_cli_query_reports_silence(tmp_path, capsys):
    doc = tmp_path / "notes.txt"
    doc.write_text("The ingest queue may be drained after backfill completes.")
    memory = tmp_path / "m.json"
    cli_main(["encode", str(doc), "-o", str(memory)])
    capsys.readouterr()

    assert cli_main(["query", str(memory), "qual e a capital da Franca?"]) == 0
    assert "silent" in capsys.readouterr().out


def test_cli_encode_missing_file(tmp_path, capsys):
    assert cli_main(["encode", str(tmp_path / "nope.txt")]) == 1


def test_mcp_server_full_cycle(tmp_path):
    # Guard the module build_server actually imports, not the top-level
    # package: mcp 2.0.0 ships "mcp" while removing this submodule, so
    # guarding on "mcp" lets the test run and die inside build_server.
    pytest.importorskip("mcp.server.fastmcp")
    import asyncio

    from darwin_memo.mcp_server import build_server

    path = tmp_path / "memory.json"
    server = build_server(path, resource_scale=2.0)

    async def scenario():
        tools = {t.name for t in await server.list_tools()}
        assert {
            "memory_query",
            "memory_settle",
            "memory_add",
            "memory_tick",
            "memory_stats",
            "memory_obituary",
        } <= tools

        await server.call_tool(
            "memory_add",
            {
                "question": "Is the nightly job safe to skip?",
                "answer": "The nightly job is redundant and safe to skip.",
                "source": "runbook",
            },
        )
        blocks, _ = await server.call_tool(
            "memory_query", {"query": "can I skip the nightly job?"}
        )
        payload = json.loads(blocks[0].text)
        assert payload["answer"] and payload["ticket_id"]

        await server.call_tool(
            "memory_settle",
            {"ticket_id": payload["ticket_id"], "delta": 3.0, "detail": "saved 40m"},
        )
        blocks, _ = await server.call_tool("memory_stats", {})
        stats = json.loads(blocks[0].text)
        assert stats["alive"] == 1
        assert stats["total_energy"] > 1.0, "settlement credited the entry"

    asyncio.run(scenario())
    assert path.exists(), "state persists across calls"


def test_cli_mcp_subcommand_runs_the_server(tmp_path, monkeypatch):
    """`darwin-memo mcp` starts the same server as darwin-memo-mcp.

    Registry clients construct `uvx [runtimeArguments] darwin-memo@VERSION
    [packageArguments]`, which lands on the main CLI; the mcp subcommand
    is what makes that launch work. build_server is faked so no stdio
    loop starts and the test needs neither the extra nor a network.
    """
    calls = {}

    class FakeServer:
        def run(self):
            calls["ran"] = True

    def fake_build(memory_path, resource_scale):
        calls["memory_path"] = memory_path
        calls["resource_scale"] = resource_scale
        return FakeServer()

    monkeypatch.setattr("darwin_memo.mcp_server.build_server", fake_build)
    memory = tmp_path / "memory.json"
    assert cli_main(["mcp", "--memory", str(memory), "--resource-scale", "2.0"]) == 0
    assert calls == {"ran": True, "memory_path": memory, "resource_scale": 2.0}


def test_cli_mcp_subcommand_honors_darwin_memo_path(tmp_path, monkeypatch):
    calls = {}

    class FakeServer:
        def run(self):
            calls["ran"] = True

    def fake_build(memory_path, resource_scale):
        calls["memory_path"] = memory_path
        return FakeServer()

    monkeypatch.setenv("DARWIN_MEMO_PATH", str(tmp_path / "from-env.json"))
    monkeypatch.setattr("darwin_memo.mcp_server.build_server", fake_build)
    assert cli_main(["mcp"]) == 0
    assert calls["memory_path"] == tmp_path / "from-env.json"


def test_cli_mcp_without_extra_names_the_install(tmp_path, monkeypatch):
    """Missing [mcp] extra exits with the exact pip command to run."""
    for name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
        monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["mcp", "--memory", str(tmp_path / "memory.json")])
    assert 'pip install "darwin-memo[mcp]"' in str(excinfo.value)


def _ledger_json(capsys, argv):
    assert cli_main(argv) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_ledger_full_cycle(tmp_path, capsys):
    """add -> decide -> settle -> tick -> obituary, all through the CLI."""
    memory = str(tmp_path / "nested" / "ledger.json")

    added = _ledger_json(
        capsys,
        [
            "ledger",
            memory,
            "add",
            "Is the nightly job safe to skip?",
            "The nightly job is redundant and safe to skip.",
            "--source",
            "runbook",
        ],
    )
    assert added["entry_id"]

    decided = _ledger_json(
        capsys,
        ["ledger", memory, "--scale", "2.0", "decide", "can I skip the nightly job?"],
    )
    assert decided["answer"] and decided["ticket_id"] and not decided["silent"]

    settled = _ledger_json(
        capsys,
        [
            "ledger",
            memory,
            "--scale",
            "2.0",
            "settle",
            decided["ticket_id"],
            "3.0",
            "--detail",
            "saved 40 minutes",
        ],
    )
    assert settled["settled"] is True
    assert _ledger_json(
        capsys, ["ledger", memory, "settle", decided["ticket_id"], "3.0"]
    ) == {"settled": False}, "duplicate delivery is reported, not re-credited"

    stats = _ledger_json(capsys, ["ledger", memory, "stats"])
    assert stats["alive"] == 1 and stats["pending_tickets"] == 0
    assert stats["total_energy"] > 1.0, "settlement credited the entry"

    ticked = _ledger_json(capsys, ["ledger", memory, "tick"])
    assert ticked["tick"] == 1

    obit = _ledger_json(capsys, ["ledger", memory, "obituary", added["entry_id"]])
    assert "credit" in obit["obituary"]


def test_cli_ledger_silent_decide_abandon_forget(tmp_path, capsys):
    memory = str(tmp_path / "ledger.json")

    decided = _ledger_json(capsys, ["ledger", memory, "decide", "anything?"])
    assert decided == {"answer": None, "ticket_id": None, "silent": True}

    added = _ledger_json(
        capsys,
        [
            "ledger",
            memory,
            "add",
            "Is the cache disposable?",
            "The cache is disposable and safe to remove.",
        ],
    )
    decided = _ledger_json(
        capsys, ["ledger", memory, "decide", "is the cache safe to remove?"]
    )
    assert decided["ticket_id"]
    assert _ledger_json(
        capsys, ["ledger", memory, "abandon", decided["ticket_id"]]
    ) == {"abandoned": True}

    assert _ledger_json(capsys, ["ledger", memory, "forget", added["entry_id"]]) == {
        "forgotten": True
    }
    assert _ledger_json(capsys, ["ledger", memory, "forget", added["entry_id"]]) == {
        "forgotten": False
    }, "already buried"
    assert _ledger_json(capsys, ["ledger", memory, "stats"])["alive"] == 0


def test_cli_ledger_forget_refuses_escrowed_entries(tmp_path, capsys):
    """Burying an escrowed entry would falsify a later settlement."""
    memory = str(tmp_path / "ledger.json")
    added = _ledger_json(
        capsys,
        [
            "ledger",
            memory,
            "add",
            "Is the cache disposable?",
            "The cache is disposable and safe to remove.",
        ],
    )
    decided = _ledger_json(
        capsys, ["ledger", memory, "decide", "is the cache safe to remove?"]
    )
    assert decided["ticket_id"]

    refused = _ledger_json(capsys, ["ledger", memory, "forget", added["entry_id"]])
    assert refused == {"forgotten": False, "reason": "escrowed by a pending ticket"}

    settled = _ledger_json(
        capsys, ["ledger", memory, "settle", decided["ticket_id"], "2.0"]
    )
    assert settled["settled"] is True
    stats = _ledger_json(capsys, ["ledger", memory, "stats"])
    assert stats["total_energy"] > 1.0, "the credit landed on a live entry"

    # Escrow released: now forget works.
    assert (
        _ledger_json(capsys, ["ledger", memory, "forget", added["entry_id"]])[
            "forgotten"
        ]
        is True
    )


def test_cli_ledger_writes_the_shared_event_log(tmp_path, capsys):
    """CLI ops append to the same .events.jsonl the MCP server uses."""
    memory = tmp_path / "ledger.json"
    _ledger_json(capsys, ["ledger", str(memory), "add", "Is X safe?", "X is safe."])
    _ledger_json(capsys, ["ledger", str(memory), "decide", "is X safe?"])
    log = memory.with_suffix(".events.jsonl")
    assert log.exists()
    events = [json.loads(line)["event"] for line in log.read_text().splitlines()]
    assert "decide" in events


def test_cli_encode_rejects_an_unknown_model_spec(tmp_path, capsys):
    doc = tmp_path / "notes.txt"
    doc.write_text("The cache may be cleared after a deploy.")
    with pytest.raises(SystemExit) as exit_info:
        cli_main(
            ["encode", str(doc), "-o", str(tmp_path / "m.json"), "--model", "nope:x"]
        )
    assert exit_info.value.code == 1
    assert "unknown model spec" in capsys.readouterr().err


def test_cli_encode_uses_the_reflection_encoder_when_given_a_model(
    tmp_path, monkeypatch
):
    """`encode` was hardcoded to LocalEncoder, so the CLI could not produce a
    reflection-encoded store at all and nothing documented the limit: the only
    route to one was dropping into Python. The client is faked here because
    what is under test is which encoder the flag selects, not the prompting.
    """
    from darwin_memo import MemoryEntry
    from darwin_memo import cli as cli_module

    used: dict[str, object] = {}

    class FakeReflectionEncoder:
        def __init__(self, client: object) -> None:
            used["client"] = client

        def encode(self, documents: list[object]) -> list[MemoryEntry]:
            used["documents"] = len(documents)
            return [MemoryEntry(question="q?", answer="a", sources=["fake"])]

    monkeypatch.setattr(cli_module, "_client_for", lambda spec: f"client:{spec}")
    monkeypatch.setattr(cli_module, "ReflectionEncoder", FakeReflectionEncoder)

    doc = tmp_path / "notes.txt"
    doc.write_text("The cache may be cleared after a deploy.")
    memory = tmp_path / "m.json"
    assert cli_main(["encode", str(doc), "-o", str(memory), "--model", "ollama:x"]) == 0
    assert used == {"client": "client:ollama:x", "documents": 1}
    assert json.loads(memory.read_text())["entries"]


def test_encode_names_a_non_text_file_instead_of_a_traceback(tmp_path, capsys):
    binary = tmp_path / "image.bin"
    binary.write_bytes(b"\xff\xfe\x00\x01not utf-8\xff")
    code = cli_main(["encode", str(binary), "-o", str(tmp_path / "m.json")])
    assert code == 1
    assert "cannot read" in capsys.readouterr().err
