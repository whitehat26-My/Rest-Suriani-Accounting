"use client";

/**
 * The doorway.
 *
 * Two people share this app and want opposite things, so the choice is made
 * once, in large type, before either interface loads. The owner's side is
 * deliberately the left and larger one - it is the door used every day.
 */
import Link from "next/link";
import { motion } from "framer-motion";

export default function RoleChooser() {
  return (
    <main className="theme-accountant relative min-h-screen overflow-hidden bg-surface-base">
      <div className="aurora pointer-events-none absolute inset-0" aria-hidden="true" />
      <div
        className="grid-backdrop pointer-events-none absolute inset-0 opacity-40"
        aria-hidden="true"
      />

      <div className="relative mx-auto flex min-h-screen max-w-6xl flex-col justify-center px-6 py-16">
        <motion.header
          initial={{ opacity: 0, y: -16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-14 text-center"
        >
          <p className="mb-3 text-sm font-semibold uppercase tracking-[0.35em] text-accent">
            Restoran Suriani
          </p>
          <h1 className="text-4xl font-bold tracking-tight text-ink-primary sm:text-6xl">
            Who is using the system?
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg text-ink-secondary">
            One set of books, two ways in. Every tap on the left writes a complete
            double entry on the right.
          </p>
        </motion.header>

        <div className="grid gap-6 md:grid-cols-2">
          <RoleCard
            href="/owner"
            emoji="🍜"
            title="Daily Use"
            subtitle="For the owner"
            description="Money in, money out, count stock. Big buttons, no accounting words."
            accent="from-emerald-400/25 to-emerald-500/5"
            delay={0.1}
            primary
          />
          <RoleCard
            href="/accountant"
            emoji="📊"
            title="Financial Management"
            subtitle="For the accountant"
            description="Ledger, statements, ratios and the automated posting trail."
            accent="from-sky-400/25 to-indigo-500/5"
            delay={0.2}
          />
        </div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="mt-12 text-center text-sm text-ink-muted"
        >
          You can switch at any time from the corner of either screen.
        </motion.p>
      </div>
    </main>
  );
}

function RoleCard({
  href,
  emoji,
  title,
  subtitle,
  description,
  accent,
  delay,
  primary = false,
}: {
  href: string;
  emoji: string;
  title: string;
  subtitle: string;
  description: string;
  accent: string;
  delay: number;
  primary?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay }}
      whileHover={{ y: -6 }}
    >
      <Link
        href={href}
        className="glass group block h-full rounded-xl3 border border-surface-border p-8 transition-shadow hover:shadow-glow sm:p-10"
      >
        <div
          className={`mb-6 inline-flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br ${accent} text-4xl`}
          aria-hidden="true"
        >
          {emoji}
        </div>
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-accent">
          {subtitle}
        </p>
        <h2 className="mt-2 text-3xl font-bold text-ink-primary sm:text-4xl">{title}</h2>
        <p className="mt-4 text-base leading-relaxed text-ink-secondary">{description}</p>
        <p className="mt-8 inline-flex items-center gap-2 text-lg font-semibold text-ink-primary">
          {primary ? "Open daily screen" : "Open dashboard"}
          <span className="transition-transform group-hover:translate-x-1" aria-hidden="true">
            →
          </span>
        </p>
      </Link>
    </motion.div>
  );
}
