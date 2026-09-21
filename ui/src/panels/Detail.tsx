import { useEffect, useState } from "react";
import { fetchEntry, type Life, type State, type WriteAction } from "../api";
import type { Nav } from "../nav";

/**
 * One entry's whole life, and what you can do about it.
 *
 * The old drawer declared `birth` and `settlements` in its type and
 * rendered neither, showed no entry id, had no keyboard path in or out,
 * and covered the row you clicked. This is a pane, not an overlay: it
 * sits beside the listing so the two stay legible together.
 *
 * Target: never poorer than `darwin-memo why <id>`.
 */
export function Detail({
  id,
  state,
  go,
  select,
  busy,
  act,
}: {
  id: string | null;
  state: State;
  go: (patch: Partial<Nav>) => void;
  select: (id: string | null) => void;
  busy: boolean;
  act: (a: WriteAction, body: Record<string, unknown>, said: string) => void;
}) {
  const [life, setLife] = useState<Life | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) {
      setLife(null);
      return;
    }
    let live = true;
    fetchEntry(id)
      .then((next) => live && (setLife(next), setError(null)))
      .catch((caught) => live && setError(String(caught)));
    return () => {
      live = false;
    };
  }, [id, state]);

  useEffect(() => {
    if (!id) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") select(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [id, select]);

  if (!id) return <NewEntry busy={busy} act={act} />;
  if (error) return <aside className="detail"><p className="empty">{error}</p></aside>;
  if (!life) return <aside className="detail"><p className="empty">Loading…</p></aside>;

  const runway = life.ticks_to_starvation;
  return (
    <aside className="detail" aria-label="Entry detail">
      <header>
        <span className={`status ${life.status}`}>{life.status}</span>
        <button type="button" className="close" onClick={() => select(null)}>
          Close
        </button>
      </header>

      <h2>{life.question ?? life.id}</h2>
      {life.answer && <p className="answer">{life.answer}</p>}

      <div className="actions">
        {life.status === "living" && (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                act(
                  life.pinned ? "unpin" : "pin",
                  { id: life.id },
                  life.pinned
                    ? `unpinned ${life.id}; selection resumes`
                    : `pinned ${life.id}; starvation and merges cannot remove it`,
                )
              }
              title={
                life.pinned
                  ? "Return this entry to normal selection pressure"
                  : "Exempt from starvation and merges. A pin suspends the only mechanism that removes bad memory."
              }
            >
              {life.pinned ? "Unpin" : "Pin"}
            </button>
            <button
              type="button"
              className="danger"
              disabled={busy}
              onClick={() =>
                act("forget", { id: life.id }, `forget ${life.id}: requested`)
              }
              title="Bury it now, without waiting for selection. For advice that is wrong but inert."
            >
              Forget
            </button>
          </>
        )}
        {/* Available for the dead too: an entry's log is most worth reading
            once it is gone and you want to know what killed it. */}
        <button
          type="button"
          className="ghost"
          onClick={() => go({ view: "events", query: life.id })}
        >
          Its events
        </button>
      </div>

      <h3>
        Settlements
        <span className="count">{life.settlements.length}</span>
      </h3>
      {life.settlements.length === 0 ? (
        <p className="none">
          No settlement evidence is retained for this lesson. Missing historical
          outcomes remain unknown.
        </p>
      ) : (
        <ol className="settlements">
          {life.settlements.map((note, index) => (
            <li
              key={index}
              className={note.credit == null ? "" : note.credit < 0 ? "neg" : "pos"}
            >
              <span className="credit">
                {note.credit == null ? "unknown" : `${note.credit >= 0 ? "+" : ""}${note.credit.toFixed(3)}`}
              </span>
              <span className="body">
                <span>
                  reported outcome{" "}
                  <strong>
                    {note.delta == null ? "unknown" : `${note.delta >= 0 ? "+" : ""}${note.delta}`}
                  </strong>
                  <span className="flag">{note.source ?? "unknown source"}</span>
                  {note.source === "measured" && <span className="flag">legacy caller claim</span>}
                  {note.deciding && <span className="flag">decided</span>}
                </span>
                {note.detail && <span className="detailtext">{note.detail}</span>}
                {note.evidence ? <span className="detailtext">
                  {note.evidence.repository ?? "Unknown repository"} · task {note.evidence.task ?? "unknown"} · run {note.evidence.run ?? "unknown"}<br />
                  Comparison: {note.evidence.base?.slice(0, 12) ?? "unknown base"} → {note.evidence.commit?.slice(0, 12) ?? "unknown commit"}
                </span> : <span className="detailtext">Comparison and provenance unknown.</span>}
                <span className="meta">t{note.tick ?? "?"}</span>
              </span>
            </li>
          ))}
        </ol>
      )}

      <details><summary>Advanced lesson details</summary>
      <dl className="facts">
        <div>
          <dt>id</dt>
          <dd>
            <code>{life.id}</code>
          </dd>
        </div>
        <div>
          <dt>kind</dt>
          <dd>{life.kind ?? "—"}</dd>
        </div>
        <div>
          <dt>balance</dt>
          <dd>
            {life.balance === null
              ? "—"
              : `${life.balance.toFixed(3)} of ${state.store.max_energy}`}
          </dd>
        </div>
        {/* Runway is ticks-until-starvation, which is meaningless once an
            entry is gone: the raw figure went negative and rendered as
            "-6 ticks" on a grave. */}
        {life.status === "living" && (
          <div>
            <dt>runway</dt>
            <dd>
              {life.pinned
                ? "pinned — cannot starve"
                : runway === null
                  ? "—"
                  : `${Math.max(0, Math.floor(runway))} ticks`}
            </dd>
          </div>
        )}
        <div>
          <dt>uses</dt>
          <dd>{life.uses ?? 0}</dd>
        </div>
        <div>
          <dt>born</dt>
          <dd>
            t{life.birth.tick ?? "?"}
            {life.birth.source ? ` from ${life.birth.source}` : ""}
            {life.birth.stake !== null && ` at stake ${life.birth.stake}`}
          </dd>
        </div>
        {life.sources.length > 0 && (
          <div>
            <dt>sources</dt>
            <dd>{life.sources.join(", ")}</dd>
          </div>
        )}
        {life.probation > 0 && (
          <div>
            <dt>probation</dt>
            <dd>
              {life.probation} net-positive settlements before it may decide
            </dd>
          </div>
        )}
        {life.juvenile > 0 && (
          <div>
            <dt>juvenile</dt>
            <dd>{life.juvenile} settlements left in its admission window</dd>
          </div>
        )}
        {life.cause_of_death && (
          <div>
            <dt>cause of death</dt>
            <dd>
              <span className={`flag cause-${life.cause_of_death}`}>
                {life.cause_of_death}
              </span>
            </dd>
          </div>
        )}
        {life.merged_into && (
          <div>
            <dt>merged into</dt>
            <dd>
              <button
                type="button"
                className="idlink"
                onClick={() => select(life.merged_into)}
              >
                {life.merged_into}
              </button>
            </dd>
          </div>
        )}
      </dl>

      </details>

      <h3>History</h3>
      <ol className="history">
        {life.events.map((note, index) => (
          <li key={index}>
            <span className="t">t{note.tick ?? "?"}</span>
            <span>{note.text ?? note.event}</span>
          </li>
        ))}
      </ol>
    </aside>
  );
}

/** With nothing selected the pane is not blank: it is where you write. */
function NewEntry({
  busy,
  act,
}: {
  busy: boolean;
  act: (a: WriteAction, body: Record<string, unknown>, said: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const ready = question.trim() !== "" && answer.trim() !== "";

  return (
    <aside className="detail idle" aria-label="Add an entry">
      <h2>Nothing selected</h2>
      <p className="hint">
        Pick an entry to see every settlement that moved its balance and why
        it is alive or dead. Or write a new lesson &mdash; adding is cheap,
        surviving is not.
      </p>
      <form
        className="newentry"
        onSubmit={(event) => {
          event.preventDefault();
          if (!ready) return;
          act(
            "add",
            { question, answer, source: "operator" },
            "added an entry at spawn energy",
          );
          setQuestion("");
          setAnswer("");
        }}
      >
        <label>
          <span>question</span>
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="When is it safe to delete the cache?"
          />
        </label>
        <label>
          <span>answer</span>
          <textarea
            value={answer}
            rows={4}
            onChange={(event) => setAnswer(event.target.value)}
            placeholder="Cache chunk files under cache/ are disposable."
          />
        </label>
        <button type="submit" disabled={busy || !ready}>
          Add entry
        </button>
        <p className="warn">
          It starts at spawn energy and pays upkeep like everything else. If
          nothing ever measures it, it starves.
        </p>
      </form>
    </aside>
  );
}
