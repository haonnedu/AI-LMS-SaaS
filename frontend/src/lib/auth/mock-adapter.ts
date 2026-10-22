import type { AuthAdapter, AuthSession, MockScenario } from "./types";

// One instance per mounted provider. No cookies, storage, tokens or network calls.
export function createMockAuthAdapter(scenario: MockScenario): AuthAdapter {
  let session: AuthSession | null = null;
  return {
    async getSession() { return session; },
    async signIn() {
      await new Promise((resolve) => setTimeout(resolve, 700));
      if (scenario === "error" || scenario === "cancelled") return { status: scenario };
      session = { user: { id: "demo-teacher", name: "Minh Anh (mẫu)" } };
      return { status: "success", session };
    },
    async signOut() { session = null; },
  };
}
