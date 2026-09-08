import { useEffect, useState } from "react";
import { fetchEvents, type LogEvent } from "../api";
import type { Nav } from "../nav";

/**
 * The event log, rendered as events rather than as the word "settle".
 *
 * The old panel printed tick, event name and timestamp only, so a
 * settlement showed as "settle" with no delta, no entry and no outcome --
 * and you could filter on ids the list never displayed. It also polled on
 * its own timer with its own duplicated fetch logic.
 */
const POLL_MS = 2000;

function ids(event: LogEvent): string[] {
  const found = new Set<string>();
  const applied = event.applied;
  if (Array.isArray(applied)) {
    for (const row of applied) {
      const id = (row as { entry?: unknown })?.entry;
      if (typeof id === "string") found.add(id);
    }
  }
  for (const key of ["entry", "id"]) {
    const value = event[key];
    if (typeof value === "string") found.add(value);
  }
  const buried = event.buried;
  if (Array.isArray(buried)) {
    for (const id of buried) if (typeof id === "string") found.add(id);
  }
  return [...found];
}

function summarize(event: LogEvent): string {
  const delta = typeof event.delta === "number" ? event.delta : null;
  switch (event.event) {
    case "settle": {
      const sign = delta !== null && delta >= 0 ? "+" : "";
      const who = event.source === "operator" ? " (operator-entered)" : "";
      const detail = typeof event.detail === "string" && event.detail
        ? ` — ${event.detail}`
        : "";
      return `settled ${sign}${delta ?? "?"}${who}${detail}`;
    }
    case "decide":
      return typeof event.query === "string" ? `asked: ${event.query}` : "decided";
    case "tick": {
      const charged = event.upkeep_charged;
      return typeof charged === "number"
        ? `tick — charged ${charged.toFixed(3)} upkeep`
        : "tick";
    }
    case "add":
      return typeof event.question === "string"
        ? `added: ${event.question}`
        : "added an entry";
    case "settle_dropped":
      return "settlement DROPPED — unknown, already settled, or expired ticket";
    case "settle_rejected":
      return "settlement REFUSED — not a finite measurement";
    case "admission_denied":
      return "admission denied — a juvenile entry decided badly on its first outcome";
    default:
      return event.event.replace(/_/g, " ");
  }
}

export function Events({
  nav,
  go,
  select,
}: {
  nav: Nav;
  go: (patch: Partial<Nav>) => void;
  select: (id: string | null) => void;
}) {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const body = await fetchEvents(300);
        if (live) {
          setEvents(body.events);
          setError(null);
        }
      } catch (caught) {
        if (live) setError(caught instanceof Error ? caught.message : String(caught));
      }
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  // The shared filter doubles as "show me this entry's events", which is
  // what makes the selection in every other panel mean something here.
  const needle = nav.query.trim().toLowerCase();
  const shown = needle
    ? events.filter((event) =>
        JSON.stringify(event).toLowerCase().includes(needle),
      )
    : events;

  return (
    <>
      <div className="listhead">
        <h2>
          Events
          {nav.query && (
            <span className="filtered">
              {shown.length} of {events.length} match “{nav.query}”
            </span>
          )}
        </h2>
        <input
          type="search"
          value={nav.query}
          placeholder="filter by entry id, ticket, or text"
          aria-label="Filter events"
          onChange={(event) => go({ query: event.target.value })}
        />
      </div>

      {error && <p className="empty">Cannot read the event log: {error}</p>}
      {!error && events.length === 0 && (
        <div className="empty">
          <h2>No events recorded</h2>
          <p>
            The event log is a sidecar file next to the store. It fills up as
            decisions are made, settled and ticked.
          </p>
        </div>
      )}

      <ol className="events">
        {shown.map((event, index) => (
          <li key={`${event.ts}-${index}`} className={`ev ev-${event.event}`}>
            <span className="t">t{event.tick}</span>
            <span className="body">
              <span className="what">{summarize(event)}</span>
              <span className="meta">
                <span className="name">{event.event}</span>
                {ids(event).map((id) => (
                  <button
                    key={id}
                    type="button"
                    className="idlink"
                    onClick={() => select(id)}
                    title="Open this entry"
                  >
                    {id}
                  </button>
                ))}
                <time dateTime={event.ts}>{event.ts?.replace("T", " ")}</time>
              </span>
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}
