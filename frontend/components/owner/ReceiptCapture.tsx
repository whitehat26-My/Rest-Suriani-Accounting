"use client";

/**
 * Attach a photo of the receipt.
 *
 * `capture="environment"` opens the rear camera directly on a phone, which
 * removes a whole gallery-navigation step. On a desktop it falls back to the
 * ordinary file picker.
 */
import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { api } from "@/lib/api";

export function ReceiptCapture({
  attachmentId,
  onAttached,
}: {
  attachmentId: number | null;
  onAttached: (id: number | null, previewUrl: string | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<string | null>(null);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const uploaded = await api.uploadReceipt(file);
      const objectUrl = URL.createObjectURL(file);
      setPreview(objectUrl);
      onAttached(uploaded.id, objectUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the photo.");
    } finally {
      setBusy(false);
    }
  }

  function clear() {
    if (preview) URL.revokeObjectURL(preview);
    setPreview(null);
    onAttached(null, null);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="sr-only"
        onChange={(event) => void handleFile(event.target.files?.[0])}
      />

      {attachmentId && preview ? (
        <div className="flex items-center gap-4 rounded-2xl border-4 border-[#0b7a34] bg-[#0b7a34]/5 p-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={preview}
            alt="The receipt you photographed"
            className="h-24 w-24 rounded-xl object-cover"
          />
          <div className="flex-1">
            <p className="text-xl font-bold text-[#0b7a34]">Photo attached ✓</p>
            <button
              type="button"
              onClick={clear}
              className="mt-1 text-lg font-semibold text-ink-secondary underline"
            >
              Remove it
            </button>
          </div>
        </div>
      ) : (
        <motion.button
          type="button"
          whileTap={{ scale: 0.97 }}
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="flex min-h-[5rem] w-full items-center justify-center gap-4 rounded-2xl border-4 border-dashed border-surface-border bg-surface-raised px-6 text-2xl font-bold text-ink-primary disabled:opacity-50"
        >
          <span className="text-4xl" aria-hidden="true">
            📷
          </span>
          {busy ? "Saving photo…" : "Photo of receipt (optional)"}
        </motion.button>
      )}

      {error ? (
        <p className="mt-3 text-lg font-semibold text-[#8f2b19]" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
