"use client";

/**
 * Speak the transaction instead of typing it.
 *
 * Speech recognition runs in the browser (the Web Speech API); the *meaning* is
 * worked out by the backend parser. Where the API is missing - Firefox, older
 * Android WebViews - the same box accepts typed text and behaves identically,
 * so the feature degrades to something useful rather than disappearing.
 *
 * Nothing is ever posted from here. The parse comes back as a sentence the
 * owner reads and confirms.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "@/lib/api";
import type { VoiceParseResult } from "@/lib/types";
import { PlainButton } from "./BigButton";

// The Web Speech API is not in the DOM typings, so describe the parts we use.
interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}

function getRecognition(): SpeechRecognitionLike | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

export function VoiceInput({
  onParsed,
  onCancel,
}: {
  onParsed: (result: VoiceParseResult) => void;
  onCancel: () => void;
}) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    const recognition = getRecognition();
    setSupported(recognition !== null);
    return () => recognitionRef.current?.stop();
  }, []);

  const interpret = useCallback(
    async (text: string) => {
      if (!text.trim()) return;
      setBusy(true);
      setError("");
      try {
        onParsed(await api.parseSpeech(text));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not understand that.");
      } finally {
        setBusy(false);
      }
    },
    [onParsed],
  );

  function listen() {
    const recognition = getRecognition();
    if (!recognition) return;
    recognitionRef.current = recognition;

    // Malay first: it is what the phrase is usually spoken in, and the parser
    // reads both languages regardless of which model transcribed it.
    recognition.lang = "ms-MY";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
      const heard = event.results[0]?.[0]?.transcript ?? "";
      setTranscript(heard);
      void interpret(heard);
    };
    recognition.onerror = (event) => {
      setError(
        event.error === "not-allowed"
          ? "The microphone is blocked. Allow it in your browser settings, or type instead."
          : "I did not hear anything. Try again, or type it.",
      );
      setListening(false);
    };
    recognition.onend = () => setListening(false);

    setError("");
    setTranscript("");
    setListening(true);
    recognition.start();
  }

  function stop() {
    recognitionRef.current?.stop();
    setListening(false);
  }

  return (
    <div className="text-center">
      <h2 className="text-3xl font-bold text-ink-primary sm:text-4xl">
        Say what happened
      </h2>
      <p className="mx-auto mt-3 max-w-md text-xl text-ink-secondary">
        For example: <span className="font-semibold">&ldquo;Bought RM50 of chicken&rdquo;</span>
        {" "}or{" "}
        <span className="font-semibold">&ldquo;Jual RM120 tunai&rdquo;</span>
      </p>

      {supported ? (
        <div className="mt-10 flex justify-center">
          <button
            type="button"
            onClick={listening ? stop : listen}
            disabled={busy}
            aria-label={listening ? "Stop listening" : "Start listening"}
            className={`relative flex h-40 w-40 items-center justify-center rounded-full text-6xl shadow-lift transition-colors ${
              listening ? "bg-[#a8341f] text-white" : "bg-[#1c5cab] text-white"
            }`}
          >
            {listening ? (
              <span
                className="absolute inset-0 animate-pulseRing rounded-full bg-[#a8341f]/50"
                aria-hidden="true"
              />
            ) : null}
            <span aria-hidden="true">{listening ? "⏹" : "🎤"}</span>
          </button>
        </div>
      ) : null}

      <p className="mt-6 text-xl font-semibold text-ink-primary" aria-live="polite">
        {busy
          ? "Working it out…"
          : listening
            ? "Listening… speak now"
            : transcript
              ? `You said: “${transcript}”`
              : supported
                ? "Tap the microphone"
                : "Type what happened"}
      </p>

      <AnimatePresence>
        {error ? (
          <motion.p
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="mx-auto mt-4 max-w-md rounded-2xl bg-[#a8341f]/10 px-5 py-4 text-lg font-semibold text-[#8f2b19]"
            role="alert"
          >
            {error}
          </motion.p>
        ) : null}
      </AnimatePresence>

      <form
        className="mt-8"
        onSubmit={(event) => {
          event.preventDefault();
          void interpret(transcript);
        }}
      >
        <label htmlFor="voice-text" className="sr-only">
          Type what happened
        </label>
        <input
          id="voice-text"
          type="text"
          value={transcript}
          onChange={(event) => setTranscript(event.target.value)}
          placeholder="Bought RM50 of chicken"
          className="w-full rounded-2xl border-4 border-surface-border bg-surface-raised px-6 py-5 text-2xl text-ink-primary placeholder:text-ink-muted"
        />
        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <PlainButton onClick={onCancel} className="sm:flex-1">
            Go back
          </PlainButton>
          <PlainButton
            type="submit"
            variant="solid"
            disabled={busy || !transcript.trim()}
            className="sm:flex-1"
          >
            {busy ? "Working…" : "Check this"}
          </PlainButton>
        </div>
      </form>
    </div>
  );
}
