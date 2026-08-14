import { useEffect, useState } from "react";

type Event = { event: string; tick?: number; ts?: string } & Record<string, unknown>;

export function EventStream() {
  const [events, setEvents] = useState<Event[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const response = await fetch("api/events?last=200");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (!Array.isArray(payload.events)) {
          throw new Error("unexpected response shape");
        }
        if (!live) return;
        setEvents(payload.events);
        setError(null);
      } catch (caught) {
        // A break here used to be invisible: a permanently empty panel
        // with no error anywhere, on the one endpoint this branch had
        // zero test coverage for. Surface it instead.
        if (live) setError(String(caught));
      }
    };
    load();
    const timer = setInterval(load, 2000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  const shown = filter
    ? events.filter((e) => JSON.stringify(e).includes(filter))
    : events;
  return (
    <section className="panel">
      <h2>Events</h2>
      <input
        value={filter}
        placeholder="filter"
        onChange={(change) => setFilter(change.target.value)}
      />
      {error && (
        <article className="finding error">
          <h3>events unavailable</h3>
          <p>{error}</p>
        </article>
      )}
      <ol className="stream">
        {[...shown].reverse().map((event, index) => (
          <li key={index}>
            <code>t{event.tick ?? "?"}</code> <strong>{event.event}</strong>{" "}
            <span className="label">{event.ts ?? ""}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
