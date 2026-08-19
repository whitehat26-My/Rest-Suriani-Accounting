"use client";

/**
 * The dashboard's charts.
 *
 * Three deliberate choices, all from the same reasoning:
 *
 * 1. Daily flows and the cash balance are two charts, never one. They differ by
 *    an order of magnitude, and a second y-axis would let the reader infer a
 *    relationship between two lines that share no scale.
 * 2. The expense breakdown is a sorted horizontal bar chart, not a donut. The
 *    question is "which costs are biggest and by how much", and length answers
 *    that far more precisely than angle.
 * 3. Series colours come from the validated categorical palette, stepped for the
 *    dark surface. Status colours are never reused as series colours, so a red
 *    bar never has to mean both "expenses" and "danger".
 */
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { money, moneyShort, shortDate, toNumber } from "@/lib/format";
import type { ExpenseBreakdownItem, TrendPoint } from "@/lib/types";

// Categorical slots 1 and 2, stepped for the dark surface (#141c30).
const SERIES_IN = "#3987e5";
const SERIES_OUT = "#d95926";
const GRID = "rgba(169, 182, 208, 0.14)";
const AXIS_TEXT = "#71809d";

function ChartFrame({
  title,
  subtitle,
  legend,
  children,
  table,
}: {
  title: string;
  subtitle?: string;
  legend?: { color: string; label: string }[];
  children: React.ReactNode;
  table?: React.ReactNode;
}) {
  return (
    <section className="glass rounded-xl2 border border-surface-border p-6">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-3">
        <h3 className="text-lg font-semibold text-ink-primary">{title}</h3>
        {legend ? (
          <ul className="flex flex-wrap gap-4">
            {legend.map((key) => (
              <li
                key={key.label}
                className="flex items-center gap-2 text-sm font-medium text-ink-secondary"
              >
                <span
                  className="inline-block h-2.5 w-2.5 rounded-sm"
                  style={{ backgroundColor: key.color }}
                />
                {key.label}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {subtitle ? <p className="mb-4 text-sm text-ink-muted">{subtitle}</p> : null}
      {children}
      {table ? (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-ink-muted hover:text-ink-secondary">
            View as table
          </summary>
          <div className="mt-3 max-h-64 overflow-y-auto">{table}</div>
        </details>
      ) : null}
    </section>
  );
}

function DarkTooltip({
  active,
  payload,
  label,
  rows,
}: {
  active?: boolean;
  payload?: { dataKey?: string | number; value?: number }[];
  label?: string;
  rows: { key: string; label: string; color: string }[];
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised px-4 py-3 shadow-lift">
      <p className="mb-2 text-sm font-semibold text-ink-primary">{label}</p>
      {rows.map((row) => {
        const entry = payload.find((p) => p.dataKey === row.key);
        if (entry?.value === undefined) return null;
        return (
          <p key={row.key} className="flex items-center gap-2 text-sm text-ink-secondary">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ backgroundColor: row.color }}
            />
            {row.label}
            <span className="tabular ml-auto font-semibold text-ink-primary">
              {money(entry.value)}
            </span>
          </p>
        );
      })}
    </div>
  );
}

/** Daily cash in and cash out. Two lines, one scale. */
export function DailyFlowChart({ points }: { points: TrendPoint[] }) {
  const data = points.map((point) => ({
    day: shortDate(point.day),
    moneyIn: toNumber(point.money_in),
    moneyOut: toNumber(point.money_out),
  }));

  return (
    <ChartFrame
      title="Daily cash movement"
      subtitle="Cash and bank receipts against payments, day by day"
      legend={[
        { color: SERIES_IN, label: "Money in" },
        { color: SERIES_OUT, label: "Money out" },
      ]}
      table={
        <table className="w-full text-left text-sm">
          <thead className="text-ink-muted">
            <tr>
              <th scope="col" className="py-1.5 font-medium">Day</th>
              <th scope="col" className="py-1.5 text-right font-medium">In</th>
              <th scope="col" className="py-1.5 text-right font-medium">Out</th>
            </tr>
          </thead>
          <tbody className="tabular">
            {data.map((row) => (
              <tr key={row.day} className="border-t border-surface-border">
                <th scope="row" className="py-1.5 font-normal text-ink-secondary">
                  {row.day}
                </th>
                <td className="py-1.5 text-right text-ink-primary">{money(row.moneyIn)}</td>
                <td className="py-1.5 text-right text-ink-primary">{money(row.moneyOut)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis
              dataKey="day"
              tickLine={false}
              axisLine={false}
              minTickGap={28}
              tick={{ fill: AXIS_TEXT, fontSize: 12 }}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={56}
              tickFormatter={(value: number) => moneyShort(value)}
              tick={{ fill: AXIS_TEXT, fontSize: 12 }}
            />
            <Tooltip
              cursor={{ stroke: "rgba(169,182,208,0.35)", strokeWidth: 1 }}
              content={
                <DarkTooltip
                  rows={[
                    { key: "moneyIn", label: "Money in", color: SERIES_IN },
                    { key: "moneyOut", label: "Money out", color: SERIES_OUT },
                  ]}
                />
              }
            />
            <Line
              type="monotone"
              dataKey="moneyIn"
              name="Money in"
              stroke={SERIES_IN}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 5, strokeWidth: 2, stroke: "#141c30" }}
            />
            <Line
              type="monotone"
              dataKey="moneyOut"
              name="Money out"
              stroke={SERIES_OUT}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 5, strokeWidth: 2, stroke: "#141c30" }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartFrame>
  );
}

/** The running cash balance. One series, so the title is the legend. */
export function CashBalanceChart({ points }: { points: TrendPoint[] }) {
  const data = points.map((point) => ({
    day: shortDate(point.day),
    cash: toNumber(point.cumulative_cash),
  }));

  return (
    <ChartFrame
      title="Cash position"
      subtitle="Till and bank combined, at the close of each day"
    >
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <defs>
              <linearGradient id="cashFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={SERIES_IN} stopOpacity={0.45} />
                <stop offset="100%" stopColor={SERIES_IN} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis
              dataKey="day"
              tickLine={false}
              axisLine={false}
              minTickGap={28}
              tick={{ fill: AXIS_TEXT, fontSize: 12 }}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={56}
              tickFormatter={(value: number) => moneyShort(value)}
              tick={{ fill: AXIS_TEXT, fontSize: 12 }}
            />
            <Tooltip
              cursor={{ stroke: "rgba(169,182,208,0.35)", strokeWidth: 1 }}
              content={
                <DarkTooltip rows={[{ key: "cash", label: "Cash", color: SERIES_IN }]} />
              }
            />
            <Area
              type="monotone"
              dataKey="cash"
              name="Cash"
              stroke={SERIES_IN}
              strokeWidth={2}
              fill="url(#cashFill)"
              activeDot={{ r: 5, strokeWidth: 2, stroke: "#141c30" }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </ChartFrame>
  );
}

/**
 * Where the money went. Sorted descending, one hue, labelled directly.
 *
 * Every bar is the same colour on purpose: the categories are already
 * identified by the axis labels, so colouring each one differently would encode
 * nothing and would burn the categorical palette on a non-question.
 */
export function ExpenseBreakdownChart({ items }: { items: ExpenseBreakdownItem[] }) {
  if (items.length === 0) {
    return (
      <ChartFrame title="Where the money went">
        <p className="py-16 text-center text-sm text-ink-muted">
          No expenses recorded in this period.
        </p>
      </ChartFrame>
    );
  }

  const data = items.slice(0, 10).map((item) => ({
    label: item.label.replace(/ (Expense|& Consumables|- Food & Beverage)$/, ""),
    amount: toNumber(item.amount),
    percentage: item.percentage,
  }));

  return (
    <ChartFrame
      title="Where the money went"
      subtitle="Largest cost first, share of total expenses shown alongside"
    >
      <div style={{ height: Math.max(data.length * 42, 160) }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 4, right: 16, bottom: 4, left: 4 }}
            barCategoryGap={6}
          >
            <CartesianGrid horizontal={false} stroke={GRID} />
            <XAxis
              type="number"
              tickLine={false}
              axisLine={false}
              tickFormatter={(value: number) => moneyShort(value)}
              tick={{ fill: AXIS_TEXT, fontSize: 12 }}
            />
            <YAxis
              type="category"
              dataKey="label"
              tickLine={false}
              axisLine={false}
              width={168}
              tick={{ fill: "var(--text-secondary)", fontSize: 12 }}
            />
            <Tooltip
              cursor={{ fill: "rgba(169,182,208,0.08)" }}
              content={
                <DarkTooltip rows={[{ key: "amount", label: "Spent", color: SERIES_IN }]} />
              }
            />
            <Bar dataKey="amount" radius={[0, 4, 4, 0]} maxBarSize={20} name="Spent">
              {data.map((row) => (
                <Cell key={row.label} fill={SERIES_IN} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Direct labels: the value and share for each bar, outside the plot so
          they never sit on top of a mark. */}
      <ul className="mt-3 space-y-1.5">
        {data.map((row) => (
          <li key={row.label} className="flex items-baseline gap-3 text-sm">
            <span className="flex-1 truncate text-ink-secondary">{row.label}</span>
            <span className="tabular font-semibold text-ink-primary">{money(row.amount)}</span>
            <span className="tabular w-14 text-right text-ink-muted">
              {row.percentage.toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </ChartFrame>
  );
}
