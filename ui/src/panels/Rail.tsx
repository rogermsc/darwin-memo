import type { State, WriteAction } from "../api";
import type { Nav, View } from "../nav";

/** A magnitude with its sign, but never a signed zero: "-0.00" reads wrong. */
function signed(magnitude: number, sign: "+" | "-"): string {
  const shown = magnitude.toFixed(2);
  return Number(shown) === 0 ? shown : `${sign}${shown}`;
}

/**
 * Store identity, the vitals, and the clock.
 *
 * Every count here is a button into the view that lists what it counts.
 * They used to be six bare numbers with nowhere to go -- `pending: 4`
 * most of all, since there was no pending view at all.
 */
export function Rail({
  state,
  nav,
  go,
  busy,
  act,
}: {
  state: State;
  nav: Nav;
  go: (patch: Partial<Nav>) => void;
  busy: boolean;
  act: (a: WriteAction, body: Record<string, unknown>, said: string) => void;
}) {
  const { counts, store, economics } = state;
  // Each tile navigates to what it counts. "pinned" is not a view of its
  // own -- it filters the roster, which is why it carries a query.
  const cells: {
    label: string;
    value: number;
    view: View;
    query?: string;
    hint: string;
  }[] = [
    {
      label: "living",
      value: counts.alive,
      view: "living",
      hint: "entries paying upkeep right now",
    },
    {
      label: "pending",
      value: counts.pending,
      view: "pending",
      hint: "decisions still waiting on an outcome",
    },
    {
      label: "buried",
      value: counts.dead,
      view: "graveyard",
      hint: "entries selection has removed",
    },
    {
      label: "pinned",
      value: counts.pinned,
      view: "living",
      query: "pinned",
      hint: "entries exempt from starvation and merges",
    },
  ];

  return (
    <aside className="rail">
      <header className="brand">
        <h1>darwin-memo</h1>
        <p className="store" title={store.path}>
          {store.name}
        </p>
      </header>

      <dl className="clock">
        <div>
          <dt>tick</dt>
          <dd>{state.tick}</dd>
        </div>
        <div>
          <dt>upkeep / tick</dt>
          <dd>{state.upkeep.toFixed(3)}</dd>
        </div>
      </dl>
      <p className="note">
        A tick is one round of upkeep, charged when you or a script advance
        it &mdash; not a wall clock. Every living entry pays{" "}
        <strong>{state.upkeep.toFixed(3)}</strong> energy per tick and can hold
        at most <strong>{store.max_energy}</strong>.
      </p>

      <ul className="vitals">
        {cells.map((cell) => {
          const active =
            cell.view === nav.view && (cell.query ?? "") === nav.query;
          return (
            <li key={cell.label}>
              <button
                type="button"
                className={active ? "vital on" : "vital"}
                aria-pressed={active}
                onClick={() => go({ view: cell.view, query: cell.query ?? "" })}
                title={cell.hint}
              >
                <span className="n">{cell.value}</span>
                <span className="k">{cell.label}</span>
              </button>
            </li>
          );
        })}
      </ul>

      <section className="ledgerette">
        <h2>Energy</h2>
        <dl>
          <div>
            <dt>held</dt>
            <dd>
              {state.total_energy.toFixed(2)}
              {counts.alive > 0 && (
                <span className="of">
                  {" "}
                  / {(counts.alive * store.max_energy).toFixed(0)} max
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt>earned</dt>
            <dd className={economics.energy.credited ? "pos" : undefined}>
              {signed(economics.energy.credited, "+")}
            </dd>
          </div>
          <div>
            {/* `debited` and `upkeep_paid` are magnitudes, not signed
                amounts, so the sign belongs here. Without it the panel
                read "lost 6.00" as though it were a gain. */}
            <dt>lost to bad outcomes</dt>
            <dd className={economics.energy.debited ? "neg" : undefined}>
              {signed(economics.energy.debited, "-")}
            </dd>
          </div>
          <div>
            <dt>paid as upkeep</dt>
            <dd className={economics.energy.upkeep_paid ? "neg" : undefined}>
              {signed(economics.energy.upkeep_paid, "-")}
            </dd>
          </div>
          <div className="net">
            <dt>net</dt>
            <dd
              className={
                economics.energy.net === 0
                  ? undefined
                  : economics.energy.net > 0
                    ? "pos"
                    : "neg"
              }
            >
              {signed(Math.abs(economics.energy.net), economics.energy.net < 0 ? "-" : "+")}
            </dd>
          </div>
        </dl>
        {!economics.energy.upkeep_exact && (
          <p className="caveat">{economics.energy.upkeep_caveat}</p>
        )}
      </section>

      <section className="ledgerette">
        <h2>Resource measured</h2>
        <p className="big">
          {economics.resource.delta_total >= 0 ? "+" : ""}
          {economics.resource.delta_total.toLocaleString()}
        </p>
        <p className="caveat">
          over {economics.resource.decides} decisions,{" "}
          {economics.resource.silent} of them silent. This is your unit
          &mdash; bytes, passing tests, dollars &mdash; and it is <em>not</em>{" "}
          comparable with the energy figures above.
        </p>
      </section>

      <button
        type="button"
        className="tick"
        disabled={busy}
        onClick={() => act("tick", {}, "ticked: upkeep charged")}
        title="Charge one round of upkeep, bury what starved, consolidate"
      >
        Advance one tick
      </button>
    </aside>
  );
}
