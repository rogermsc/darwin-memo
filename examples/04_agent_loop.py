"""Bolting the store onto an agent loop: memory as a tool, outcomes as credit.

With ANTHROPIC_API_KEY set (and `pip install "darwin-memo[anthropic]"`),
Claude runs a real tool-use loop where consult_memory is a tool. Without
a key, the protocol answers directly so the file always runs offline.
Either way, the environment measures the outcome and credit flows back
along whatever was consulted. Watch the ledger move.

    python examples/04_agent_loop.py
"""

import os

from common import build_store

from darwin_memo import (
    QueryProtocol,
    SurvivalConfig,
    Task,
    VerifiableQAEnv,
    assign_credit,
)

store = build_store()
protocol = QueryProtocol(store)

QA = [
    ("How long are old log files under logs/ kept?", "seven days"),
    ("Who backs up the database store files?", "Platform Team"),
    ("Where does the Platform Team send nightly backups?", "cold storage"),
]
env = VerifiableQAEnv(QA, per_cycle=3)


def consult_memory(query: str, consulted: list[str]) -> str:
    answer = protocol.answer(query)
    if answer.deciding_entry:
        consulted.append(answer.deciding_entry)
    consulted.extend(answer.supporting_entries)
    return answer.text or "(memory is silent)"


def agent_answer(task: Task, consulted: list[str]) -> str:
    """A real Claude tool-use loop when a key is present, memory-direct otherwise."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return consult_memory(task.prompt, consulted)

    import anthropic

    client = anthropic.Anthropic()
    tools = [
        {
            "name": "consult_memory",
            "description": "Look up facts in the agent's curated memory.",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]
    messages = [{"role": "user", "content": task.prompt}]
    while True:
        response = client.messages.create(
            model=os.environ.get("DARWIN_MEMO_MODEL", "claude-sonnet-4-6"),
            max_tokens=512,
            tools=tools,
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                text = consult_memory(block.input["query"], consulted)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": text,
                    }
                )
        messages.append({"role": "user", "content": results})


mode = "Claude tool-use loop" if os.environ.get("ANTHROPIC_API_KEY") else "offline"
print(f"Agent mode: {mode}\n")

for task in env.tasks(cycle=0):
    consulted: list[str] = []
    before = {e.id: e.energy for e in store.alive()}

    answer_text = agent_answer(task, consulted)
    outcome = env.verify(task, answer_text)

    # Credit flows back along provenance via the shared credit rule.
    deduped = list(dict.fromkeys(consulted))
    assign_credit(
        store,
        None,
        deduped,
        outcome.delta,
        env.resource_scale,
        SurvivalConfig(),
        cycle=0,
    )
    store.charge_upkeep()

    print(f"Q: {task.prompt}")
    print(f"A: {answer_text}")
    print(f"   outcome: {outcome.detail} (delta {outcome.delta:+.1f})")
    for entry_id in dict.fromkeys(consulted):
        entry = store.get(entry_id)
        if entry:
            moved = entry.energy - before.get(entry_id, 0.0)
            print(f"   ledger: {moved:+.3f} -> {entry.question[:60]}")
    print()
