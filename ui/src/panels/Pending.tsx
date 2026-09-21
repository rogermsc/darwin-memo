import { useState } from "react";
import type { State, WriteAction } from "../api";

/**
 * Open tickets: decisions waiting on an outcome.
 *
 * The payload has carried this array all along and nothing rendered it --
 * only the integer count reached the header, and `doctor` warned about
 * stale tickets in a dashboard that could not show you a ticket.
 *
 * Settling here takes a number a person types, which is the one place
 * this package admits human judgment. The form says so, and the server
 * stamps every such settlement `source: "operator"` so `why`, `audit`
 * and `doctor` can tell it from a measurement.
 */
export function Pending({
  state,
  select,
  busy,
  act,
}: {
  state: State;
  select: (id: string | null) => void;
  busy: boolean;
  act: (a: WriteAction, body: Record<string, unknown>, said: string) => void;
}) {
  if (state.pending.length === 0) {
    return (
      <div className="empty">
        <h2>No open tickets</h2>
        <p>
          Every decision this store has made has been settled or abandoned.
          A ticket opens when memory answers a question, and closes when you
          report what actually happened.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="listhead">
        <h2>Open tickets</h2>
        <p className="sub">
          An unsettled ticket escrows the entries that answered it: they keep
          paying upkeep but cannot be buried or merged until the verdict lands.
        </p>
      </div>
      <ul className="tickets">
        {state.pending.map((ticket) => (
          <Ticket
            key={ticket.id}
            id={ticket.id}
            query={ticket.query}
            age={ticket.age_ticks}
            born={ticket.born_tick}
            binding={ticket.binding}
            busy={busy}
            act={act}
            select={select}
          />
        ))}
      </ul>
    </>
  );
}

function Ticket({
  id,
  query,
  age,
  born,
  binding,
  busy,
  act,
  select,
}: {
  id: string;
  query: string;
  age: number;
  born: number;
  binding?: Record<string, string> | null;
  busy: boolean;
  act: (a: WriteAction, body: Record<string, unknown>, said: string) => void;
  select: (id: string | null) => void;
}) {
  const [delta, setDelta] = useState("");
  const [detail, setDetail] = useState("");
  const parsed = Number(delta);
  const valid = delta.trim() !== "" && Number.isFinite(parsed);

  return (
    <li className={age >= 50 ? "ticket stale" : "ticket"}>
      <div className="q">
        <strong>{query}</strong>
        <span className="meta">
          <code>{id}</code>
          <span>opened t{born}</span>
          <span>{age} ticks old</span>
          {age >= 50 && <span className="flag prob">stale</span>}
        </span>
      </div>

      {binding && <p>Bound to {binding.repository} · task {binding.task} · base {binding.base?.slice(0, 12)}. Use the CI workflow to record the outcome.</p>}
      <details><summary>Operator outcome controls</summary>
      <form
        className="settle"
        onSubmit={(event) => {
          event.preventDefault();
          if (!valid) return;
          act(
            "settle",
            { ticket_id: id, delta: parsed, detail },
            `settled ${id} at ${parsed >= 0 ? "+" : ""}${parsed} (operator-entered)`,
          );
          setDelta("");
          setDetail("");
        }}
      >
        <label>
          <span>reported delta</span>
          <input
            value={delta}
            onChange={(event) => setDelta(event.target.value)}
            inputMode="decimal"
            placeholder="e.g. 1200"
            aria-label={`Reported delta for ticket ${id}`}
          />
        </label>
        <label className="wide">
          <span>outcome source and comparison</span>
          <input
            value={detail}
            onChange={(event) => setDetail(event.target.value)}
            placeholder="bytes freed, tests passing, run URL"
            aria-label={`Detail for ticket ${id}`}
          />
        </label>
        <div className="row">
          <button type="submit" disabled={busy || !valid}>
            Settle
          </button>
          <button
            type="button"
            className="ghost"
            disabled={busy}
            onClick={() =>
              act("abandon", { ticket_id: id }, `abandoned ${id}; escrow released`)
            }
            title="You did not act on this answer, so there is no outcome to measure"
          >
            Abandon
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => select(null)}
            hidden
          />
        </div>
        <p className="warn">
          A number you type is not a measurement. It is recorded as
          operator-entered and shows up in <code>audit</code> and{" "}
          <code>doctor</code> as such.
        </p>
      </form>
      </details>
    </li>
  );
}
