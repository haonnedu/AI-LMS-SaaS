import assert from "node:assert/strict";
import { test } from "node:test";
import { createMockWorkspaceAdapter } from "../src/lib/workspace/mock-adapter.ts";

test("concurrent preparation shares a promise and preserves workspace identity", async () => {
  const adapter = createMockWorkspaceAdapter("success");
  assert.equal(await adapter.getPersonalWorkspace(), null);
  const first = adapter.ensurePersonalWorkspace();
  const second = adapter.ensurePersonalWorkspace();
  assert.equal(first, second);
  const workspace = await first;
  assert.equal(workspace.name, "Không gian cá nhân mẫu");
  assert.equal(await adapter.getPersonalWorkspace(), workspace);
  assert.equal(await adapter.ensurePersonalWorkspace(), workspace);
});

test("existing fixture is reused without a new record", async () => {
  const adapter = createMockWorkspaceAdapter("existing");
  const existing = await adapter.getPersonalWorkspace();
  assert.ok(existing);
  assert.equal(await adapter.ensurePersonalWorkspace(), existing);
});

test("first failure is shared, clears pending work and allows a successful retry", async () => {
  const adapter = createMockWorkspaceAdapter("error_once");
  const first = adapter.ensurePersonalWorkspace();
  assert.equal(first, adapter.ensurePersonalWorkspace());
  await assert.rejects(first, /preparation failed/);
  assert.equal(await adapter.getPersonalWorkspace(), null);
  const workspace = await adapter.ensurePersonalWorkspace();
  assert.equal(await adapter.ensurePersonalWorkspace(), workspace);
});

test("a fresh auth session starts with an independent adapter", async () => {
  const oldSession = createMockWorkspaceAdapter("success");
  await oldSession.ensurePersonalWorkspace();
  const newSession = createMockWorkspaceAdapter("success");
  assert.equal(await newSession.getPersonalWorkspace(), null);
});
