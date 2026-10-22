"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
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
};
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [state, setState] = useState<AuthState>("idle");
  const [scenario, setScenario] = useState<MockScenario>("success");
  const adapter = useRef<AuthAdapter | null>(null);
  const busy = useRef(false);
  const expiry = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (expiry.current) clearTimeout(expiry.current);
    };
  }, []);

  async function signIn() {
    if (busy.current) return;
    busy.current = true;
    setState("loading");
    const selected = process.env.NODE_ENV === "development" ? scenario : "success";
    const current = createMockAuthAdapter(selected);
    adapter.current = current;
    try {
      const result = await current.signIn();
      if (!mounted.current) return;
      if (result.status !== "success") { setState(result.status); return; }
      setSession(await current.getSession());
      setState("success");
      router.push("/");
      if (expiry.current) clearTimeout(expiry.current);
      if (selected === "expired") {
        expiry.current = setTimeout(() => {
          void current.signOut();
          setSession(null);
          setState("expired");
          router.replace("/login");
        }, 5000);
      }
    } catch {
      if (mounted.current) setState("error");
    } finally { busy.current = false; }
  }

  async function signOut() {
    if (busy.current) return;
    busy.current = true;
    try {
      if (expiry.current) clearTimeout(expiry.current);
      await adapter.current?.signOut();
      setSession(null);
      setState("idle");
      router.push("/login");
    } finally { busy.current = false; }
  }

  return <AuthContext.Provider value={{ session, state, scenario, setScenario, signIn, signOut }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth requires AuthProvider");
  return auth;
}
