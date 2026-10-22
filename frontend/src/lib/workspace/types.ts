export type WorkspaceSummary = { id: string; name: string; kind: "personal" };
export type WorkspaceScenario = "success" | "existing" | "error_once";

// Internal frontend boundary, not a backend API contract.
export interface WorkspaceAdapter {
  getPersonalWorkspace(): Promise<WorkspaceSummary | null>;
  ensurePersonalWorkspace(): Promise<WorkspaceSummary>;
}
