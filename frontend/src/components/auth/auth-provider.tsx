"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createMockAuthAdapter } from "@/lib/auth/mock-adapter";
import type { AuthAdapter, AuthSession, MockScenario } from "@/lib/auth/types";

type AuthState = "idle" | "loading" | "success" | "error" | "cancelled" | "expired";
type AuthContextValue = {
  session: AuthSession | null;
  state: AuthState;
  scenario: MockScenario;
  setScenario: (scenario: MockScenario) => void;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  cancelSignIn: () => void;
};
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [state, setState] = useState<AuthState>("idle");
  const [scenario, setScenario] = useState<MockScenario>("success");
  const adapter = useRef<AuthAdapter | null>(null);
  const busy = useRef(false);
  const operation = useRef(0);
  const pendingSignIn = useRef<number | null>(null);
  const expiry = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      operation.current += 1;
      pendingSignIn.current = null;
      busy.current = false;
      if (expiry.current) clearTimeout(expiry.current);
    };
  }, []);

  const cancelSignIn = useCallback(() => {
    if (pendingSignIn.current === null) return;
    operation.current += 1;
    pendingSignIn.current = null;
    busy.current = false;
    setState("idle");
  }, []);

  async function signIn() {
    if (busy.current) return;
    const id = ++operation.current;
    pendingSignIn.current = id;
    busy.current = true;
    setState("loading");
    const selected = process.env.NODE_ENV === "development" ? scenario : "success";
    const current = createMockAuthAdapter(selected);
    try {
      const result = await current.signIn();
      if (!mounted.current || operation.current !== id) return;
      if (result.status !== "success") { setState(result.status); return; }
      const nextSession = await current.getSession();
      if (!mounted.current || operation.current !== id) return;
      adapter.current = current;
      setSession(nextSession);
      setState("success");
      // Login unmounts after navigation. Its cleanup must not cancel this session.
      pendingSignIn.current = null;
      router.push("/");
      if (expiry.current) clearTimeout(expiry.current);
      if (selected === "expired") {
        expiry.current = setTimeout(() => {
          if (!mounted.current || operation.current !== id) return;
          operation.current += 1;
          expiry.current = null;
          adapter.current = null;
          void current.signOut();
          setSession(null);
          setState("expired");
          router.replace("/login");
        }, 5000);
      }
    } catch {
      if (mounted.current && operation.current === id) setState("error");
    } finally {
      // A stale request cannot unlock or reset a newer login attempt.
      if (operation.current === id) {
        pendingSignIn.current = null;
        busy.current = false;
      }
    }
  }

  async function signOut() {
    if (busy.current) return;
    const id = ++operation.current;
    busy.current = true;
    try {
      if (expiry.current) clearTimeout(expiry.current);
      expiry.current = null;
      await adapter.current?.signOut();
      if (!mounted.current || operation.current !== id) return;
      adapter.current = null;
      setSession(null);
      setState("idle");
      router.push("/login");
    } finally { if (operation.current === id) busy.current = false; }
  }

  return <AuthContext.Provider value={{ session, state, scenario, setScenario, signIn, signOut, cancelSignIn }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth requires AuthProvider");
  return auth;
}
