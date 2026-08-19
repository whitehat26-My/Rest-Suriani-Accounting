"use client";

/**
 * The whole data-entry journey for the owner, in at most four taps:
 *
 *   amount  ->  (what for?)  ->  how paid  ->  confirm
 *
 * The "what for?" step only appears for money going out, because money coming
 * in needs no category. Each step fills the screen; there is never a form with
 * several fields competing for attention.
 *
 * When the flow is entered by voice, the amount and category arrive pre-filled
 * and the journey starts at the confirmation step.
 */
import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api, type QuickEntryPayload } from "@/lib/api";
import { money } from "@/lib/format";
import type { PaymentMethod, SpendingCategory, Transaction, VoiceParseResult } from "@/lib/types";
import { PlainButton } from "./BigButton";
import { NumberPad } from "./NumberPad";
import { ReceiptCapture } from "./ReceiptCapture";

type Step = "amount" | "category" | "method" | "confirm";

const METHODS: { value: PaymentMethod; label: string; emoji: string; hint: string }[] = [
  { value: "CASH", label: "Cash", emoji: "💵", hint: "Notes and coins" },
  { value: "CARD", label: "Card", emoji: "💳", hint: "Card machine" },
  { value: "EWALLET", label: "E-wallet", emoji: "📱", hint: "QR scan" },
  { value: "BANK", label: "Bank", emoji: "🏦", hint: "Transfer" },
  { value: "CREDIT", label: "Pay later", emoji: "🕒", hint: "On account" },
];

export function MoneyFlow({
  kind,
  categories,
  prefill,
  onDone,
  onCancel,
}: {
  kind: "in" | "out";
  categories: SpendingCategory[];
  prefill?: VoiceParseResult | null;
  onDone: (txn: Transaction) => void;
  onCancel: () => void;
}) {
  const [step, setStep] = useState<Step>(prefill ? "confirm" : "amount");
  const [amount, setAmount] = useState(prefill?.amount ?? "");
  const [category, setCategory] = useState<string | null>(prefill?.category ?? null);
  const [method, setMethod] = useState<PaymentMethod>(prefill?.method ?? "CASH");
  const [attachmentId, setAttachmentId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // The keypad writes a bare string; keep a number handy for validation.
  const amountValue = Number.parseFloat(amount || "0");
  const valid = Number.isFinite(amountValue) && amountValue > 0;

  const categoryLabel =
    categories.find((c) => c.slug === category)?.label ?? prefill?.category_label ?? "";

  useEffect(() => {
    setError("");
  }, [step]);

  async function submit() {
    if (!valid) return;
    setSaving(true);
    setError("");
    try {
      const payload: QuickEntryPayload = {
        kind,
        amount: amountValue.toFixed(2),
        method,
        category: kind === "out" ? (category ?? "other") : null,
        note: prefill?.note ?? "",
        raw_input: prefill?.original_text ?? "",
        source: prefill ? "VOICE" : attachmentId ? "RECEIPT_PHOTO" : "GRANDMA_UI",
        attachment_ids: attachmentId ? [attachmentId] : [],
        inventory_item_id: prefill?.inventory_item_id ?? null,
        quantity: prefill?.quantity ?? null,
      };
      onDone(await api.quickEntry(payload));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save. Please try again.");
      setSaving(false);
    }
  }

  const heading = kind === "in" ? "Money In" : "Money Out";
  const tone = kind === "in" ? "#0b7a34" : "#a8341f";

  function goBack() {
    if (step === "amount") return onCancel();
    if (step === "category") return setStep("amount");
    if (step === "method") return setStep(kind === "out" ? "category" : "amount");
    // From confirm, a voice-prefilled entry returns to the caller rather than
    // dropping the owner into a keypad she never used.
    return prefill ? onCancel() : setStep("method");
  }

  function afterAmount() {
    setStep(kind === "out" ? "category" : "method");
  }

  return (
    <div className="mx-auto w-full max-w-xl">
      <header className="mb-8 flex items-center gap-4">
        <button
          type="button"
          onClick={goBack}
          aria-label="Go back"
          className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl border-4 border-surface-border bg-surface-raised text-3xl text-ink-primary"
        >
          ←
        </button>
        <div>
          <h1 className="text-4xl font-bold" style={{ color: tone }}>
            {heading}
          </h1>
          <p className="text-lg font-medium text-ink-secondary">
            {step === "amount" && "How much?"}
            {step === "category" && "What was it for?"}
            {step === "method" && (kind === "in" ? "How did they pay?" : "How did you pay?")}
            {step === "confirm" && "Is this right?"}
          </p>
        </div>
      </header>

      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -24 }}
          transition={{ duration: 0.2 }}
        >
          {step === "amount" ? (
            <>
              <NumberPad value={amount} onChange={setAmount} tone={kind} />
              <PlainButton
                variant="solid"
                onClick={afterAmount}
                disabled={!valid}
                className="mt-6 w-full"
              >
                Next →
              </PlainButton>
            </>
          ) : null}

          {step === "category" ? (
            <div className="grid grid-cols-2 gap-3">
              {categories.map((item) => {
                const selected = category === item.slug;
                return (
                  <motion.button
                    key={item.slug}
                    type="button"
                    whileTap={{ scale: 0.95 }}
                    onClick={() => {
                      setCategory(item.slug);
                      setStep("method");
                    }}
                    className={`flex min-h-[7rem] flex-col items-center justify-center gap-2 rounded-2xl border-4 px-3 py-4 text-center transition-colors ${
                      selected
                        ? "border-[#a8341f] bg-[#a8341f]/10"
                        : "border-surface-border bg-surface-raised hover:bg-surface-sunken"
                    }`}
                  >
                    <span className="text-4xl" aria-hidden="true">
                      {item.emoji}
                    </span>
                    <span className="text-lg font-bold leading-tight text-ink-primary">
                      {item.label}
                    </span>
                  </motion.button>
                );
              })}
            </div>
          ) : null}

          {step === "method" ? (
            <div className="space-y-3">
              {METHODS.map((item) => (
                <motion.button
                  key={item.value}
                  type="button"
                  whileTap={{ scale: 0.98 }}
                  onClick={() => {
                    setMethod(item.value);
                    setStep("confirm");
                  }}
                  className={`flex min-h-[5.5rem] w-full items-center gap-5 rounded-2xl border-4 px-6 text-left transition-colors ${
                    method === item.value
                      ? "border-[#1c5cab] bg-[#1c5cab]/10"
                      : "border-surface-border bg-surface-raised hover:bg-surface-sunken"
                  }`}
                >
                  <span className="text-4xl" aria-hidden="true">
                    {item.emoji}
                  </span>
                  <span>
                    <span className="block text-2xl font-bold text-ink-primary">
                      {item.label}
                    </span>
                    <span className="block text-lg text-ink-secondary">{item.hint}</span>
                  </span>
                </motion.button>
              ))}
            </div>
          ) : null}

          {step === "confirm" ? (
            <div className="space-y-6">
              <div
                className="rounded-xl3 border-4 p-7 text-center"
                style={{ borderColor: tone, backgroundColor: `${tone}0f` }}
              >
                <p className="text-xl font-semibold uppercase tracking-wide text-ink-muted">
                  {heading}
                </p>
                <p className="tabular mt-2 text-giant font-bold" style={{ color: tone }}>
                  {money(amountValue)}
                </p>
                <p className="mt-4 text-2xl font-semibold text-ink-primary">
                  {kind === "out" && categoryLabel ? `For ${categoryLabel.toLowerCase()}` : null}
                  {kind === "in" ? "From customers" : null}
                </p>
                <p className="mt-1 text-xl text-ink-secondary">
                  {METHODS.find((m) => m.value === method)?.label}
                  {method === "CREDIT" ? " — nothing paid yet" : ""}
                </p>
                {prefill?.inventory_item_name ? (
                  <p className="mt-3 text-lg text-ink-secondary">
                    Stock: {prefill.quantity ?? ""} {prefill.inventory_item_unit ?? ""}{" "}
                    {prefill.inventory_item_name}
                  </p>
                ) : null}
              </div>

              <ReceiptCapture
                attachmentId={attachmentId}
                onAttached={(id) => setAttachmentId(id)}
              />

              {error ? (
                <p
                  className="rounded-2xl bg-[#a8341f]/10 px-5 py-4 text-lg font-semibold text-[#8f2b19]"
                  role="alert"
                >
                  {error}
                </p>
              ) : null}

              <div className="flex flex-col gap-3 sm:flex-row">
                <PlainButton onClick={goBack} className="sm:flex-1">
                  No, change it
                </PlainButton>
                <PlainButton
                  variant="solid"
                  onClick={() => void submit()}
                  disabled={saving || !valid}
                  className="sm:flex-[2]"
                >
                  {saving ? "Saving…" : "Yes, save it ✓"}
                </PlainButton>
              </div>
            </div>
          ) : null}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
