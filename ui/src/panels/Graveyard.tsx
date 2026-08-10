import type { Grave } from "../api";

const ORDER = ["starved", "executed", "merged", "forgotten", "unknown"];

export function Graveyard({ graves }: { graves: Grave[] }) {
  const byCause = new Map<string, Grave[]>();
  for (const grave of graves) {
    byCause.set(grave.cause, [...(byCause.get(grave.cause) ?? []), grave]);
  }
  const known = ORDER.filter((cause) => byCause.has(cause));
  // Anything the server sends that ORDER does not know about still gets
  // shown: a grave that silently vanishes is worse than one in an
  // unexpected group, and nothing ties this list to the Python vocabulary.
  const extra = [...byCause.keys()].filter((c) => !ORDER.includes(c)).sort();
  const causes = [...known, ...extra];
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
