import { NextResponse } from "next/server";
import { isHealthResponse } from "@/lib/api/health";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Only a fixed server-configured origin is accepted. Request input never selects an upstream.
export async function GET() {
  try {
    const base = new URL(process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000");
    if (!["http:", "https:"].includes(base.protocol) || base.username || base.password) {
      throw new Error("Invalid backend configuration");
    }
    const response = await fetch(new URL("/health/live", base), {
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(4000),
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error("Upstream unavailable");
    const payload: unknown = await response.json();
    if (!isHealthResponse(payload)) throw new Error("Unexpected upstream response");
    return NextResponse.json(
      { status: payload.status, service: payload.service, version: payload.version },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { error: { code: "backend_unavailable", message: "The API is not available right now." } },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
