import type { State } from "../api";

export function Header({ state }: { state: State }) {
  const { counts } = state;
  const cells: [string, string | number][] = [
    ["tick", state.tick],
    ["alive", counts.alive],
    ["dead", counts.dead],
    ["pinned", counts.pinned],
    ["pending", counts.pending],
    ["total energy", state.total_energy.toFixed(2)],
  ];
  return (
    <header className="panel header">
      {cells.map(([label, value]) => (
        <div key={label}>
          <span className="label">{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </header>
  );
}
