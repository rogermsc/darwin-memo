import type { State } from "../api";

export function Economics({ report }: { report: State["economics"] }) {
  const { resource, energy } = report;
  return (
    <section className="panel">
      <h2>Economics</h2>
      <p className="headline">
        <strong>{resource.delta_total > 0 ? "+" : ""}{resource.delta_total.toLocaleString()}</strong>
        <span className="label">
          resource delta over {resource.decides} decisions
          {resource.silent > 0 && ` (${resource.silent} silent)`}
        </span>
      </p>
      {/* Deliberately a separate block: energy is dimensionless and must
          never be read as continuous with the resource units above. */}
      <dl className="secondary">
        <dt>energy net</dt>
        <dd>{energy.net.toFixed(3)}</dd>
        <dt>upkeep paid</dt>
        <dd>
          {energy.upkeep_paid.toFixed(3)}
          {!energy.upkeep_exact && <span className="tag">estimated</span>}
        </dd>
      </dl>
      {energy.upkeep_caveat && <p className="label">{energy.upkeep_caveat}</p>}
    </section>
  );
}
