import { useMemo, useState } from "react";
import type { Entry, State } from "../api";
import { entryHref, type Nav } from "../nav";

type Column = "balance" | "ticks_to_starvation" | "uses" | "age_ticks";

const COLUMNS: { id: Column; label: string; hint: string }[] = [
  { id: "balance", label: "balance", hint: "energy held; upkeep drains it every tick" },
  {
    id: "ticks_to_starvation",
    label: "runway",
    hint: "ticks until this entry starves if it never earns again",
  },
  { id: "uses", label: "uses", hint: "decisions this entry has answered" },
  { id: "age_ticks", label: "age", hint: "ticks since it was written" },
];

/**
 * The living population, with the columns `darwin-memo top` prints.
 *
 * kind, sources, last-settled and the pinned/probation flags were all in
 * the payload and rendered nowhere, which left the terminal strictly more
 * informative than the GUI. Rows are links now, not a bare onClick with a
 * hover cursor as its only affordance.
 */
export function Roster({
  state,
  nav,
  go,
  select,
}: {
  state: State;
  nav: Nav;
  go: (patch: Partial<Nav>) => void;
  select: (id: string | null) => void;
}) {
  const [sort, setSort] = useState<Column>("uses");
  const [asc, setAsc] = useState(false);
  const [advanced, setAdvanced] = useState(false);

  const rows = useMemo(() => {
    const needle = nav.query.trim().toLowerCase();
    const matched = needle
      ? state.entries.filter((entry) =>
          [
            entry.question,
            entry.id,
            entry.kind,
            ...entry.sources,
            // Searchable so the rail's flag tiles can filter to them, and
            // so typing "pinned" does what a reader expects.
            entry.pinned ? "pinned" : "",
            entry.probation > 0 ? "probation" : "",
          ]
            .join(" ")
            .toLowerCase()
            .includes(needle),
        )
      : state.entries;
    // Copy before sorting: the poll replaces `entries` every two seconds
    // and sorting in place would reorder rows under the cursor.
    return [...matched].sort((a, b) => {
      const left = Number(a[sort] ?? 0);
      const right = Number(b[sort] ?? 0);
      return asc ? left - right : right - left;
    });
  }, [state.entries, nav.query, sort, asc]);

  if (state.entries.length === 0) {
    return (
      <div className="empty">
        <h2>No living entries</h2>
        <p>
          Nothing is in this store yet. Build one from your own text with{" "}
          <code>darwin-memo encode notes/*.txt -o {state.store.name}</code>, or
          write a single lesson from the panel on the right.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="listhead">
        <h2>
          Lessons
          {nav.query && (
            <span className="filtered">
              {rows.length} of {state.entries.length} match “{nav.query}”
            </span>
          )}
        </h2>
        <input
          type="search"
          value={nav.query}
          placeholder="filter by text, id, kind or source"
          aria-label="Filter living entries"
          onChange={(event) => go({ query: event.target.value })}
        />
      </div>

      <label><input type="checkbox" checked={advanced} onChange={(event) => setAdvanced(event.target.checked)} /> Show advanced energy columns</label>
      <table className="roster">
        <thead>
          <tr>
            <th scope="col">lesson</th>
            {COLUMNS.filter((column) => advanced || (column.id !== "balance" && column.id !== "ticks_to_starvation")).map((column) => (
              <th key={column.id} scope="col">
                <button
                  type="button"
                  title={column.hint}
                  aria-sort={
                    sort === column.id
                      ? asc
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                  onClick={() => {
                    if (sort === column.id) setAsc(!asc);
                    else {
                      setSort(column.id);
                      setAsc(false);
                    }
                  }}
                >
                  {column.label}
                  {sort === column.id && <span aria-hidden>{asc ? " ▲" : " ▼"}</span>}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((entry) => (
            <Row
              key={entry.id}
              entry={entry}
              selected={entry.id === nav.selected}
              maxEnergy={state.store.max_energy}
              advanced={advanced}
              onSelect={select}
            />
          ))}
        </tbody>
      </table>
    </>
  );
}

function Row({
  entry,
  selected,
  maxEnergy,
  advanced,
  onSelect,
}: {
  entry: Entry;
  selected: boolean;
  maxEnergy: number;
  advanced: boolean;
  onSelect: (id: string) => void;
}) {
  const runway = entry.ticks_to_starvation;
  return (
    <tr className={selected ? "on" : undefined} aria-selected={selected}>
      <td>
        <a
          className="entrylink"
          href={entryHref(entry.id)}
          onClick={(event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey) return;
            event.preventDefault();
            onSelect(entry.id);
          }}
        >
          {entry.question}
        </a>
        <span className="meta">
          <code>{entry.id}</code>
          <span className="kind">{entry.kind}</span>
          {entry.sources.map((source) => (
            <span key={source} className="src">
              {source}
            </span>
          ))}
          {entry.pinned && <span className="flag pin">pinned</span>}
          {entry.probation > 0 && (
            <span className="flag prob">probation {entry.probation}</span>
          )}
          <span className="settled">
            {entry.last_settled_tick === null
              ? "never settled"
              : `settled t${entry.last_settled_tick}`}
          </span>
        </span>
      </td>
      {/* data-label carries the column name into the narrow layout, where
          the header row is hidden and bare numbers would be unreadable. */}
      {advanced && <>
      <td className="num" data-label="balance">
        {/* A bar, because 0.85 means nothing without the ceiling. */}
        <span className="bar" aria-hidden>
          <i style={{ width: `${Math.max(2, (entry.balance / maxEnergy) * 100)}%` }} />
        </span>
        {entry.balance.toFixed(2)}
      </td>
      <td
        className={runway !== null && runway <= 5 ? "num soon" : "num"}
        data-label="runway"
      >
        {entry.pinned ? "—" : runway === null ? "?" : Math.floor(runway)}
      </td>
      </>}
      <td className="num" data-label="uses">
        {entry.uses}
      </td>
      <td className="num" data-label="age">
        {entry.age_ticks}
      </td>

    </tr>
  );
}
