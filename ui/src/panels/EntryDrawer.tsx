import { useEffect, useState } from "react";
import { fetchEntry } from "../api";

type Life = {
  id: string;
  status: string;
  question: string | null;
  answer: string | null;
  balance: number | null;
  uses: number | null;
  cause_of_death: string | null;
  birth: { tick: number | null; ts: string | null; source: string | null };
  settlements: Record<string, unknown>[];
  events: { text?: string }[];
};

// A pinned or long-lived entry racks up dozens of settle events (70+ is
// routine in a 30-cycle run); dumping all of them into a fixed-width side
// panel is a real usability defect, not a cosmetic one. Show the most
// recent EVENTS_SHOWN and say how many are hidden — the panel also caps
// its own height (see .drawer .stream in theme.css) so a shorter list
// still can't push the close button off-screen.
const EVENTS_SHOWN = 50;

export function EntryDrawer({
  id,
  onClose,
}: {
  id: string;
  onClose: () => void;
}) {
  const [life, setLife] = useState<Life | null>(null);
  useEffect(() => {
    setLife(null); // clear stale entry immediately when selection changes
    let live = true;
    fetchEntry(id).then((loaded) => live && setLife(loaded));
    return () => {
      live = false;
    };
  }, [id]);
  const recent = life ? [...life.events].reverse().slice(0, EVENTS_SHOWN) : [];
  return (
    <aside className="drawer">
      <button type="button" onClick={onClose}>
        close
      </button>
      {!life ? (
        <p>Loading…</p>
      ) : (
        <>
          <h2>{life.question}</h2>
          <p>{life.answer}</p>
          <p className="label">
            {life.status} · balance {life.balance ?? "—"} · uses {life.uses ?? 0}
            {life.cause_of_death && ` · died: ${life.cause_of_death}`}
          </p>
          <h3>
            Events
            {life.events.length > EVENTS_SHOWN &&
              ` (latest ${EVENTS_SHOWN} of ${life.events.length})`}
          </h3>
          <ol className="stream">
            {recent.map((event, index) => (
              <li key={index}>{event.text ?? JSON.stringify(event)}</li>
            ))}
          </ol>
        </>
      )}
    </aside>
  );
}
