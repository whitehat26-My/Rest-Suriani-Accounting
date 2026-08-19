"use client";

/**
 * Sign in.
 *
 * One button. The owner is 70 and signs in once per device, so this page is
 * deliberately almost empty - a name, a button, and a plain explanation of what
 * happens next. There is no password field because there is no password.
 */
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import { api } from "@/lib/api";

function SignInBody() {
  const params = useSearchParams();
  const error = params.get("error");
  const redirectTo = params.get("redirect_to") ?? "/";
  const [configured, setConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    void api
      .authStatus()
      .then((status) => {
        setConfigured(status.auth_enabled);
        // Nothing to sign in to when Google is not configured; the app is open.
        if (!status.auth_enabled || status.signed_in) {
          window.location.replace(redirectTo);
        }
      })
      .catch(() => setConfigured(null));
  }, [redirectTo]);

  const loginHref = `/api/auth/google/login?redirect_to=${encodeURIComponent(redirectTo)}`;

  return (
    <main className="theme-accountant relative flex min-h-screen items-center justify-center overflow-hidden bg-surface-base px-6">
      <div className="aurora pointer-events-none absolute inset-0" aria-hidden="true" />
      <div
        className="grid-backdrop pointer-events-none absolute inset-0 opacity-40"
        aria-hidden="true"
      />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="glass relative w-full max-w-md rounded-xl3 border border-surface-border p-10 text-center"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/brand/logo-mark.png"
          alt="Restoran Suriani"
          className="mx-auto h-14 w-auto"
        />
        <h1 className="mt-6 text-3xl font-bold text-ink-primary">Sign in</h1>
        <p className="mx-auto mt-4 max-w-sm text-base leading-relaxed text-ink-secondary">
          Use your Google account. You will stay signed in on this device, so you
          only have to do this once.
        </p>

        {error ? (
          <p
            className="mt-6 rounded-xl border border-status-critical bg-status-critical/10 px-5 py-4 text-sm font-medium text-ink-primary"
            role="alert"
          >
            {error}
          </p>
        ) : null}

        {configured === false ? (
          <p className="mt-6 rounded-xl border border-status-warning/50 bg-status-warning/10 px-5 py-4 text-sm text-ink-secondary">
            Google sign-in is not set up yet, so the system is running without
            accounts. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to
            backend/.env to switch it on.
          </p>
        ) : (
          <a
            href={loginHref}
            className="mt-8 flex min-h-[3.75rem] w-full items-center justify-center gap-3 rounded-2xl bg-white px-6 text-lg font-semibold text-[#1f1f1f] transition-transform hover:scale-[1.02]"
          >
            <GoogleMark />
            Continue with Google
          </a>
        )}

        <p className="mt-8 text-xs leading-relaxed text-ink-muted">
          The daily screen is available to everyone who signs in. The accounts,
          reports and payroll need the owner or the accountant, and a PIN on this
          device.
        </p>
      </motion.div>
    </main>
  );
}

function GoogleMark() {
  return (
    <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

export default function SignInPage() {
  return (
    <Suspense fallback={<main className="theme-accountant min-h-screen bg-surface-base" />}>
      <SignInBody />
    </Suspense>
  );
}
