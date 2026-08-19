"use client";

/**
 * Seven days of money in and money out.
 *
 * The sentence above the chart carries the meaning; the bars are the supporting
 * detail. That ordering matters for this user - if she reads nothing but the
 * sentence, she has still got the answer.
 *
 * Colours are the validated categorical palette (slots 1 and 2), which clear the
 * colour-vision-deficiency separation gate against a white surface. The legend
 * is always present, so identity never rests on colour alone.
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { money, moneyShort, shortDate, toNumber } from "@/lib/format";
import type { TrendPoint } from "@/lib/types";

const IN = "#2a78d6";
const OUT = "#eb6834";

export function WeekChart({ points }: { points: TrendPoint[] }) {
  if (points.length === 0) return null;

  const data = points.map((point) => ({
    day: shortDate(point.day),
    in: toNumber(point.money_in),
    out: toNumber(point.money_out),
  }));

  const totalIn = data.reduce((sum, row) => sum + row.in, 0);
  const totalOut = data.reduce((sum, row) => sum + row.out, 0);
  const kept = totalIn - totalOut;

  return (
    <section
      className="rounded-xl3 border-4 border-surface-border bg-surface-raised p-6 sm:p-8"
      aria-labelledby="week-heading"
    >
      <h2 id="week-heading" className="text-3xl font-bold text-ink-primary">
        Last 7 days
      </h2>
      <p className="mt-2 text-2xl leading-snug text-ink-primary">
        You took in <strong style={{ color: IN }}>{money(totalIn)}</strong> and spent{" "}
        <strong style={{ color: OUT }}>{money(totalOut)}</strong>.{" "}
        {kept >= 0 ? (
          <>
            You kept <strong className="text-[#0b7a34]">{money(kept)}</strong>.
          </>
        ) : (
          <>
            You are <strong className="text-[#a8341f]">{money(Math.abs(kept))}</strong> short.
          </>
        )}
      </p>

      {/* The legend sits above the plot so it is read before the bars. */}
      <ul className="mt-6 flex flex-wrap gap-6" aria-hidden="true">
        <LegendKey color={IN} label="Money in" />
        <LegendKey color={OUT} label="Money out" />
      </ul>

      <div className="mt-4 h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 4 }} barGap={2}>
            <CartesianGrid
              vertical={false}
              stroke="var(--surface-border)"
              strokeDasharray="3 3"
            />
            <XAxis
              dataKey="day"
              tickLine={false}
              axisLine={false}
              tick={{ fill: "var(--text-secondary)", fontSize: 15, fontWeight: 600 }}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={58}
              tickFormatter={(value: number) => moneyShort(value)}
              tick={{ fill: "var(--text-muted)", fontSize: 14 }}
            />
            <Tooltip
              cursor={{ fill: "var(--surface-sunken)" }}
              content={<OwnerTooltip />}
            />
            <Bar dataKey="in" radius={[4, 4, 0, 0]} maxBarSize={26} name="Money in">
              {data.map((row) => (
                <Cell key={`in-${row.day}`} fill={IN} />
              ))}
            </Bar>
            <Bar dataKey="out" radius={[4, 4, 0, 0]} maxBarSize={26} name="Money out">
              {data.map((row) => (
                <Cell key={`out-${row.day}`} fill={OUT} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* The same numbers, readable by a screen reader and by anyone who finds
          the chart hard to parse. */}
      <details className="mt-4">
        <summary className="cursor-pointer text-xl font-semibold text-ink-secondary">
          Show the numbers
        </summary>
        <table className="mt-3 w-full text-left text-lg">
          <thead>
            <tr className="text-ink-secondary">
              <th scope="col" className="py-2 font-semibold">Day</th>
              <th scope="col" className="py-2 text-right font-semibold">In</th>
              <th scope="col" className="py-2 text-right font-semibold">Out</th>
            </tr>
          </thead>
          <tbody className="tabular">
            {data.map((row) => (
              <tr key={row.day} className="border-t-2 border-surface-border">
                <th scope="row" className="py-2 font-medium text-ink-primary">
                  {row.day}
                </th>
                <td className="py-2 text-right text-ink-primary">{money(row.in)}</td>
                <td className="py-2 text-right text-ink-primary">{money(row.out)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}

function LegendKey({ color, label }: { color: string; label: string }) {
  return (
    <li className="flex items-center gap-2 text-xl font-semibold text-ink-primary">
      <span
        className="inline-block h-4 w-4 rounded-sm"
        style={{ backgroundColor: color }}
      />
      {label}
    </li>
  );
}

function OwnerTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { dataKey?: string | number; value?: number }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const moneyIn = payload.find((p) => p.dataKey === "in")?.value ?? 0;
  const moneyOut = payload.find((p) => p.dataKey === "out")?.value ?? 0;
  return (
    <div className="rounded-xl border-2 border-surface-border bg-surface-raised px-4 py-3 shadow-lift">
      <p className="text-lg font-bold text-ink-primary">{label}</p>
      <p className="tabular text-lg" style={{ color: IN }}>
        In {money(moneyIn)}
      </p>
      <p className="tabular text-lg" style={{ color: OUT }}>
        Out {money(moneyOut)}
      </p>
    </div>
  );
}
