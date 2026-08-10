import { useEffect, useState } from "react";

type Event = { event: string; tick?: number; ts?: string } & Record<string, unknown>;

export function EventStream() {
  const [events, setEvents] = useState<Event[]>([]);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    let live = true;
    const load = async () => {
      const response = await fetch("api/events?last=200");
      if (response.ok && live) setEvents((await response.json()).events);
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
