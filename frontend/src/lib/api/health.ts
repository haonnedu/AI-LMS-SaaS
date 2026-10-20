import type { components } from "@/lib/api/generated";

// The API defaults its literal fields; successful responses must still include them.
export type HealthResponse = Required<components["schemas"]["LiveResponse"]>;

export function isHealthResponse(value: unknown): value is HealthResponse {
  return typeof value === "object" && value !== null
    && "status" in value && value.status === "ok"
    && "service" in value && value.service === "eduvia-api"
    && "version" in value && typeof value.version === "string"
    && value.version.length > 0 && value.version.length < 64;
}
