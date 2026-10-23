"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { components } from "@/lib/api/generated";
import styles from "../workspace/workspace.module.css";

type Workspace = components["schemas"]["WorkspaceDTO"];
type User = components["schemas"]["UserDTO"];
class RequestError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}
type Session = { authenticated: boolean; emailVerified?: boolean; csrfToken?: string; user?: { name: string; email: string } };
export function AccountScreen({ mode }: { mode: "onboarding" | "dashboard" }) {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState("");
  const epoch = useRef(0);
  const inFlight = useRef(false);
  const read = useCallback(async (url: string, init?: RequestInit) => {
    const response = await fetch(url, { ...init, cache: "no-store", signal: AbortSignal.timeout(15000) });
    const payload = await response.json();
    if (!response.ok) {
      throw new RequestError(response.status, payload.error?.code || "request_failed", payload.error?.message || "Chưa thể hoàn thành. Vui lòng thử lại.");
    }
    return payload;
  }, []);
  const handleError = useCallback((error: unknown) => {
    setMessage(error instanceof Error ? error.message : "Không thể kết nối.");
    if (!(error instanceof RequestError)) return;
    if (error.status === 401) {
      setSession(null); setUser(null); setWorkspace(null); setWorkspaces([]); setNextCursor(null);
      router.replace("/login?error=expired");
    } else if (error.code === "email_unverified") router.replace("/verify-email");
    else if (error.code === "onboarding_required") router.replace("/onboarding");
  }, [router]);
  const load = useCallback(async () => {
    const version = ++epoch.current;
    try {
      const current: Session = await read("/api/session");
      if (version !== epoch.current) return;
      if (!current.authenticated) { setUser(null); setWorkspace(null); setWorkspaces([]); router.replace("/login"); return; }
      setSession(current);
      if (mode === "dashboard") {
        const [me, list] = await Promise.all([read("/api/backend/me"), read("/api/backend/workspaces")]);
        if (version !== epoch.current) return;
        setUser(me); setWorkspaces(list.items); setNextCursor(list.nextCursor); setWorkspace(list.items[0] || null);
      }
    } catch (error) { if (version === epoch.current) handleError(error); }
    finally { if (version === epoch.current) setBusy(false); }
  }, [read, mode, router, handleError]);
  // Starts external session/API synchronization; state updates follow network responses.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); return () => {
    // This numeric generation invalidates network results; it is not a DOM ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    epoch.current++;
  }; }, [load]);
  useEffect(() => {
    const recheck = () => { if (document.visibilityState === "visible" && !inFlight.current) void load(); };
    document.addEventListener("visibilitychange", recheck);
    return () => document.removeEventListener("visibilitychange", recheck);
  }, [load]);
  useEffect(() => {
    const clear = () => { epoch.current++; setSession(null); setUser(null); setWorkspace(null); setWorkspaces([]); setNextCursor(null); };
    const channel = new BroadcastChannel("eduvia-auth");
    channel.onmessage = event => { if (event.data === "logout") { clear(); router.replace("/login"); } };
    const restore = (event: PageTransitionEvent) => { if (event.persisted) { clear(); void load(); } };
    window.addEventListener("pageshow", restore);
    return () => { channel.close(); window.removeEventListener("pageshow", restore); };
  }, [load, router]);
  async function action(kind: "bootstrap" | "logout") {
    if (inFlight.current || !session?.csrfToken) return;
    inFlight.current = true;
    const version = ++epoch.current;
    setBusy(true); setMessage("");
    if (kind === "logout") { setWorkspace(null); setWorkspaces([]); setUser(null); }
    try {
      const url = kind === "bootstrap" ? "/api/backend/auth/bootstrap" : "/api/logout";
      const payload = await read(url, { method: "POST", headers: { "X-CSRF-Token": session.csrfToken } });
      if (version !== epoch.current) return;
      if (kind === "bootstrap") router.replace("/dashboard");
      if (kind === "logout") {
        setSession(null);
        const channel = new BroadcastChannel("eduvia-auth"); channel.postMessage("logout"); channel.close();
        window.location.assign(payload.redirect);
      }
    } catch (error) { if (version === epoch.current) handleError(error); }
    finally { inFlight.current = false; if (version === epoch.current) setBusy(false); }
  }
  async function switchWorkspace(id: string) {
    const version = ++epoch.current;
    setWorkspace(null); setBusy(true); setMessage("");
    try { const result = await read("/api/backend/workspaces/" + encodeURIComponent(id)); if (version === epoch.current) setWorkspace(result); }
    catch (error) { if (version === epoch.current) handleError(error); }
    finally { if (version === epoch.current) setBusy(false); }
  }
  async function more() {
    if (!nextCursor) return;
    const version = epoch.current;
    setBusy(true);
    try { const result = await read("/api/backend/workspaces?cursor=" + encodeURIComponent(nextCursor)); if (version === epoch.current) { setWorkspaces(current => [...current, ...result.items]); setNextCursor(result.nextCursor); } }
    catch (error) { if (version === epoch.current) handleError(error); }
    finally { if (version === epoch.current) setBusy(false); }
  }
  return <div className={styles.page}><section className={styles.card} aria-busy={busy}>
    <p>{user?.name || session?.user?.name || "Eduvia"}</p>
    {mode === "onboarding" && <><p>Eduvia sẽ tạo hoặc mở lại workspace cá nhân của bạn.</p><button className="button button-primary" disabled={busy || !session} onClick={() => void action("bootstrap")}>{busy ? "Đang chuẩn bị…" : "Mở workspace cá nhân"}</button></>}
    {mode === "dashboard" && <><label htmlFor="real-workspace">Workspace</label><select id="real-workspace" value={workspace?.id || ""} disabled={busy} onChange={event => void switchWorkspace(event.target.value)}><option value="" disabled>Chọn workspace</option>{workspaces.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>{nextCursor && <button disabled={busy} onClick={() => void more()}>Tải thêm workspace</button>}{workspace ? <div className={styles.workspace}><div><strong>{workspace.name}</strong><p>Vai trò: {workspace.role}</p><p>Workspace của bạn đã sẵn sàng. Các tính năng học liệu và lớp học sẽ được bổ sung sau.</p></div></div> : !busy && <p>Không có workspace khả dụng. Quyền truy cập có thể đã thay đổi.</p>}</>}
    {message && <p role="status" aria-live="polite">{message}</p>}
    {message && <button disabled={busy} onClick={() => void load()}>Tải lại</button>}
    <button className="button button-secondary" disabled={busy || !session} onClick={() => void action("logout")}>Đăng xuất</button>
    <Link href="/">Xem giao diện minh họa</Link>
  </section></div>;
}
