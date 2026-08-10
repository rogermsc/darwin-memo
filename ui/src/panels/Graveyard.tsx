import type { Grave } from "../api";

const ORDER = ["starved", "executed", "merged", "forgotten", "unknown"];

export function Graveyard({ graves }: { graves: Grave[] }) {
  const byCause = new Map<string, Grave[]>();
  for (const grave of graves) {
    byCause.set(grave.cause, [...(byCause.get(grave.cause) ?? []), grave]);
  }
  const causes = ORDER.filter((cause) => byCause.has(cause));
  return (
    <section className="panel">
      <h2>Graveyard</h2>
      <div className="cause-counts">
        {causes.map((cause) => (
          <div key={cause} className={`cause ${cause}`}>
            <strong>{byCause.get(cause)!.length}</strong>
            <span className="label">{cause}</span>
          </div>
        ))}
      </div>
      {causes.map((cause) => (
        <details key={cause}>
          <summary>
            {cause} ({byCause.get(cause)!.length})
          </summary>
          <ul>
            {byCause.get(cause)!.map((grave) => (
              <li key={grave.id}>
                <code>{grave.id}</code> {grave.question ?? "(no question on record)"}
              </li>
            ))}
          </ul>
        </details>
      ))}
      {graves.length === 0 && <p>Nothing has died yet.</p>}
    </section>
  );
}
