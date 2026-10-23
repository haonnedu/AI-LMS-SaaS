import assert from "node:assert/strict";
import { test } from "node:test";
import { allowQuery, isInviteToken, isUuid, pickUploadHeaders, QUERY_RULES, safeJoinReturnTo } from "../src/lib/server/validation.ts";
import { buildUploadHeaders, uploadContentType } from "../src/lib/client/upload.ts";
import { applyPoll, isTerminal, nextDelay, pendingJobIds, shouldContinue } from "../src/lib/client/jobs.ts";

const uuid = "0b9f3c1e-6a52-4c1d-9f0e-2a7d8c4b5e61";
const token = "A".repeat(43);

test("uuid validator", () => {
  assert.equal(isUuid(uuid), true);
  for (const bad of ["", "../x", uuid + "/", uuid.slice(1), "g".repeat(36), undefined, 5]) assert.equal(isUuid(bad), false);
});
test("invitation token validator", () => {
  assert.equal(isInviteToken(token), true);
  assert.equal(isInviteToken("a-b_".repeat(10)), true);
  for (const bad of ["short", "A".repeat(129), "A".repeat(31) + "/", "A".repeat(31) + "?", "A".repeat(31) + " "]) assert.equal(isInviteToken(bad), false);
});
test("header allowlist drops everything else", () => {
  const headers = new Headers({ "content-type": "application/pdf", "content-length": "10", "x-file-name": "a.pdf", "x-rights-attested": "true", "idempotency-key": "k", authorization: "Bearer evil", cookie: "x=1", "x-forwarded-for": "1.1.1.1", "x-csrf-token": "t", origin: "http://x" });
  assert.deepEqual(Object.keys(pickUploadHeaders(headers)).sort(), ["content-length", "content-type", "idempotency-key", "x-file-name", "x-rights-attested"]);
  assert.deepEqual(pickUploadHeaders(new Headers({ authorization: "x" })), {});
});
test("query allowlist", () => {
  assert.equal(allowQuery(new URLSearchParams("a=1"), ["cursor"]), null);
  assert.equal(allowQuery(new URLSearchParams("limit=abc"), ["limit"], QUERY_RULES), null);
  assert.equal(allowQuery(new URLSearchParams("cursor=x&cursor=y"), ["cursor"]), null);
  assert.equal(allowQuery(new URLSearchParams("limit=20&status=active"), ["limit", "status"], QUERY_RULES)?.toString(), "limit=20&status=active");
  assert.equal(allowQuery(new URLSearchParams(), ["limit"])?.toString(), "");
});
test("returnTo accepts only /join/<token>", () => {
  assert.equal(safeJoinReturnTo("/join/" + token), "/join/" + token);
  for (const bad of ["//evil.com", "https://evil.com", "/join/" + token + "/x", "/dashboard", "/join/short", "/join/" + token + "?a=b", undefined]) assert.equal(safeJoinReturnTo(bad), null);
});
test("upload header builder", () => {
  const headers = buildUploadHeaders({ name: "Bài giảng 1.PDF" }, "csrf", "idem");
  assert.equal(headers["Content-Type"], "application/pdf");
  assert.equal(headers["X-File-Name"], encodeURIComponent("Bài giảng 1.PDF"));
  assert.equal(decodeURIComponent(headers["X-File-Name"]), "Bài giảng 1.PDF");
  assert.equal(headers["X-Rights-Attested"], "true");
  assert.equal(headers["X-CSRF-Token"], "csrf");
  assert.equal(headers["Idempotency-Key"], "idem");
  assert.equal(buildUploadHeaders({ name: "a.exe" }, "c"), null);
  assert.equal(buildUploadHeaders({ name: "noext" }, "c"), null);
  assert.equal(uploadContentType("a.txt"), "text/plain");
  assert.match(uploadContentType("a.docx"), /wordprocessingml/);
  assert.equal("Idempotency-Key" in buildUploadHeaders({ name: "a.txt" }, "c"), false);
});
test("job polling state machine", () => {
  assert.deepEqual(["succeeded", "failed", "cancelled"].map(isTerminal), [true, true, true]);
  assert.deepEqual(["queued", "running"].map(isTerminal), [false, false]);
  let state = { statuses: { a: "queued", b: "running", c: "succeeded" }, errors: 0 };
  assert.deepEqual(pendingJobIds(state.statuses), ["a", "b"]);
  state = applyPoll(state, [{ id: "a", status: "running" }, { id: "b", failed: true }]);
  assert.equal(state.errors, 1);
  assert.equal(state.statuses.a, "running");
  assert.equal(shouldContinue(state), true);
  state = applyPoll(state, [{ id: "a", status: "succeeded" }, { id: "b", status: "failed" }]);
  assert.equal(state.errors, 0);
  assert.equal(shouldContinue(state), false);
  assert.equal(nextDelay(0), 3000);
  assert.equal(nextDelay(1), 6000);
  assert.equal(nextDelay(10), 15000);
});
