"use client";

/**
 * The non-chart panels of the accountant dashboard: the health hero, the metric
 * tiles, the advice list, the statements and the posting trail.
 *
 * Status colour never travels alone here either - every rated element carries a
 * glyph and a word beside the colour.
 */
import { useState } from "react";
import { motion } from "framer-motion";
import { money, percent, ratingColor, ratingGlyph, ratingWord, shortDate } from "@/lib/format";
import type {
  BalanceSheet,
  CashFlow,
  FinancialEvaluation,
  IncomeStatement,
  InventoryItem,
  Metric,
  StatementSection,
  Suggestion,
  Transaction,
} from "@/lib/types";

// --------------------------------------------------------------------------- //
// Health hero
// --------------------------------------------------------------------------- //
export function HealthHero({ evaluation }: { evaluation: FinancialEvaluation }) {
  const score = evaluation.health_score;
  const rating = score >= 70 ? "good" : score >= 55 ? "watch" : "bad";
  const color = ratingColor(rating);

  // A ring is decoration; the number carries the meaning.
  const circumference = 2 * Math.PI * 54;
  const dash = (score / 100) * circumference;

  return (
    <section className="glass relative overflow-hidden rounded-xl2 border border-surface-border p-7">
      <div className="flex flex-col gap-7 sm:flex-row sm:items-center">
        <div className="relative shrink-0 self-center">
          <svg width="140" height="140" viewBox="0 0 140 140" role="img"
               aria-label={`Financial health score ${score} out of 100, rated ${evaluation.health_grade}`}>
            <circle
              cx="70" cy="70" r="54" fill="none"
              stroke="var(--surface-border)" strokeWidth="10"
            />
            <motion.circle
              cx="70" cy="70" r="54" fill="none"
              stroke={color} strokeWidth="10" strokeLinecap="round"
              transform="rotate(-90 70 70)"
              initial={{ strokeDasharray: `0 ${circumference}` }}
              animate={{ strokeDasharray: `${dash} ${circumference}` }}
              transition={{ duration: 1.1, ease: "easeOut" }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="tabular text-4xl font-bold text-ink-primary">{score}</span>
            <span className="text-xs uppercase tracking-widest text-ink-muted">/ 100</span>
          </div>
        </div>

        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-[0.25em] text-accent">
            Financial health
          </p>
          <h2 className="mt-1 flex items-center gap-2 text-3xl font-bold text-ink-primary">
            <span style={{ color }} aria-hidden="true">
              {ratingGlyph(rating)}
            </span>
            {evaluation.health_grade}
          </h2>
          <p className="mt-3 text-base leading-relaxed text-ink-secondary">
            {evaluation.headline}
          </p>

          <dl className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3">
            <MiniStat label="Working capital" value={money(evaluation.working_capital)} />
            <MiniStat
              label="Cash runway"
              value={
                evaluation.cash_runway_days === null
                  ? "n/a"
                  : `${evaluation.cash_runway_days.toFixed(0)} days`
              }
            />
            <MiniStat
              label="Daily burn"
              value={money(evaluation.average_daily_burn)}
            />
          </dl>
        </div>
      </div>
    </section>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wider text-ink-muted">{label}</dt>
      <dd className="tabular mt-1 text-lg font-semibold text-ink-primary">{value}</dd>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Metric tiles
// --------------------------------------------------------------------------- //
export function MetricGrid({ metrics }: { metrics: Metric[] }) {
  return (
    <section aria-labelledby="metrics-heading">
      <h2 id="metrics-heading" className="mb-4 text-lg font-semibold text-ink-primary">
        Key ratios
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {metrics.map((metric, index) => (
          <motion.article
            key={metric.key}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: index * 0.03 }}
            className="glass group relative overflow-hidden rounded-xl2 border border-surface-border p-5"
          >
            <span
              className="absolute inset-x-0 top-0 h-0.5"
              style={{ backgroundColor: ratingColor(metric.rating) }}
              aria-hidden="true"
            />
            <p className="text-sm font-medium text-ink-secondary">{metric.label}</p>
            <p className="tabular mt-2 text-3xl font-bold text-ink-primary">
              {metric.display}
            </p>
            <p
              className="mt-2 flex items-center gap-1.5 text-xs font-semibold"
              style={{ color: ratingColor(metric.rating) }}
            >
              <span aria-hidden="true">{ratingGlyph(metric.rating)}</span>
              {ratingWord(metric.rating)}
              <span className="font-normal text-ink-muted">· {metric.benchmark}</span>
            </p>
            <p className="mt-3 text-xs leading-relaxed text-ink-muted">
              {metric.explanation}
            </p>
          </motion.article>
        ))}
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Advice
// --------------------------------------------------------------------------- //
const SEVERITY_LABEL: Record<string, string> = {
  critical: "Act now",
  warning: "Watch",
  info: "Note",
  positive: "Good news",
};

export function SuggestionList({ suggestions }: { suggestions: Suggestion[] }) {
  return (
    <section aria-labelledby="advice-heading">
      <h2 id="advice-heading" className="mb-4 text-lg font-semibold text-ink-primary">
        What the numbers are saying
      </h2>
      <ul className="space-y-3">
        {suggestions.map((suggestion, index) => {
          const color = ratingColor(suggestion.severity);
          return (
            <motion.li
              key={`${suggestion.title}-${index}`}
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: index * 0.05 }}
              className="glass rounded-xl2 border border-surface-border p-5"
            >
              <div className="flex items-start gap-3">
                <span
                  className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-sm font-bold"
                  style={{ backgroundColor: `${color}22`, color }}
                  aria-hidden="true"
                >
                  {ratingGlyph(suggestion.severity)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-baseline gap-2">
                    <span className="font-semibold text-ink-primary">{suggestion.title}</span>
                    <span
                      className="rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider"
                      style={{ backgroundColor: `${color}22`, color }}
                    >
                      {SEVERITY_LABEL[suggestion.severity] ?? suggestion.severity}
                    </span>
                  </p>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink-secondary">
                    {suggestion.message}
                  </p>
                  {suggestion.action ? (
                    <p className="mt-2 text-sm font-medium text-accent">
                      → {suggestion.action}
                    </p>
                  ) : null}
                </div>
              </div>
            </motion.li>
          );
        })}
      </ul>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Financial statements
// --------------------------------------------------------------------------- //
type StatementTab = "profit" | "position" | "cash";

export function StatementPanel({
  incomeStatement,
  balanceSheet,
  cashFlow,
}: {
  incomeStatement: IncomeStatement;
  balanceSheet: BalanceSheet;
  cashFlow: CashFlow;
}) {
  const [tab, setTab] = useState<StatementTab>("profit");

  const tabs: { id: StatementTab; label: string; sections: StatementSection[]; note: string }[] = [
    {
      id: "profit",
      label: "Profit or Loss",
      sections: incomeStatement.sections,
      note: `For the period ${shortDate(incomeStatement.period_start)} to ${shortDate(incomeStatement.period_end)}`,
    },
    {
      id: "position",
      label: "Financial Position",
      sections: balanceSheet.sections,
      note: `As at ${shortDate(balanceSheet.as_of)}`,
    },
    {
      id: "cash",
      label: "Cash Flows",
      sections: cashFlow.sections,
      note: `For the period ${shortDate(cashFlow.period_start)} to ${shortDate(cashFlow.period_end)}`,
    },
  ];

  const active = tabs.find((t) => t.id === tab)!;

  return (
    <section className="glass rounded-xl2 border border-surface-border p-6" aria-labelledby="statements-heading">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
        <h2 id="statements-heading" className="text-lg font-semibold text-ink-primary">
          Financial statements
        </h2>
        <IntegrityBadge
          balanced={balanceSheet.balances}
          reconciles={cashFlow.reconciles}
        />
      </div>
      <p className="mb-4 text-sm text-ink-muted">{active.note}</p>

      <div role="tablist" aria-label="Financial statements" className="mb-5 flex flex-wrap gap-2">
        {tabs.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              tab === item.id
                ? "bg-accent-soft text-ink-primary ring-1 ring-inset ring-accent"
                : "text-ink-secondary hover:bg-surface-sunken"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" className="space-y-5">
        {active.sections.map((section) => {
          // A subtotal section carries one line named after itself; the header
          // already shows that figure, so drop the duplicate row.
          const lines =
            section.lines.length === 1 && section.lines[0].label === section.title
              ? []
              : section.lines;
          return (
            <div key={section.title}>
            <div className="flex items-baseline justify-between border-b border-surface-border pb-1.5">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-accent">
                {section.title}
              </h3>
              <span className="tabular text-sm font-semibold text-ink-primary">
                {money(section.total)}
              </span>
            </div>
            {lines.length > 0 ? (
              <ul className="mt-2 space-y-1">
                {lines.map((line, index) => (
                  <li
                    key={`${line.label}-${index}`}
                    className={`flex items-baseline justify-between gap-4 py-1 text-sm ${
                      line.is_total
                        ? "font-bold text-ink-primary"
                        : line.is_subtotal
                          ? "font-semibold text-ink-primary"
                          : "text-ink-secondary"
                    }`}
                  >
                    <span className="min-w-0 flex-1">
                      {line.account_code ? (
                        <span className="tabular mr-2 text-xs text-ink-muted">
                          {line.account_code}
                        </span>
                      ) : null}
                      {line.label}
                      {line.note ? (
                        <span className="ml-2 text-xs text-ink-muted">({line.note})</span>
                      ) : null}
                    </span>
                    <span className="tabular shrink-0">{money(line.amount)}</span>
                  </li>
                ))}
              </ul>
              ) : null}
            </div>
          );
        })}
      </div>

      {tab === "profit" ? (
        <dl className="mt-6 grid grid-cols-2 gap-4 border-t border-surface-border pt-5 sm:grid-cols-4">
          <MiniStat label="Revenue" value={money(incomeStatement.revenue)} />
          <MiniStat label="Gross margin" value={percent(incomeStatement.gross_margin_pct)} />
          <MiniStat label="Net margin" value={percent(incomeStatement.net_margin_pct)} />
          <MiniStat label="Profit" value={money(incomeStatement.net_profit)} />
        </dl>
      ) : null}
    </section>
  );
}

/**
 * The two checks an accountant runs before trusting anything else on the page.
 * They are shown, not hidden, because a silent failure would be worse than a
 * visible one.
 */
function IntegrityBadge({
  balanced,
  reconciles,
}: {
  balanced: boolean;
  reconciles: boolean;
}) {
  const ok = balanced && reconciles;
  const color = ratingColor(ok ? "good" : "bad");
  return (
    <span
      className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold"
      style={{ backgroundColor: `${color}22`, color }}
    >
      <span aria-hidden="true">{ratingGlyph(ok ? "good" : "bad")}</span>
      {ok ? "Balanced and reconciled" : "Check the ledger"}
    </span>
  );
}

// --------------------------------------------------------------------------- //
// The posting trail: what the owner's taps actually did
// --------------------------------------------------------------------------- //
export function PostingTrail({ transactions }: { transactions: Transaction[] }) {
  const [expanded, setExpanded] = useState<number | null>(
    transactions[0]?.id ?? null,
  );

  return (
    <section className="glass rounded-xl2 border border-surface-border p-6" aria-labelledby="trail-heading">
      <h2 id="trail-heading" className="text-lg font-semibold text-ink-primary">
        Automated posting trail
      </h2>
      <p className="mb-5 mt-1 text-sm text-ink-muted">
        Each row is one tap on the owner&apos;s screen. Open it to see the double
        entry the system generated.
      </p>

      <ul className="space-y-2">
        {transactions.map((txn) => {
          const open = expanded === txn.id;
          return (
            <li key={txn.id} className="rounded-lg border border-surface-border">
              <button
                type="button"
                onClick={() => setExpanded(open ? null : txn.id)}
                aria-expanded={open}
                className="flex w-full items-center gap-3 px-4 py-3 text-left"
              >
                <span className="tabular shrink-0 text-xs text-ink-muted">
                  {txn.reference}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm text-ink-secondary">
                  {txn.friendly_summary}
                </span>
                <span className="tabular shrink-0 text-sm font-semibold text-ink-primary">
                  {money(txn.amount)}
                </span>
                <span
                  className="shrink-0 text-xs text-ink-muted transition-transform"
                  style={{ transform: open ? "rotate(90deg)" : undefined }}
                  aria-hidden="true"
                >
                  ▶
                </span>
              </button>

              {open ? (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  className="overflow-hidden border-t border-surface-border px-4 py-3"
                >
                  <p className="mb-2 text-xs uppercase tracking-wider text-ink-muted">
                    {txn.event_type.replace(/_/g, " ").toLowerCase()}
                    {txn.raw_input ? ` · spoken: “${txn.raw_input}”` : ""}
                  </p>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs uppercase tracking-wider text-ink-muted">
                        <th scope="col" className="pb-1 text-left font-medium">Account</th>
                        <th scope="col" className="pb-1 text-right font-medium">Debit</th>
                        <th scope="col" className="pb-1 text-right font-medium">Credit</th>
                      </tr>
                    </thead>
                    <tbody className="tabular">
                      {txn.entries.map((entry) => (
                        <tr key={entry.id} className="border-t border-surface-border/60">
                          <td className="py-1.5 text-ink-secondary">
                            <span className="mr-2 text-xs text-ink-muted">
                              {entry.account_code}
                            </span>
                            {entry.account_name}
                          </td>
                          <td className="py-1.5 text-right text-ink-primary">
                            {entry.side === "DEBIT" ? money(entry.amount) : ""}
                          </td>
                          <td className="py-1.5 text-right text-ink-primary">
                            {entry.side === "CREDIT" ? money(entry.amount) : ""}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </motion.div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Inventory watchlist
// --------------------------------------------------------------------------- //
export function StockWatchlist({
  items,
  inventoryValue,
}: {
  items: InventoryItem[];
  inventoryValue: string;
}) {
  return (
    <section className="glass rounded-xl2 border border-surface-border p-6" aria-labelledby="stock-heading">
      <div className="flex items-baseline justify-between">
        <h2 id="stock-heading" className="text-lg font-semibold text-ink-primary">
          Stock watchlist
        </h2>
        <span className="tabular text-sm text-ink-secondary">
          {money(inventoryValue)} on hand
        </span>
      </div>

      {items.length === 0 ? (
        <p className="mt-6 text-sm text-ink-muted">
          Every item is above its reorder level.
        </p>
      ) : (
        <ul className="mt-5 space-y-3">
          {items.map((item) => {
            const rating = item.status === "critical" ? "bad" : "watch";
            const color = ratingColor(rating);
            return (
              <li key={item.id}>
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="flex items-center gap-2 text-ink-secondary">
                    <span aria-hidden="true">{item.emoji}</span>
                    {item.name}
                  </span>
                  <span className="tabular text-ink-primary">
                    {Number.parseFloat(item.quantity_on_hand).toLocaleString()} {item.unit}
                    {item.days_of_cover !== null ? (
                      <span className="ml-2 text-xs text-ink-muted">
                        ~{item.days_of_cover}d cover
                      </span>
                    ) : null}
                  </span>
                </div>
                <div className="mt-1.5 flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-sunken">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.max(item.stock_ratio * 100, 2)}%` }}
                      transition={{ duration: 0.6 }}
                      className="h-full rounded-full"
                      style={{ backgroundColor: color }}
                    />
                  </div>
                  <span
                    className="flex items-center gap-1 text-xs font-semibold"
                    style={{ color }}
                  >
                    <span aria-hidden="true">{ratingGlyph(rating)}</span>
                    {item.status === "critical" ? "Critical" : "Low"}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
