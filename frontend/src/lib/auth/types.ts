export type AuthSession = { user: { id: string; name: string } };
export type AuthResult =
  | { status: "success"; session: AuthSession }
  | { status: "error" | "cancelled" };
export type MockScenario = "success" | "error" | "cancelled" | "expired";

export interface AuthAdapter {
  getSession(): Promise<AuthSession | null>;
  signIn(): Promise<AuthResult>;
  signOut(): Promise<void>;
}
