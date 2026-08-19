"use client";

/**
 * The PIN gate for Accountant Mode.
 *
 * This is the boundary that actually matters day to day. The tablet sits
 * unlocked beside the till for the whole shift, so the session being valid says
 * nothing about who is holding it. The PIN says "the person asking for the wage
 * bill right now is the owner".
 *
 * It uses the same oversized keypad as the daily screen, because the owner is
 * the person who types it most often.
 */
import { useState } from "react";
import { motion } from "framer-motion";
import { api } from "@/lib/api";
import type { AuthStatus } from "@/lib/types";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"];
const MAX_LENGTH = 8;

export function PinGate({
  status,
  onUnlocked,
}: {
  status: AuthStatus;
  onUnlocked: (next: AuthStatus) => void;
}) {
  // Someone who has never set a PIN is choosing one, not entering one.
  const choosing = !status.user?.has_pin;

  const [pin, setPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [stage, setStage] = useState<"enter" | "confirm">("enter");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const value = stage === "confirm" ? confirmPin : pin;
  const setValue = stage === "confirm" ? setConfirmPin : setPin;

  function press(key: string) {
    setError("");
    if (key === "back") return setValue(value.slice(0, -1));
    if (key === "clear") return setValue("");
    if (value.length >= MAX_LENGTH) return;
    setValue(value + key);
  }

  async function submit() {
    setBusy(true);
    setError("");
    try {
      if (!choosing) {
        onUnlocked(await api.verifyPin(pin));
        return;
      }
      if (stage === "enter") {
        if (pin.length < 4) {
          setError("Choose at least 4 digits.");
          return;
        }
        setStage("confirm");
        return;
      }
      if (pin !== confirmPin) {
        setError("The two PINs do not match. Try again.");
        setConfirmPin("");
        setStage("enter");
        setPin("");
        return;
      }
      onUnlocked(await api.setPin(pin));
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work.");
      setValue("");
    } finally {
      setBusy(false);
    }
  }

  const heading = choosing
    ? stage === "enter"
      ? "Choose a PIN"
      : "Enter it once more"
    : "Enter your PIN";

  const explanation = choosing
    ? "This PIN opens the accounts on this device. Pick something you will remember but others will not guess."
    : "The accounts, reports and payroll are behind this PIN.";

  return (
    <main className="theme-accountant relative flex min-h-screen items-center justify-center overflow-hidden bg-surface-base px-6 py-12">
      <div className="aurora pointer-events-none absolute inset-0" aria-hidden="true" />

      <motion.div
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        className="glass relative w-full max-w-sm rounded-xl3 border border-surface-border p-8 text-center"
      >
        <span className="text-4xl" aria-hidden="true">
          🔐
        </span>
        <h1 className="mt-3 text-2xl font-bold text-ink-primary">{heading}</h1>
        <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-ink-secondary">
          {explanation}
        </p>

        <div
          className="mt-7 flex justify-center gap-3"
          role="img"
          aria-label={`${value.length} of up to ${MAX_LENGTH} digits entered`}
        >
          {Array.from({ length: Math.max(value.length, 4) }).map((_, index) => (
            <span
              key={index}
              className={`h-3.5 w-3.5 rounded-full transition-colors ${
                index < value.length ? "bg-accent" : "bg-surface-border"
              }`}
            />
          ))}
        </div>

        {error ? (
          <p
            className="mt-5 rounded-xl border border-status-critical bg-status-critical/10 px-4 py-3 text-sm font-medium text-ink-primary"
            role="alert"
          >
            {error}
          </p>
        ) : null}

        <div className="mt-7 grid grid-cols-3 gap-2.5">
          {KEYS.map((key) => (
            <motion.button
              key={key}
              type="button"
              whileTap={{ scale: 0.94 }}
              onClick={() => press(key)}
              disabled={busy}
              aria-label={
                key === "back" ? "Delete last digit" : key === "clear" ? "Clear" : key
              }
              className="min-h-[3.75rem] rounded-xl border border-surface-border bg-surface-raised/60 text-xl font-semibold text-ink-primary transition-colors hover:bg-surface-sunken disabled:opacity-50"
            >
              {key === "back" ? "⌫" : key === "clear" ? "C" : key}
            </motion.button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || value.length < 4}
          className="mt-5 min-h-[3.25rem] w-full rounded-xl bg-accent-soft text-base font-semibold text-ink-primary ring-1 ring-inset ring-accent disabled:opacity-40"
        >
          {busy ? "Checking…" : choosing && stage === "enter" ? "Next" : "Open accounts"}
        </button>

        <a
          href="/owner"
          className="mt-5 inline-block text-sm text-ink-muted underline hover:text-ink-secondary"
        >
          Back to the daily screen
        </a>
      </motion.div>
    </main>
  );
}
