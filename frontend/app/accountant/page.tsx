"use client";

/**
 * Accountant Mode.
 *
 * Same ledger, opposite priorities: density over simplicity, precision over
 * reassurance, and every figure traceable back to the tap that produced it.
 *
 * The visual treatment is deliberately dark and luminous, but the discipline is
 * unchanged where it counts - status colours carry a glyph and a word, charts
 * never share an axis they do not share a scale with, and the two integrity
 * checks (balance sheet balances, cash flow reconciles) are shown on the face of
 * the statements panel rather than assumed.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "@/lib/api";
import { money, shortDate } from "@/lib/format";
import type { AccountantDashboard, Transaction } from "@/lib/types";
import {
  CashBalanceChart,
  DailyFlowChart,
  ExpenseBreakdownChart,
} from "@/components/accountant/charts";
import {
  HealthHero,
  MetricGrid,
  PostingTrail,
  StatementPanel,
  StockWatchlist,
  SuggestionList,
} from "@/components/accountant/panels";
import { PayrollPanel } from "@/components/accountant/payroll";

const PERIODS = [
  { id: "week", label: "7 days" },
  { id: "month", label: "This month" },
  { id: "quarter", label: "90 days" },
  { id: "year", label: "Year" },
  { id: "all", label: "All time" },
] as const;

const VIEWS = [
  { id: "overview", label: "Overview" },
  { id: "payroll", label: "Payroll" },
] as const;

type View = (typeof VIEWS)[number]["id"];

export default function AccountantPage() {
  const [period, setPeriod] = useState<string>("month");
  const [view, setView] = useState<View>("overview");
  const [data, setData] = useState<AccountantDashboard | null>(null);
  const [trail, setTrail] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (next: string) => {
    setLoading(true);
    try {
      const [dashboard, recent] = await Promise.all([
        api.dashboard(next),
        api.recentTransactions(12),
      ]);
      setData(dashboard);
      setTrail(recent);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (view === "overview") void load(period);
  }, [load, period, view]);

  return (
    <main className="theme-accountant relative min-h-screen bg-surface-base">
      <div className="aurora pointer-events-none fixed inset-0 opacity-70" aria-hidden="true" />
      <div
        className="grid-backdrop pointer-events-none fixed inset-0 opacity-30"
        aria-hidden="true"
      />

      <div className="relative">
        <header className="sticky top-0 z-20 border-b border-surface-border bg-surface-base/85 backdrop-blur-xl">
          <div
            className={`mx-auto flex flex-wrap items-center justify-between gap-4 px-6 py-4 ${
              view === "payroll" ? "max-w-[1680px]" : "max-w-7xl"
            }`}
          >
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-accent">
                Restoran Suriani
              </p>
              <h1 className="text-2xl font-bold text-ink-primary">Financial Management</h1>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <div role="tablist" aria-label="Section" className="flex rounded-lg border border-surface-border p-1">
                {VIEWS.map((item) => (
                  <button
                    key={item.id}
                    role="tab"
                    aria-selected={view === item.id}
                    onClick={() => setView(item.id)}
                    className={`rounded-md px-4 py-1.5 text-sm font-semibold transition-colors ${
                      view === item.id
                        ? "bg-accent-soft text-ink-primary"
                        : "text-ink-secondary hover:text-ink-primary"
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>

              {/* One filter row, above the charts, as the interaction rules ask. */}
              <div
                role="group"
                aria-label="Reporting period"
                className="flex rounded-lg border border-surface-border p-1"
              >
                {PERIODS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setPeriod(item.id)}
                    aria-pressed={period === item.id}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                      period === item.id
                        ? "bg-accent-soft text-ink-primary"
                        : "text-ink-secondary hover:text-ink-primary"
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <Link
                href="/owner"
                className="rounded-lg border border-surface-border px-4 py-2 text-sm font-medium text-ink-secondary transition-colors hover:text-ink-primary"
              >
                Daily screen
              </Link>
            </div>
          </div>
        </header>

        <div
          className={`mx-auto px-6 py-8 ${
            view === "payroll" ? "max-w-[1680px]" : "max-w-7xl"
          }`}
        >
          {view === "payroll" ? (
            <PayrollPanel period={period} />
          ) : error ? (
            <div className="glass rounded-xl2 border border-status-critical p-8 text-center">
              <p className="text-lg font-semibold text-ink-primary">{error}</p>
              <button
                type="button"
                onClick={() => void load(period)}
                className="mt-5 rounded-lg bg-accent-soft px-6 py-2.5 text-sm font-semibold text-ink-primary ring-1 ring-inset ring-accent"
              >
                Try again
              </button>
            </div>
          ) : loading && !data ? (
            <LoadingSkeleton />
          ) : data ? (
            <AnimatePresence mode="wait">
              <motion.div
                key={period}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
                className="space-y-6"
              >
                <p className="text-sm text-ink-muted">
                  {shortDate(data.period_start)} — {shortDate(data.period_end)}
                  {loading ? " · refreshing…" : ""}
                </p>

                <HealthHero evaluation={data.evaluation} />

                <div className="grid gap-6 lg:grid-cols-4">
                  <SummaryTile
                    label="Revenue"
                    value={money(data.income_statement.revenue)}
                    caption="Sales for the period"
                  />
                  <SummaryTile
                    label="Gross profit"
                    value={money(data.income_statement.gross_profit)}
                    caption={`${data.income_statement.gross_margin_pct.toFixed(1)}% margin`}
                  />
                  <SummaryTile
                    label="Profit for the period"
                    value={money(data.income_statement.net_profit)}
                    caption={`${data.income_statement.net_margin_pct.toFixed(1)}% net margin`}
                  />
                  <SummaryTile
                    label="Cash at period end"
                    value={money(data.cash_flow.closing_cash)}
                    caption={`Stock on hand ${money(data.inventory_value)}`}
                  />
                </div>

                <div className="grid gap-6 lg:grid-cols-2">
                  <DailyFlowChart points={data.revenue_by_day} />
                  <CashBalanceChart points={data.revenue_by_day} />
                </div>

                <MetricGrid metrics={data.evaluation.metrics} />

                <div className="grid gap-6 lg:grid-cols-2">
                  <ExpenseBreakdownChart items={data.expense_breakdown} />
                  <SuggestionList suggestions={data.evaluation.suggestions} />
                </div>

                <div className="grid gap-6 lg:grid-cols-3">
                  <div className="lg:col-span-2">
                    <StatementPanel
                      incomeStatement={data.income_statement}
                      balanceSheet={data.balance_sheet}
                      cashFlow={data.cash_flow}
                    />
                  </div>
                  <StockWatchlist
                    items={data.low_stock}
                    inventoryValue={data.inventory_value}
                  />
                </div>

                <PostingTrail transactions={trail} />
              </motion.div>
            </AnimatePresence>
          ) : null}
        </div>
      </div>
    </main>
  );
}

function SummaryTile({
  label,
  value,
  caption,
}: {
  label: string;
  value: string;
  caption: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-xl2 border border-surface-border p-5"
    >
      <p className="text-xs uppercase tracking-wider text-ink-muted">{label}</p>
      <p className="tabular mt-2 text-2xl font-bold text-ink-primary">{value}</p>
      <p className="mt-1 text-xs text-ink-secondary">{caption}</p>
    </motion.div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading dashboard">
      <div className="h-44 animate-pulse rounded-xl2 border border-surface-border bg-surface-raised/40" />
      <div className="grid gap-6 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-28 animate-pulse rounded-xl2 border border-surface-border bg-surface-raised/40"
          />
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        {[0, 1].map((i) => (
          <div
            key={i}
            className="h-80 animate-pulse rounded-xl2 border border-surface-border bg-surface-raised/40"
          />
        ))}
      </div>
    </div>
  );
}
