"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/auth-provider";
import { createMockWorkspaceAdapter } from "@/lib/workspace/mock-adapter";
import type { WorkspaceAdapter, WorkspaceScenario, WorkspaceSummary } from "@/lib/workspace/types";

type WorkspaceContextValue = {
  workspace: WorkspaceSummary | null;
  state: "idle" | "loading" | "ready" | "error";
  scenario: WorkspaceScenario;
  canChooseScenario: boolean;
  chooseScenario: (scenario: WorkspaceScenario) => void;
  openWorkspace: () => Promise<void>;
  cancelPending: () => void;
};
const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const { sessionVersion } = useAuth();
  return <SessionWorkspaceProvider key={sessionVersion}>{children}</SessionWorkspaceProvider>;
}

function SessionWorkspaceProvider({ children }: { children: React.ReactNode }) {
  const { session, sessionVersion, isCurrentSession } = useAuth();
  const router = useRouter();
  const [workspace, setWorkspace] = useState<WorkspaceSummary | null>(null);
  const [state, setState] = useState<WorkspaceContextValue["state"]>("idle");
  const [scenario, setScenario] = useState<WorkspaceScenario>("success");
  const [started, setStarted] = useState(false);
  const adapter = useRef<WorkspaceAdapter | null>(null);
  const operation = useRef(0);
  const pending = useRef(false);
  const hasStarted = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      operation.current += 1;
      pending.current = false;
    };
  }, []);

  const cancelPending = useCallback(() => {
    if (!pending.current) return;
    operation.current += 1;
    pending.current = false;
    setState("idle");
  }, []);

  function chooseScenario(next: WorkspaceScenario) {
    if (process.env.NODE_ENV !== "development" || hasStarted.current) return;
    adapter.current = null;
    setScenario(next);
  }

  async function openWorkspace() {
    if (!session || !isCurrentSession(sessionVersion) || pending.current) return;
    if (workspace) { router.push("/"); return; }
    const id = ++operation.current;
    pending.current = true;
    hasStarted.current = true;
    setStarted(true);
    setState("loading");
    const current = adapter.current ?? createMockWorkspaceAdapter(
      process.env.NODE_ENV === "development" ? scenario : "success",
    );
    adapter.current = current;
    const isCurrent = () => mounted.current && operation.current === id &&
      isCurrentSession(sessionVersion);
    try {
      let result = await current.getPersonalWorkspace();
      if (!isCurrent()) return;
      if (!result) result = await current.ensurePersonalWorkspace();
      if (!isCurrent()) return;
      setWorkspace(result);
      setState("ready");
      pending.current = false;
      router.push("/");
    } catch {
      if (isCurrent()) setState("error");
    } finally {
      if (isCurrent()) pending.current = false;
    }
  }

  return <WorkspaceContext.Provider value={{ workspace, state, scenario,
    canChooseScenario: !started && !workspace, chooseScenario, openWorkspace, cancelPending }}>
    {children}
  </WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error("useWorkspace requires WorkspaceProvider");
  return context;
}
