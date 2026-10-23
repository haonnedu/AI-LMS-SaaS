"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { components } from "@/lib/api/generated";
import { read, RequestError, type Session } from "@/lib/client/api";

type Workspace = components["schemas"]["WorkspaceDTO"];
type State = { phase: "loading" | "ready" | "error"; csrf: string; workspace: Workspace | null; message: string };
/** Loads session + first workspace and provides a shared 401/403/onboarding error handler. */
export function useTeaching() {
  const router = useRouter();
  const [state, setState] = useState<State>({ phase: "loading", csrf: "", workspace: null, message: "" });
  const alive = useRef(true);
  const handle = useCallback((error: unknown) => {
    if (error instanceof RequestError) {
      if (error.status === 401) { router.replace("/login?error=expired"); return error.message; }
      if (error.code === "email_unverified") { router.replace("/verify-email"); return error.message; }
      if (error.code === "onboarding_required") { router.replace("/onboarding"); return error.message; }
      return error.message;
    }
    return "Không thể kết nối. Vui lòng thử lại.";
  }, [router]);
  const load = useCallback(async () => {
    try {
      const session: Session = await read("/api/session");
      if (!session.authenticated || !session.csrfToken) { router.replace("/login"); return; }
      const list = await read("/api/backend/workspaces?limit=1");
      if (!alive.current) return;
      const workspace: Workspace | null = list.items[0] || null;
      setState({ phase: workspace ? "ready" : "error", csrf: session.csrfToken, workspace, message: workspace ? "" : "Không có workspace khả dụng. Hãy mở workspace cá nhân trước." });
    } catch (error) { if (alive.current) setState(current => ({ ...current, phase: "error", message: handle(error) })); }
  }, [handle, router]);
  useEffect(() => {
    alive.current = true;
    void load();
    return () => { alive.current = false; };
  }, [load]);
  return { ...state, handle, reload: load };
}
