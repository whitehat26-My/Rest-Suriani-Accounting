"use client";

/**
 * "Count Stock" - the owner walks the store room and types what she sees.
 *
 * She is never told that the difference between the book figure and her count
 * becomes Cost of Goods Sold; she just counts. The colour bar on each row is the
 * depletion signal, always paired with a word so colour is not the only cue.
 */
import { useState } from "react";
import { motion } from "framer-motion";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import type { InventoryItem } from "@/lib/types";
import { PlainButton } from "./BigButton";

const BANDS: Record<string, { label: string; color: string; glyph: string }> = {
  ok: { label: "Plenty", color: "#0b7a34", glyph: "✓" },
  low: { label: "Running low", color: "#b57400", glyph: "△" },
  critical: { label: "Buy today", color: "#a8341f", glyph: "✕" },
};

export function StockSheet({
  items,
  onDone,
  onCancel,
}: {
  items: InventoryItem[];
  onDone: (message: string) => void;
  onCancel: () => void;
}) {
  const [counts, setCounts] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const filled = Object.entries(counts).filter(([, value]) => value.trim() !== "");

  async function submit() {
    if (filled.length === 0) return;
    setSaving(true);
    setError("");
    try {
      const results = await api.countStock(
        filled.map(([id, value]) => ({
          item_id: Number(id),
          counted_quantity: Number.parseFloat(value).toFixed(3),
        })),
        "Counted by owner",
      );
      const used = results.reduce(
        (total, row) => total + Math.abs(Number.parseFloat(row.variance_value)),
        0,
      );
      onDone(
        `Counted ${results.length} item${results.length === 1 ? "" : "s"}. ` +
          `${money(used)} of food was used.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the count.");
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl">
      <header className="mb-8 flex items-center gap-4">
        <button
          type="button"
          onClick={onCancel}
          aria-label="Go back"
          className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl border-4 border-surface-border bg-surface-raised text-3xl text-ink-primary"
        >
          ←
        </button>
        <div>
          <h1 className="text-4xl font-bold text-[#1c5cab]">Count Stock</h1>
          <p className="text-lg font-medium text-ink-secondary">
            Type how much is left. Skip anything you did not count.
          </p>
        </div>
      </header>

      <ul className="space-y-3">
        {items.map((item) => {
          const band = BANDS[item.status] ?? BANDS.ok;
          const onHand = Number.parseFloat(item.quantity_on_hand);
          return (
            <li
              key={item.id}
              className="rounded-2xl border-4 border-surface-border bg-surface-raised p-4"
            >
              <div className="flex items-center gap-4">
                <span className="text-4xl" aria-hidden="true">
                  {item.emoji}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-2xl font-bold text-ink-primary">{item.name}</p>
                  <p className="text-lg text-ink-secondary">
                    Book says {onHand.toLocaleString()} {item.unit}
                  </p>
                  <p
                    className="mt-1 text-lg font-bold"
                    style={{ color: band.color }}
                  >
                    <span aria-hidden="true">{band.glyph} </span>
                    {band.label}
                  </p>
                </div>
                <div className="w-32 shrink-0">
                  <label htmlFor={`count-${item.id}`} className="sr-only">
                    Counted quantity of {item.name} in {item.unit}
                  </label>
                  <input
                    id={`count-${item.id}`}
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step="0.1"
                    placeholder="—"
                    value={counts[item.id] ?? ""}
                    onChange={(event) =>
                      setCounts((prev) => ({ ...prev, [item.id]: event.target.value }))
                    }
                    className="tabular w-full rounded-xl border-4 border-surface-border bg-surface-sunken px-3 py-4 text-center text-3xl font-bold text-ink-primary"
                  />
                  <p className="mt-1 text-center text-base font-semibold text-ink-muted">
                    {item.unit}
                  </p>
                </div>
              </div>
              <div
                className="mt-3 h-3 w-full overflow-hidden rounded-full bg-surface-sunken"
                role="img"
                aria-label={`${item.name} stock level: ${band.label}`}
              >
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.max(item.stock_ratio * 100, 3)}%` }}
                  transition={{ duration: 0.6 }}
                  className="h-full rounded-full"
                  style={{ backgroundColor: band.color }}
                />
              </div>
            </li>
          );
        })}
      </ul>

      {error ? (
        <p
          className="mt-6 rounded-2xl bg-[#a8341f]/10 px-5 py-4 text-lg font-semibold text-[#8f2b19]"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <div className="sticky bottom-4 mt-8 flex flex-col gap-3 rounded-2xl bg-surface-base/95 p-2 backdrop-blur sm:flex-row">
        <PlainButton onClick={onCancel} className="sm:flex-1">
          Cancel
        </PlainButton>
        <PlainButton
          variant="solid"
          onClick={() => void submit()}
          disabled={saving || filled.length === 0}
          className="sm:flex-[2]"
        >
          {saving
            ? "Saving…"
            : `Save count (${filled.length} item${filled.length === 1 ? "" : "s"})`}
        </PlainButton>
      </div>
    </div>
  );
}
