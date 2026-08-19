"use client";

/**
 * What happened today, in sentences.
 *
 * Each row offers "Undo" rather than "Reverse" or "Delete". Behind that word the
 * backend posts a mirror-image transaction, so the audit trail keeps both the
 * mistake and the correction - but that is the accountant's concern, not hers.
 */
import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import type { Transaction } from "@/lib/types";

export function RecentList({
  transactions,
  onChanged,
}: {
  transactions: Transaction[];
  onChanged: () => void;
}) {
  const [undoing, setUndoing] = useState<number | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);

  async function undo(id: number) {
    setUndoing(id);
    try {
      await api.reverse(id, "Undone by owner");
      onChanged();
    } finally {
      setUndoing(null);
      setConfirming(null);
    }
  }

  if (transactions.length === 0) {
    return (
      <section className="rounded-xl3 border-4 border-dashed border-surface-border bg-surface-raised p-8 text-center">
        <p className="text-3xl" aria-hidden="true">
          📝
        </p>
        <p className="mt-3 text-2xl font-semibold text-ink-primary">
          Nothing written down yet today
        </p>
        <p className="mt-2 text-xl text-ink-secondary">
          Use the big buttons above when money comes in or goes out.
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="today-list-heading">
      <h2 id="today-list-heading" className="mb-4 text-3xl font-bold text-ink-primary">
        Today&apos;s list
      </h2>
      <ul className="space-y-3">
        <AnimatePresence initial={false}>
          {transactions.map((txn) => {
            const isIn = txn.direction === "in";
            const color = isIn ? "#0b7a34" : txn.direction === "out" ? "#a8341f" : "#1c5cab";
            return (
              <motion.li
                key={txn.id}
                layout
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, height: 0 }}
                className={`rounded-2xl border-4 bg-surface-raised p-5 ${
                  txn.is_reversed ? "opacity-50" : ""
                }`}
                style={{ borderColor: txn.is_reversed ? "var(--surface-border)" : color }}
              >
                <div className="flex items-start gap-4">
                  <span className="text-3xl leading-none" aria-hidden="true">
                    {isIn ? "⬆️" : txn.direction === "out" ? "⬇️" : "↔️"}
                  </span>
                  {/* The amount sits under the label rather than beside it, so
                      neither has to shrink on a narrow phone screen. */}
                  <div className="min-w-0 flex-1">
                    <p className="text-xl font-semibold leading-snug text-ink-primary">
                      {txn.friendly_label}
                    </p>
                    <p className="tabular mt-1 text-3xl font-bold" style={{ color }}>
                      {isIn ? "+" : txn.direction === "out" ? "−" : ""}
                      {money(txn.amount)}
                    </p>
                    {txn.raw_input ? (
                      <p className="mt-1 text-lg italic text-ink-muted">
                        You said: &ldquo;{txn.raw_input}&rdquo;
                      </p>
                    ) : null}
                    {txn.is_reversed ? (
                      <p className="mt-1 text-lg font-bold text-ink-muted">Undone</p>
                    ) : null}
                  </div>
                </div>

                {!txn.is_reversed ? (
                  <div className="mt-4">
                    {confirming === txn.id ? (
                      <div className="flex flex-wrap items-center gap-3">
                        <p className="text-lg font-semibold text-ink-primary">
                          Remove this entry?
                        </p>
                        <button
                          type="button"
                          onClick={() => void undo(txn.id)}
                          disabled={undoing === txn.id}
                          className="min-h-[3rem] rounded-xl bg-[#a8341f] px-6 text-lg font-bold text-white disabled:opacity-50"
                        >
                          {undoing === txn.id ? "Removing…" : "Yes, remove"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirming(null)}
                          className="min-h-[3rem] rounded-xl border-2 border-surface-border px-6 text-lg font-bold text-ink-primary"
                        >
                          Keep it
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirming(txn.id)}
                        className="min-h-[3rem] rounded-xl border-2 border-surface-border px-6 text-lg font-semibold text-ink-secondary"
                      >
                        Undo this
                      </button>
                    )}
                  </div>
                ) : null}
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ul>
    </section>
  );
}
