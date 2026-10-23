"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { jsonInit, read } from "@/lib/client/api";
import { REQUEST_POLL_MAX_ATTEMPTS, requestPollDelay, shouldPollRequest } from "@/lib/client/privacy";
import type { PrivacyKind, PrivacyRequest, PrivacyRequestCreated } from "@/lib/client/privacy-types";

type Options = { createUrl: string; pollUrl: (id: string) => string; csrf: string; handle: (error: unknown) => string; onSettled?: (request: PrivacyRequest) => void };
/** Creates an export/erasure request and polls it until it settles. Request bodies and download links are never logged. */
export function usePrivacyRequest({ createUrl, pollUrl, csrf, handle, onSettled }: Options) {
  const [request, setRequest] = useState<PrivacyRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [gaveUp, setGaveUp] = useState(false);
  const attempt = useRef(0);
  const errors = useRef(0);
  const settled = useRef(onSettled);
  useEffect(() => { settled.current = onSettled; });
  const poll = useRef(pollUrl);
  useEffect(() => { poll.current = pollUrl; });

  const id = request?.id, status = request?.status, link = request?.downloadUrl;
  useEffect(() => {
    if (!id || !status) return;
    const view = { status, downloadUrl: link };
    if (!shouldPollRequest(view, attempt.current)) {
      if (attempt.current >= REQUEST_POLL_MAX_ATTEMPTS && !link) setGaveUp(true);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      attempt.current += 1;
      try {
        const next: PrivacyRequest = await read(poll.current(id));
        errors.current = 0;
        if (cancelled) return;
        setRequest(current => (current && current.id === next.id ? next : current));
        if (!shouldPollRequest(next, attempt.current)) settled.current?.(next);
      } catch (e) {
        errors.current += 1;
        if (!cancelled && errors.current >= 4) { setError(handle(e)); setGaveUp(true); }
        else if (!cancelled) setRequest(current => (current ? { ...current } : current));
      }
    }, requestPollDelay(attempt.current, errors.current));
    return () => { cancelled = true; clearTimeout(timer); };
  }, [id, status, link, handle, request]);

  const start = useCallback(async (kind: PrivacyKind) => {
    setBusy(true); setError(""); setGaveUp(false); attempt.current = 0; errors.current = 0;
    try {
      const created: PrivacyRequestCreated = await read(createUrl, jsonInit(csrf, { kind }));
      setRequest({ id: created.request.id, kind: created.request.kind, status: created.request.status });
    } catch (e) { setError(handle(e)); }
    finally { setBusy(false); }
  }, [createUrl, csrf, handle]);
  return { request, busy, error, gaveUp, start };
}
