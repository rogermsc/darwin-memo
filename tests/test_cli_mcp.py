"""CLI commands and the MCP server (the latter skipped without the extra)."""

import json

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
    pytest.importorskip("mcp")
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
