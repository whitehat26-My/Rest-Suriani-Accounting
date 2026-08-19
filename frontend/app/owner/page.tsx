"use client";

/**
 * Grandma Mode.
 *
 * The whole daily job is three buttons. Everything else on the screen is a
 * report of what those buttons have already done. There is no navigation menu,
 * no settings, no jargon, and no screen that needs scrolling before the primary
 * action is reachable.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import type {
  DailySummary,
  InventoryItem,
  SpendingCategory,
  Transaction,
  TrendPoint,
  VoiceParseResult,
} from "@/lib/types";
import { BigButton } from "@/components/owner/BigButton";
import { MoneyFlow } from "@/components/owner/MoneyFlow";
import { RecentList } from "@/components/owner/RecentList";
import { StockSheet } from "@/components/owner/StockSheet";
import { TodayCard } from "@/components/owner/TodayCard";
import { VoiceInput } from "@/components/owner/VoiceInput";
import { WeekChart } from "@/components/owner/WeekChart";
import { useAuth } from "@/lib/useAuth";

type Screen = "home" | "in" | "out" | "voice" | "stock";

export default function OwnerPage() {
  const [screen, setScreen] = useState<Screen>("home");
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [week, setWeek] = useState<TrendPoint[]>([]);
  const [categories, setCategories] = useState<SpendingCategory[]>([]);
  const [stock, setStock] = useState<InventoryItem[]>([]);
  const [prefill, setPrefill] = useState<VoiceParseResult | null>(null);
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { status, loading: authLoading } = useAuth();

  const load = useCallback(async () => {
    try {
      const [dailyData, weekData, categoryData, stockData] = await Promise.all([
        api.dailySummary(),
        api.weekTrend(7),
        api.spendingCategories(),
        api.inventory(),
      ]);
      setSummary(dailyData);
      setWeek(weekData);
      setCategories(categoryData);
      setStock(stockData);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }, []);

  const signedOut = Boolean(status?.auth_enabled && !status.signed_in);

  useEffect(() => {
    if (!authLoading && signedOut) {
      window.location.replace("/signin?redirect_to=%2Fowner");
      return;
    }
    if (!authLoading && !signedOut) void load();
  }, [authLoading, signedOut, load]);

  // The confirmation banner is the owner's receipt that the tap worked.
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 6000);
    return () => clearTimeout(timer);
  }, [toast]);

  function finish(txn: Transaction) {
    setToast(`Saved. ${txn.friendly_summary}`);
    setScreen("home");
    setPrefill(null);
    void load();
  }

  function handleParsed(result: VoiceParseResult) {
    if (!result.understood || !result.kind) {
      setToast(result.confirmation);
      return;
    }
    setPrefill(result);
    setScreen(result.kind === "in" ? "in" : "out");
  }

  const lowStock = stock.filter((item) => item.status !== "ok");

  return (
    <main className="theme-owner min-h-screen bg-surface-base pb-16">
      <header className="border-b-4 border-surface-border bg-surface-raised">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-4 px-5 py-4">
          <div className="flex min-w-0 items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/brand/logo.png"
              alt="Restoran Suriani"
              className="h-12 w-auto rounded-lg sm:h-14"
            />
            {/* The logo already says whose book this is, so on a phone the
                subtitle gives up its space to the button rather than wrapping
                onto three lines. */}
            <p className="hidden text-lg font-semibold text-ink-secondary sm:block sm:text-xl">
              Daily money book
            </p>
          </div>
          <Link
            href="/accountant"
            className="min-h-[3.5rem] shrink-0 whitespace-nowrap rounded-xl border-4 border-surface-border px-5 py-2 text-lg font-bold text-ink-secondary"
          >
            Accounts
          </Link>
        </div>
      </header>

      <AnimatePresence>
        {toast ? (
          <motion.div
            initial={{ opacity: 0, y: -12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            className="sticky top-0 z-20 bg-[#0b7a34] px-5 py-4 text-center"
            role="status"
          >
            <p className="mx-auto max-w-3xl text-xl font-bold text-white">{toast}</p>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <div className="mx-auto max-w-3xl px-5 py-7">
        {authLoading || signedOut ? (
          <p className="py-24 text-center text-3xl font-semibold text-ink-secondary">
            Loading…
          </p>
        ) : loading ? (
          <p className="py-24 text-center text-3xl font-semibold text-ink-secondary">
            Loading…
          </p>
        ) : error ? (
          <div className="rounded-xl3 border-4 border-[#a8341f] bg-surface-raised p-8 text-center">
            <p className="text-3xl" aria-hidden="true">
              ⚠️
            </p>
            <p className="mt-3 text-2xl font-bold text-ink-primary">{error}</p>
            <button
              type="button"
              onClick={() => void load()}
              className="mt-6 min-h-[4rem] rounded-2xl bg-[#1c5cab] px-8 text-2xl font-bold text-white"
            >
              Try again
            </button>
          </div>
        ) : (
          <AnimatePresence mode="wait">
            {screen === "home" && summary ? (
              <motion.div
                key="home"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="space-y-7"
              >
                <TodayCard summary={summary} />

                <div className="space-y-4">
                  <BigButton
                    tone="in"
                    emoji="💰"
                    label="Money In"
                    hint="A customer paid you"
                    onClick={() => setScreen("in")}
                  />
                  <BigButton
                    tone="out"
                    emoji="🛒"
                    label="Money Out"
                    hint="You paid for something"
                    onClick={() => setScreen("out")}
                  />
                  <BigButton
                    tone="stock"
                    emoji="📦"
                    label="Count Stock"
                    hint={
                      lowStock.length > 0
                        ? `${lowStock.length} item${lowStock.length === 1 ? "" : "s"} running low`
                        : "Check what is in the store room"
                    }
                    onClick={() => setScreen("stock")}
                  />
                  <BigButton
                    tone="neutral"
                    emoji="🎤"
                    label="Just Say It"
                    hint="Speak instead of tapping"
                    onClick={() => setScreen("voice")}
                  />
                </div>

                {lowStock.length > 0 ? (
                  <section
                    className="rounded-xl3 border-4 border-[#b57400] bg-[#b57400]/5 p-6"
                    aria-labelledby="low-stock-heading"
                  >
                    <h2
                      id="low-stock-heading"
                      className="text-2xl font-bold text-[#8a5800]"
                    >
                      <span aria-hidden="true">△ </span>
                      Buy these soon
                    </h2>
                    <ul className="mt-4 space-y-2">
                      {lowStock.slice(0, 5).map((item) => (
                        <li
                          key={item.id}
                          className="flex items-center gap-3 text-xl text-ink-primary"
                        >
                          <span className="text-3xl" aria-hidden="true">
                            {item.emoji}
                          </span>
                          <span className="flex-1 font-semibold">{item.name}</span>
                          <span className="tabular font-bold">
                            {Number.parseFloat(item.quantity_on_hand).toLocaleString()}{" "}
                            {item.unit} left
                          </span>
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}

                <WeekChart points={week} />

                <RecentList transactions={summary.recent} onChanged={() => void load()} />
              </motion.div>
            ) : null}

            {screen === "in" || screen === "out" ? (
              <motion.div
                key={screen}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <MoneyFlow
                  kind={screen}
                  categories={categories}
                  prefill={prefill}
                  onDone={finish}
                  onCancel={() => {
                    setPrefill(null);
                    setScreen("home");
                  }}
                />
              </motion.div>
            ) : null}

            {screen === "voice" ? (
              <motion.div key="voice" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <VoiceInput onParsed={handleParsed} onCancel={() => setScreen("home")} />
              </motion.div>
            ) : null}

            {screen === "stock" ? (
              <motion.div key="stock" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <StockSheet
                  items={stock}
                  onCancel={() => setScreen("home")}
                  onDone={(message) => {
                    setToast(message);
                    setScreen("home");
                    void load();
                  }}
                />
              </motion.div>
            ) : null}
          </AnimatePresence>
        )}
      </div>

      {summary && screen === "home" ? (
        <footer className="mx-auto max-w-3xl px-5">
          <p className="text-center text-lg text-ink-muted">
            Money in the till and bank right now: {money(summary.cash_on_hand)}
          </p>
        </footer>
      ) : null}
    </main>
  );
}
