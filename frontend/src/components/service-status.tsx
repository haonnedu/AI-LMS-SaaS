"use client";

import { useEffect, useState } from "react";
import { CircleCheck, LoaderCircle, RefreshCw, Unplug } from "lucide-react";
import { isHealthResponse } from "@/lib/api/health";

type Connection = { state: "checking" } | { state: "online"; version: string } | { state: "offline" };

export function ServiceStatus() {
  const [connection, setConnection] = useState<Connection>({ state: "checking" });
  const [requestNumber, setRequestNumber] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = setTimeout(() => controller.abort(), 6000);
    async function check() {
      try {
        const response = await fetch("/api/backend/health", { signal: controller.signal, cache: "no-store" });
        const data: unknown = await response.json();
        if (!response.ok || !isHealthResponse(data)) throw new Error("Unavailable");
        if (active) setConnection({ state: "online", version: data.version });
      } catch {
        if (active) setConnection({ state: "offline" });
      } finally {
        clearTimeout(timeout);
      }
    }
    void check();
    return () => { active = false; controller.abort(); clearTimeout(timeout); };
  }, [requestNumber]);

  const isChecking = connection.state === "checking";
  const Icon = isChecking ? LoaderCircle : connection.state === "online" ? CircleCheck : Unplug;
  const title = isChecking ? "Checking API connection" : connection.state === "online" ? "API connected" : "API is offline";
  const description = connection.state === "online"
    ? `Eduvia API ${connection.version} is responding. Database readiness is checked separately.`
    : isChecking ? "Connecting to your local backend…" : "Start the backend service, then try the connection again.";

  return (
    <div className={`service-status ${connection.state}`}>
      <div className="service-icon"><Icon size={21} className={isChecking ? "spin" : ""} aria-hidden="true" /></div>
      <div className="service-copy" role="status" aria-live="polite" aria-atomic="true"><strong>{title}</strong><p>{description}</p></div>
      <button type="button" className="button button-secondary button-small" disabled={isChecking} onClick={() => { setConnection({ state: "checking" }); setRequestNumber((value) => value + 1); }}>
        <RefreshCw size={15} aria-hidden="true" /><span>{isChecking ? "Checking" : "Retry"}</span>
      </button>
    </div>
  );
}
