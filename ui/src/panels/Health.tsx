import type { State } from "../api";
import type { Nav } from "../nav";

// A finding's evidence names the entries it is about. Ids are 12 hex
// characters, so they can be pulled out and made clickable -- the fix text
// used to name a problem and leave you to find it by hand.
const ID = /\b[0-9a-f]{12}\b/g;

function Evidence({
  text,
  select,
}: {
  text: string;
  select: (id: string | null) => void;
}) {
  const parts = text.split(ID);
  const ids = text.match(ID) ?? [];
  return (
    <p className="evidence">
      {parts.map((part, i) => (
        <span key={i}>
          {part}
          {ids[i] && (
            <button
              type="button"
              className="idlink"
              onClick={() => select(ids[i])}
            >
              {ids[i]}
            </button>
          )}
        </span>
      ))}
    </p>
  );
}

/**
 * The diagnosis, and -- new -- whether there was anything to diagnose.
 *
 * An empty finding list rendered a teal all-clear reading "No degeneracy
 * detected", which is exactly what a brand-new store produces. The most
 * prominent thing on an empty page was a green light on an empty room.
 */
export function Health({
  state,
  go,
  select,
}: {
  state: State;
  go: (patch: Partial<Nav>) => void;
  select: (id: string | null) => void;
}) {
  const { doctor, evidence } = state;

  if (doctor.length === 0 && !evidence.diagnosed) {
    return (
      <section className="health quiet">
        <h2>Nothing measured yet</h2>
        <p>
          {evidence.alive} {evidence.alive === 1 ? "entry" : "entries"}, {state.tick}{" "}
          {state.tick === 1 ? "tick" : "ticks"}, {evidence.settles} settled{" "}
          {evidence.settles === 1 ? "outcome" : "outcomes"}. Selection has not run,
          so there is nothing to diagnose &mdash; this is not a clean bill of
          health.
        </p>
        <p className="how">
          Memory earns only from measured outcomes. Answer a question, act on
          it, then settle the ticket with what actually changed:
          <code>darwin-memo ledger {state.store.name} decide "your question"</code>
          {state.counts.pending > 0 && (
            <button
              type="button"
              className="inline"
              onClick={() => go({ view: "pending" })}
            >
              or settle one of the {state.counts.pending} open tickets here
            </button>
          )}
        </p>
      </section>
    );
  }

  if (doctor.length === 0) {
    return (
      <section className="health ok">
        <h2>No degeneracy detected</h2>
        <p>
          Checked against {evidence.settles} settled{" "}
          {evidence.settles === 1 ? "outcome" : "outcomes"} over {state.tick}{" "}
          {state.tick === 1 ? "tick" : "ticks"}.
        </p>
      </section>
    );
  }

  return (
    <section className="health bad">
      <h2>
        {doctor.length} {doctor.length === 1 ? "finding" : "findings"}
      </h2>
      {doctor.map((finding) => (
        <article key={finding.code} className={`finding ${finding.severity}`}>
          <h3>
            <span className={`sev ${finding.severity}`}>{finding.severity}</span>
            {finding.summary}
          </h3>
          <Evidence text={finding.evidence} select={select} />
          <p className="fix">{finding.fix}</p>
          <code className="code">{finding.code}</code>
        </article>
      ))}
    </section>
  );
}
