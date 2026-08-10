import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TimelineRow } from "../api";

const TOOLTIP_STYLE = {
  background: "var(--surface)",
  border: "1px solid var(--line)",
  borderRadius: "var(--radius-sm)",
  fontSize: "0.82rem",
};
const AXIS_TICK = { fill: "var(--ink-faint)", fontSize: 11 };
// Fixed on both charts so the two plot areas are the same width and the
// ticks actually line up vertically, not just share a nominal domain.
const Y_WIDTH = 46;

// ponytail: two stacked charts on a shared, explicitly-set tick domain,
// not one plot with a second y-axis. A second y-axis has a free
// parameter — wherever its scale is set decides where the lines cross —
// so it can imply a relationship the data doesn't actually fix. Stacked
// and aligned shows the same mechanism (energy drains, population
// collapses) with nothing tunable.
export function Timeline({ rows }: { rows: TimelineRow[] }) {
  if (rows.length === 0) {
    return <section className="panel">No ticks recorded yet.</section>;
  }
  // `rows` is chronological (see timeline()'s docstring), so the first
  // and last rows ARE the min and max -- no need to scan, and no spread
  // over a potentially huge array. Math.min(...ticks)/Math.max(...ticks)
  // throws past ~100k arguments; a fully rotated log (40 MB) holds far
  // more tick rows than that.
  const domain: [number, number] = [rows[0].tick, rows[rows.length - 1].tick];
  return (
    <section className="panel">
      <h2>Population over time</h2>
      <div className="label">population</div>
      <ResponsiveContainer width="100%" height={140}>
        <LineChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="var(--line)" />
          {/* Numeric x-axis: a rotated-away log leaves a gap in the tick
              numbers, and it should render as a gap, not an interpolated
              line across it. Tick labels hidden here — the bottom chart
              carries them for both, on the same domain. */}
          <XAxis
            dataKey="tick"
            type="number"
            domain={domain}
            tick={false}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            width={Y_WIDTH}
            allowDecimals={false}
            tick={AXIS_TICK}
            stroke="var(--line-strong)"
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Line
            dataKey="population"
            name="population"
            stroke="var(--chart-series-1)"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <div className="label" style={{ marginTop: "var(--space-4)" }}>
        total energy
      </div>
      <ResponsiveContainer width="100%" height={170}>
        <LineChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="var(--line)" />
          <XAxis
            dataKey="tick"
            type="number"
            domain={domain}
            tick={AXIS_TICK}
            stroke="var(--line-strong)"
          />
          <YAxis width={Y_WIDTH} tick={AXIS_TICK} stroke="var(--line-strong)" />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Line
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
