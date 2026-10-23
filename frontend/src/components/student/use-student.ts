"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { clockOffset, type KeyStorage } from "@/lib/client/assessment";
import { read, RequestError, type Session } from "@/lib/client/api";

/** sessionStorage, or null when blocked (private mode); callers fall back to memory. */
export function sessionKeys(): KeyStorage | null {
  try { return typeof window === "undefined" ? null : window.sessionStorage; } catch { return null; }
}
/** Session + CSRF token and a shared error handler for student pages. */
export function useStudent() {
  const router = useRouter();
  const [csrf, setCsrf] = useState("");
  const [ready, setReady] = useState(false);
  const [message, setMessage] = useState("");
  const alive = useRef(true);
  const handle = useCallback((error: unknown) => {
    if (error instanceof RequestError) {
      if (error.status === 401) { router.replace("/login?error=expired"); return error.message; }
      if (error.code === "email_unverified") { router.replace("/verify-email"); return error.message; }
      return error.message;
    }
    return "Không thể kết nối. Vui lòng thử lại.";
  }, [router]);
  const load = useCallback(async () => {
    try {
      const session: Session = await read("/api/session");
      if (!session.authenticated || !session.csrfToken) { router.replace("/login"); return; }
      if (alive.current) { setCsrf(session.csrfToken); setReady(true); setMessage(""); }
    } catch (error) { if (alive.current) setMessage(handle(error)); }
  }, [handle, router]);
  // Session bootstrap: network synchronization.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, [load]);
  return { csrf, ready, message, handle, reload: load };
}
/** Server-clock offset (serverNow minus device time) plus a ticking device time. The device clock alone is never trusted. */
export function useServerClock(tickMs = 1000) {
  const [offset, setOffset] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), tickMs);
    return () => clearInterval(id);
  }, [tickMs]);
  const sync = useCallback((serverNow: string | null | undefined) => {
    const next = clockOffset(serverNow);
    if (next !== null) { setOffset(next); setNow(Date.now()); }
  }, []);
  return { offset, now, sync };
}
