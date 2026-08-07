import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TimelineRow } from "../api";

// ponytail: population and total_energy share one plot on two y-axes.
// dataviz's general rule is one axis per chart (a dual axis usually
// invents a correlation between unrelated metrics); this pair is the
// documented exception — energy running out *is* the mechanism that
// drives the population collapse this panel exists to show, so the two
// curves timed against each other on one plot is the actual story, not
// a coincidence made to look causal.
export function Timeline({ rows }: { rows: TimelineRow[] }) {
  if (rows.length === 0) {
    return <section className="panel">No ticks recorded yet.</section>;
  }
  return (
    <section className="panel">
      <h2>Population over time</h2>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="var(--line)" />
          {/* Numeric x-axis: a rotated-away log leaves a gap in the tick
              numbers, and it should render as a gap, not an interpolated
              line across it. */}
          <XAxis
            dataKey="tick"
            type="number"
            domain={["dataMin", "dataMax"]}
            tick={{ fill: "var(--ink-faint)", fontSize: 11 }}
            stroke="var(--line-strong)"
          />
          <YAxis
            yAxisId="count"
            allowDecimals={false}
            tick={{ fill: "var(--ink-faint)", fontSize: 11 }}
            stroke="var(--line-strong)"
          />
          <YAxis
            yAxisId="energy"
            orientation="right"
            tick={{ fill: "var(--ink-faint)", fontSize: 11 }}
            stroke="var(--line-strong)"
          />
          <Tooltip
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-sm)",
              fontSize: "0.82rem",
            }}
          />
          <Legend wrapperStyle={{ fontSize: "0.78rem", color: "var(--ink-soft)" }} />
          <Line
            yAxisId="count"
            dataKey="population"
            name="population"
            stroke="var(--chart-series-1)"
            strokeWidth={2}
            dot={false}
          />
          <Line
            yAxisId="energy"
            dataKey="total_energy"
            name="total energy"
            stroke="var(--chart-series-2)"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </section>
  );
}
