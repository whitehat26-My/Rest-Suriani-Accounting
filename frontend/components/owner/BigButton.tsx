"use client";

/**
 * The primary control of Grandma Mode.
 *
 * Sized well beyond the 44px accessibility minimum - these are 128px tall,
 * because the target user has reduced fine motor control and is often holding
 * the phone one-handed behind a counter. Every button carries an icon, a word
 * and a colour, so no single channel has to do the work alone.
 */
import { motion } from "framer-motion";
import type { ReactNode } from "react";

type Tone = "in" | "out" | "stock" | "neutral";

const TONES: Record<Tone, { bg: string; ring: string; text: string }> = {
  // These are UI action colours, not chart series colours, so they are chosen
  // for contrast against the white card rather than from the series palette.
  in: { bg: "bg-[#0b7a34]", ring: "ring-[#0b7a34]/30", text: "text-white" },
  out: { bg: "bg-[#a8341f]", ring: "ring-[#a8341f]/30", text: "text-white" },
  stock: { bg: "bg-[#1c5cab]", ring: "ring-[#1c5cab]/30", text: "text-white" },
  neutral: {
    bg: "bg-surface-raised border-4 border-surface-border",
    ring: "ring-surface-border",
    text: "text-ink-primary",
  },
};

export function BigButton({
  tone = "neutral",
  emoji,
  label,
  hint,
  onClick,
  disabled = false,
  className = "",
}: {
  tone?: Tone;
  emoji: string;
  label: string;
  hint?: string;
  onClick: () => void;
  disabled?: boolean;
  className?: string;
}) {
  const styles = TONES[tone];
  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={disabled}
      whileTap={{ scale: 0.97 }}
      whileHover={{ y: -3 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
      className={`flex min-h-[8rem] w-full items-center gap-5 rounded-xl3 px-7 py-6 text-left shadow-lift ring-8 transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles.bg} ${styles.ring} ${styles.text} ${className}`}
    >
      <span className="text-5xl leading-none" aria-hidden="true">
        {emoji}
      </span>
      <span className="flex-1">
        <span className="block text-3xl font-bold leading-tight sm:text-4xl">{label}</span>
        {hint ? (
          <span className="mt-1 block text-lg font-medium opacity-90">{hint}</span>
        ) : null}
      </span>
    </motion.button>
  );
}

/** A secondary control: still large, but visually quieter than the big three. */
export function PlainButton({
  children,
  onClick,
  disabled = false,
  variant = "ghost",
  className = "",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "ghost" | "solid" | "danger";
  className?: string;
  type?: "button" | "submit";
}) {
  const variants = {
    ghost:
      "bg-surface-raised text-ink-primary border-4 border-surface-border hover:bg-surface-sunken",
    solid: "bg-[#0b7a34] text-white hover:bg-[#0a6a2e]",
    danger: "bg-[#a8341f] text-white hover:bg-[#8f2b19]",
  } as const;

  return (
    <motion.button
      type={type}
      onClick={onClick}
      disabled={disabled}
      whileTap={{ scale: 0.97 }}
      className={`min-h-[4.5rem] rounded-2xl px-8 text-2xl font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${variants[variant]} ${className}`}
    >
      {children}
    </motion.button>
  );
}
