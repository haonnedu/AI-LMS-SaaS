import type { WorkspaceAdapter, WorkspaceScenario, WorkspaceSummary } from "./types";

function sampleWorkspace(): WorkspaceSummary {
  return { id: "demo-personal-workspace", name: "Không gian cá nhân mẫu", kind: "personal" };
}

// Instances belong to one mock auth session; nothing is persisted or sent over HTTP.
export function createMockWorkspaceAdapter(scenario: WorkspaceScenario): WorkspaceAdapter {
  let workspace = scenario === "existing" ? sampleWorkspace() : null;
  let pending: Promise<WorkspaceSummary> | null = null;
  let failedOnce = false;
  return {
    async getPersonalWorkspace() { return workspace; },
    ensurePersonalWorkspace() {
      if (workspace) return Promise.resolve(workspace);
      if (pending) return pending;
      pending = new Promise<WorkspaceSummary>((resolve, reject) => {
        setTimeout(() => {
          if (scenario === "error_once" && !failedOnce) {
            failedOnce = true;
            reject(new Error("Mock workspace preparation failed"));
            return;
          }
          workspace = sampleWorkspace();
          resolve(workspace);
        }, 700);
      }).finally(() => { pending = null; });
      return pending;
    },
  };
}
