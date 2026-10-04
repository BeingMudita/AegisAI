import { useState, type ComponentProps, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card } from "./ui";

// Mark specs: bars ≤24px with 4px rounded data-ends, 2px lines, ≥8px markers
// with a 2px surface ring, hairline solid gridlines, recessive axes.
const AXIS_TICK = { fill: "var(--muted)", fontSize: 11 };
const TOOLTIP = {
  contentStyle: {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    color: "var(--ink)",
    fontSize: 12,
  },
  labelStyle: { color: "var(--ink)", fontWeight: 600 },
  itemStyle: { color: "var(--ink-2)" },
  cursor: { fill: "var(--grid)", fillOpacity: 0.6 },
};

export const ALLOWED_COLOR = "#2a78d6";
export const DENIED_COLOR = "var(--critical)";

/** A chart card with a Chart / Table toggle so values are never chart-only. */
export function ChartCard({
  title,
  subtitle,
  icon,
  table,
  children,
}: {
  title: string;
  subtitle?: string;
  icon?: ComponentProps<typeof Card>["icon"];
  table: { columns: string[]; rows: (string | number)[][] };
  children: ReactNode;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <Card
      title={title}
      subtitle={subtitle}
      icon={icon}
      className="h-full"
      actions={
        <div className="flex overflow-hidden rounded-lg border border-edge text-xs" role="group" aria-label="View">
          {(["chart", "table"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              aria-pressed={view === v}
              className={`px-2.5 py-1 capitalize ${view === v ? "bg-surface-2 font-semibold text-ink" : "text-ink-2"}`}
            >
              {v}
            </button>
          ))}
        </div>
      }
    >
      {view === "chart" ? (
        children
      ) : (
        <div className="max-h-60 overflow-auto">
          <table className="tabular w-full text-xs">
            <thead>
              <tr>
                {table.columns.map((c) => (
                  <th key={c} className="border-b border-edge px-2 py-1 text-left font-semibold text-ink-2">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i}>
                  {r.map((c, j) => (
                    <td key={j} className="border-b border-edge px-2 py-1 text-ink">
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

const rowHeight = (n: number) => Math.max(120, n * 36 + 40);

/** Single-series horizontal bars (magnitude by category). Optional per-bar colors. */
export function HBarChart({
  data,
  colors,
  format = (v) => String(v),
  domain,
  reference,
  labelWidth = 130,
  height,
}: {
  data: { label: string; value: number }[];
  colors?: string[];
  format?: (v: number) => string;
  domain?: [number, number];
  reference?: { at: number; label: string };
  labelWidth?: number;
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height ?? rowHeight(data.length)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 0 }}>
        <CartesianGrid horizontal={false} stroke="var(--grid)" />
        <XAxis
          type="number"
          domain={domain ?? [0, "auto"]}
          allowDecimals={!!domain}
          tick={AXIS_TICK}
          axisLine={{ stroke: "var(--axis)" }}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="label"
          width={labelWidth}
          tick={{ ...AXIS_TICK, fill: "var(--ink-2)" }}
          axisLine={{ stroke: "var(--axis)" }}
          tickLine={false}
        />
        <Tooltip {...TOOLTIP} formatter={(v) => [format(Number(v)), "Value"]} />
        {reference && (
          <ReferenceLine
            x={reference.at}
            stroke="var(--ink-2)"
            label={{ value: reference.label, position: "top", fill: "var(--ink-2)", fontSize: 11 }}
          />
        )}
        <Bar dataKey="value" fill="var(--series-1)" radius={[0, 4, 4, 0]} maxBarSize={24} isAnimationActive={false}>
          {colors && data.map((d, i) => <Cell key={d.label} fill={colors[i]} />)}
          <LabelList
            dataKey="value"
            position="right"
            formatter={(v: unknown) => format(Number(v))}
            style={{ fill: "var(--ink-2)", fontSize: 11 }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Allowed vs denied decisions per checkpoint — stacked, with a 2px surface gap. */
export function DecisionChart({
  data,
  height,
}: {
  data: { component: string; allowed: number; denied: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height ?? rowHeight(data.length) + 24}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 0 }}>
        <CartesianGrid horizontal={false} stroke="var(--grid)" />
        <XAxis
          type="number"
          allowDecimals={false}
          tick={AXIS_TICK}
          axisLine={{ stroke: "var(--axis)" }}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="component"
          width={80}
          tick={{ ...AXIS_TICK, fill: "var(--ink-2)" }}
          axisLine={{ stroke: "var(--axis)" }}
          tickLine={false}
        />
        <Tooltip {...TOOLTIP} />
        <Legend
          verticalAlign="top"
          height={24}
          iconType="square"
          formatter={(value: string) => <span style={{ color: "var(--ink-2)", fontSize: 12 }}>{value}</span>}
        />
        <Bar
          dataKey="allowed"
          name="Allowed"
          stackId="d"
          fill={ALLOWED_COLOR}
          stroke="var(--surface)"
          strokeWidth={2}
          maxBarSize={24}
          isAnimationActive={false}
        />
        <Bar
          dataKey="denied"
          name="Denied"
          stackId="d"
          fill={DENIED_COLOR}
          stroke="var(--surface)"
          strokeWidth={2}
          radius={[0, 4, 4, 0]}
          maxBarSize={24}
          isAnimationActive={false}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** One subject's trust score over its assessments, with the gating threshold. */
export function TrustLine({
  points,
  threshold,
}: {
  points: { step: number; score: number; signal: string; time: string }[];
  threshold: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={points} margin={{ top: 16, right: 24, bottom: 4, left: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis dataKey="step" tick={AXIS_TICK} axisLine={{ stroke: "var(--axis)" }} tickLine={false} />
        <YAxis
          domain={[0, 1]}
          ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
          width={36}
          tick={AXIS_TICK}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          {...TOOLTIP}
          cursor={{ stroke: "var(--axis)" }}
          labelFormatter={(step) => {
            const p = points.find((x) => x.step === step);
            return p ? `#${step} · ${p.signal} · ${p.time}` : `#${step}`;
          }}
          formatter={(v) => [Number(v).toFixed(2), "Trust"]}
        />
        <ReferenceLine
          y={threshold}
          stroke="var(--ink-2)"
          label={{
            value: `threshold ${threshold.toFixed(2)}`,
            position: "insideTopRight",
            fill: "var(--ink-2)",
            fontSize: 11,
          }}
        />
        <Line
          type="stepAfter"
          dataKey="score"
          stroke="var(--series-1)"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          dot={{ r: 4, fill: "var(--series-1)", stroke: "var(--surface)", strokeWidth: 2 }}
          activeDot={{ r: 6, fill: "var(--series-1)", stroke: "var(--surface)", strokeWidth: 2 }}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
