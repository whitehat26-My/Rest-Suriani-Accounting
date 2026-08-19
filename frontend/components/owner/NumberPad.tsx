"use client";

/**
 * A calculator-style keypad, not a text field.
 *
 * A phone keyboard is a poor tool for someone with imprecise touch: the keys are
 * small, it covers half the screen, and it offers dozens of irrelevant symbols.
 * This shows twelve targets, each at least 72px tall, and nothing else.
 */
import { motion } from "framer-motion";
import { money } from "@/lib/format";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "back"] as const;

export function NumberPad({
  value,
  onChange,
  tone = "in",
}: {
  value: string;
  onChange: (next: string) => void;
  tone?: "in" | "out";
}) {
  function press(key: string) {
    if (key === "back") {
      onChange(value.slice(0, -1));
      return;
    }
    if (key === ".") {
      // One decimal point only, and never as the leading character.
      if (value.includes(".") || value === "") return;
      onChange(`${value}.`);
      return;
    }
    // Stop at two decimal places - there is no such thing as a third sen.
    const [, decimals] = value.split(".");
    if (decimals !== undefined && decimals.length >= 2) return;
    // Refuse a runaway amount rather than silently accepting a mis-tap.
    if (value.replace(".", "").length >= 9) return;
    onChange(value === "0" ? key : value + key);
  }

  const display = value === "" ? "0.00" : value;
  const accent = tone === "in" ? "text-[#0b7a34]" : "text-[#a8341f]";

  return (
    <div>
      <div
        className="mb-6 rounded-2xl border-4 border-surface-border bg-surface-sunken px-6 py-6 text-center"
        aria-live="polite"
        aria-atomic="true"
      >
        <p className="text-lg font-semibold uppercase tracking-wide text-ink-muted">
          Amount
        </p>
        <p className={`tabular mt-1 text-giant font-bold ${accent}`}>
          {value === "" ? money(0) : `RM${display}`}
        </p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {KEYS.map((key) => (
          <motion.button
            key={key}
            type="button"
            whileTap={{ scale: 0.94 }}
            onClick={() => press(key)}
            aria-label={key === "back" ? "Delete last digit" : key}
            className="min-h-[4.5rem] rounded-2xl border-4 border-surface-border bg-surface-raised text-4xl font-bold text-ink-primary transition-colors hover:bg-surface-sunken active:bg-surface-sunken"
          >
            {key === "back" ? "⌫" : key}
          </motion.button>
        ))}
      </div>
    </div>
  );
}
