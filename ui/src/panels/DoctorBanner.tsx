import type { Finding } from "../api";

export function DoctorBanner({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return <section className="panel clean">No degeneracy detected.</section>;
  }
  return (
    <section className="panel">
      {findings.map((finding) => (
        <article key={finding.code} className={`finding ${finding.severity}`}>
          <h3>{finding.summary}</h3>
          <p className="label">{finding.evidence}</p>
          <p>{finding.fix}</p>
        </article>
      ))}
    </section>
  );
}
