# OpenAI Agents SDK

The Agents SDK ships Sessions (`SQLiteSession`, `OpenAIConversationsSession`)
that store and replay the conversation transcript: the runner calls
`get_items` before a turn and `add_items` after it. That is short-term
context. The long-term slot, lessons that persist across sessions and
earn or lose their place by measured outcomes, is vacant.
`DarwinMemoSession` fills it while remaining a faithful Session for the
transcript part.

The adapter lives at `darwin_memo.integrations.openai_agents` and adds
zero dependencies: it implements the SDK's `Session` protocol
(`agents.memory.session.Session`, a runtime-checkable Protocol with
`session_id` plus async `get_items` / `add_items` / `pop_item` /
`clear_session`) by duck typing, so darwin-memo never imports the SDK
and the SDK never imports darwin-memo.

## Wiring

```python
from agents import Agent, Runner
from darwin_memo.integrations.openai_agents import DarwinMemoSession

session = DarwinMemoSession(
    "support-thread-42",
    transcript_dir=".darwin-memo/sessions",
    lesson_path=".darwin-memo/lessons.json",
)

# Opt in to lessons BEFORE the turn. Silence means memory has
# nothing relevant; prefer that over guessing.
consultation = session.consult("How should refunds over $500 be routed?")
prompt = user_input
if consultation.lessons:
    prompt = f"Lessons from memory:\n{consultation.lessons}\n\n{user_input}"

agent = Agent(name="Support", instructions="You handle refunds.")
result = await Runner.run(agent, prompt, session=session)

# LATER, once you have measured the outcome of acting on the lessons
# (tickets resolved, dollars saved, tests passing), settle:
if consultation.ticket_id:
    session.settle(consultation.ticket_id, delta=measured_delta)
    # or session.abandon(consultation.ticket_id) if you never acted.
```

Hosts that run many sessions against one lesson store (the point of
long-term memory) can construct a single `Ledger` and pass it as
`ledger=` to every session; `lesson_path=` alone also works and the
adapter loads or creates the store there. When `lesson_path` is set,
every consult, settle, and abandon persists, so open tickets survive
the process that minted them.

## Transcript versus lessons

The two layers never mix, on purpose:

- **Transcript** (the Session protocol): what was said in THIS
  conversation, replayed verbatim into the next turn. The adapter
  stores it as one JSONL file per session id under `transcript_dir`,
  honest and greppable, with the protocol's documented semantics:
  `get_items(limit=N)` returns the latest N items in chronological
  order, `pop_item` removes and returns the most recent item,
  `clear_session` deletes everything for the id.
- **Lessons** (the darwin-memo layer): what this agent has learned
  across ALL conversations, curated by survival. `consult` runs
  `Ledger.decide` and opens a ticket; `settle` reports the measured
  outcome and credit flows along the provenance; entries that keep
  producing bad outcomes die on their own.

The runner only ever touches the transcript layer. Lessons enter a
turn only when the host injects `consultation.lessons` itself, so what
the model sees stays under the host's control.

## Honest scope

- The adapter never invents deltas. `settle` carries a measurement the
  host made of a conserved resource; passing a quality score, a vibe,
  or an LLM's opinion destroys the no-judge property and everything
  downstream of it.
- Settlement is host-discretionary in this shape: the app must
  remember to settle or abandon. Tickets left unsettled expire at
  delta zero when the ledger ticks (see `Ledger.tick`); run a tick at
  natural boundaries, like the end of a work session.
- The transcript store is plain JSONL with no locking, sized for the
  SDK's sequential turn loop, one writer per session id. It is not a
  multi-process queue.
- Sessions cannot be combined with the SDK's `conversation_id` or
  `previous_response_id` server-side state in the same run; that is an
  SDK rule and it applies here unchanged.
