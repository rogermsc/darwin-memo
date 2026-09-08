import { useMemo, useState } from "react";
import type { State } from "../api";
import { entryHref, type Nav } from "../nav";

const CAUSES: Record<string, string> = {
  executed:
    "decided real actions the environment then measured as damage; the negative delta flowed back along provenance until the balance was gone",
  starved:
    "nothing ever punished it, it just never earned back the upkeep it paid",
  merged:
    "absorbed into a consolidated entry; its energy pooled and its lineage is recorded",
  forgotten: "buried on request, without waiting for selection",
  unknown:
    "this store carries no history for the entry, so the cause cannot be read back",
};

/**
 * The dead, by cause.
 *
 * Two fixes over the old panel: the cause tiles now filter the list below
 * them (they used to render the same taxonomy twice, adjacent and
 * unlinked), and each id is a link into the detail pane. `entry_life`
 * has always worked for dead entries and the detail pane has always
 * handled cause_of_death -- nothing ever called it with a grave.
 */
export function Graveyard({
  state,
  nav,
  select,
}: {
  state: State;
  nav: Nav;
  select: (id: string | null) => void;
}) {
  const [cause, setCause] = useState<string | null>(null);

  const counts = useMemo(() => {
    const tally: Record<string, number> = {};
    for (const grave of state.graveyard) {
      tally[grave.cause] = (tally[grave.cause] ?? 0) + 1;
    }
    return tally;
  }, [state.graveyard]);

  const shown = cause
    ? state.graveyard.filter((grave) => grave.cause === cause)
    : state.graveyard;

  if (state.graveyard.length === 0) {
    return (
      <div className="empty">
        <h2>Nothing has died yet</h2>
        <p>
          Entries are buried when their energy runs out, when the environment
          measures damage they caused, or when they are merged into a
          near-duplicate. None of that has happened here.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="listhead">
        <h2>Graveyard</h2>
      </div>
      <ul className="causes">
        {Object.entries(counts)
          .sort((a, b) => b[1] - a[1])
          .map(([name, count]) => (
            <li key={name}>
              <button
                type="button"
                className={cause === name ? "cause on" : "cause"}
                aria-pressed={cause === name}
                title={CAUSES[name] ?? name}
                onClick={() => setCause(cause === name ? null : name)}
              >
                <span className="n">{count}</span>
                <span className="k">{name}</span>
              </button>
            </li>
          ))}
      </ul>
      {cause && <p className="causenote">{CAUSES[cause] ?? cause}</p>}

      <table className="roster">
        <thead>
          <tr>
            <th scope="col">cause</th>
            <th scope="col">uses</th>
            <th scope="col">entry</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((grave) => (
            <tr
              key={grave.id}
              className={grave.id === nav.selected ? "on" : undefined}
            >
              <td>
                <span className={`flag cause-${grave.cause}`}>{grave.cause}</span>
              </td>
              <td className="num">{grave.uses ?? "—"}</td>
              <td>
                <a
                  className="entrylink"
                  href={entryHref(grave.id, "graveyard")}
                  onClick={(event) => {
                    if (event.metaKey || event.ctrlKey || event.shiftKey) return;
                    event.preventDefault();
                    select(grave.id);
                  }}
                >
                  {grave.question ?? grave.id}
                </a>
                <span className="meta">
                  <code>{grave.id}</code>
                  {grave.sources.map((source) => (
                    <span key={source} className="src">
                      {source}
                    </span>
                  ))}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
