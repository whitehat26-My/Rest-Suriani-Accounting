"use client";

/**
 * The hero of the owner's home screen: one number, one colour, one sentence.
 *
 * The verdict is a traffic light rather than a figure, because "did I do well
 * today?" is the actual question - the ringgit amount is the supporting detail.
 *
 * Layout note: the headline figure gets its own full-width line, and the three
 * stats stack on a phone. Amounts here run to nine characters, and at the type
 * sizes this interface needs, sharing a row would clip them. A clipped number is
 * worse than a tall card.
 */
import { motion } from "framer-motion";
import { longDate, money, toNumber } from "@/lib/format";
import type { DailySummary } from "@/lib/types";

const VERDICTS = {
  good: { color: "#0b7a34", emoji: "😊", word: "Good day" },
  watch: { color: "#b57400", emoji: "😐", word: "Slow day" },
  bad: { color: "#a8341f", emoji: "😟", word: "Careful" },
} as const;

export function TodayCard({ summary }: { summary: DailySummary }) {
  const verdict = VERDICTS[summary.verdict];
  const net = toNumber(summary.net);

  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="rounded-xl3 border-4 bg-surface-raised p-6 shadow-lift sm:p-9"
      style={{ borderColor: verdict.color }}
      aria-labelledby="today-heading"
    >
      <p className="text-lg font-semibold text-ink-secondary">{longDate(summary.day)}</p>

      <div className="mt-5 flex items-center gap-4">
        <span className="text-6xl leading-none sm:text-7xl" aria-hidden="true">
          {verdict.emoji}
        </span>
        <h2
          id="today-heading"
          className="text-3xl font-bold sm:text-4xl"
          style={{ color: verdict.color }}
        >
          {verdict.word}
        </h2>
      </div>

      <p className="tabular mt-3 text-huge font-bold leading-none text-ink-primary">
        {net >= 0 ? "+" : "−"}
        {money(Math.abs(net))}
      </p>

      <p className="mt-4 text-2xl leading-snug text-ink-primary">{summary.verdict_message}</p>

      <dl className="mt-7 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Stat label="Money in today" value={money(summary.money_in)} color="#0b7a34" />
        <Stat label="Money out today" value={money(summary.money_out)} color="#a8341f" />
        <Stat
          label="Money you have now"
          value={money(summary.cash_on_hand)}
          color="#1c5cab"
          wide
        />
      </dl>
    </motion.section>
  );
}

function Stat({
  label,
  value,
  color,
  wide = false,
}: {
  label: string;
  value: string;
  color: string;
  wide?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl bg-surface-sunken px-5 py-4 ${wide ? "sm:col-span-2" : ""}`}
    >
      <dt className="text-lg font-semibold text-ink-secondary">{label}</dt>
      <dd className="tabular mt-1 text-3xl font-bold" style={{ color }}>
        {value}
      </dd>
    </div>
  );
}
