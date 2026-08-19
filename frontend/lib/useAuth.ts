"use client";

/** Shared auth state for both interfaces. */
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { AuthStatus } from "./types";

export function useAuth() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.authStatus());
    } catch {
      // A backend that cannot be reached is handled by the page itself; the
      // auth layer just reports "unknown" rather than blocking the whole UI.
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { status, loading, refresh, setStatus };
}

/**
 * Whether the financial side is reachable right now.
 *
 * A finance role is not enough on its own: the device has to be unlocked too,
 * including the first time, when the PIN is chosen rather than entered. The
 * backend enforces exactly the same rule - this only decides what to render.
 */
export function canOpenFinance(status: AuthStatus | null): boolean {
  if (!status) return false;
  if (!status.auth_enabled) return true;
  if (!status.signed_in || !status.user?.can_see_finances) return false;
  return status.unlocked;
}
