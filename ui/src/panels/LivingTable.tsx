import { useState } from "react";
import type { Entry } from "../api";

type Column = keyof Pick<
  Entry,
  "balance" | "ticks_to_starvation" | "uses" | "age_ticks"
>;

const COLUMNS: Column[] = ["balance", "ticks_to_starvation", "uses", "age_ticks"];

export function LivingTable({
  entries,
  onSelect,
}: {
  entries: Entry[];
  onSelect: (id: string) => void;
}) {
  const [sortBy, setSortBy] = useState<Column>("balance");
  const sorted = [...entries].sort(
    (a, b) => Number(b[sortBy] ?? 0) - Number(a[sortBy] ?? 0),
  );
  if (entries.length === 0) {
    return <section className="panel">No living entries.</section>;
  }
  return (
    <section className="panel">
      <h2>Living entries</h2>
      <table>
        <thead>
          <tr>
            {COLUMNS.map((column) => (
              <th key={column} scope="col">
                <button type="button" onClick={() => setSortBy(column)}>
                  {column.replace(/_/g, " ")}
                </button>
              </th>
            ))}
            <th scope="col">question</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((entry) => (
            <tr key={entry.id} onClick={() => onSelect(entry.id)}>
              <td className="num">{entry.balance.toFixed(2)}</td>
              <td className="num">
                {entry.ticks_to_starvation?.toFixed(1) ?? "—"}
              </td>
              <td className="num">{entry.uses}</td>
              <td className="num">{entry.age_ticks}</td>
              <td>
                {entry.question}
                {entry.pinned && <span className="tag">pinned</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
