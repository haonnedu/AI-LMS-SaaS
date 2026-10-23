import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ackSave, adoptServer, beginSave, buildAssignmentBody, buildOverrideBody, canStart, clearIdempotencyKey, clockOffset, denominatorsText, failSave,
  formatCountdown, getIdempotencyKey, groupByAvailability, initItem, isAttemptOver, isRetryableStatus, isoToZoned, needsSave, remainingMs, retryDelay,
  saveLabel, scoreText, selectAnswer, startLabel, timerPhase, unansweredCount, unsavedCount, windowHint, zonedToIso, emptyAssignmentForm,
} from "../src/lib/client/assessment.ts";
import { isIdempotencyKey } from "../src/lib/server/validation.ts";

const server = (selectedKey = null, answerRevision = 0, clientSequence = 0) => ({ selectedKey, answerRevision, clientSequence });

test("server clock offset ignores a wrong device clock", () => {
  const offset = clockOffset("2026-10-23T10:00:00Z", Date.parse("2026-10-23T09:00:00Z"));
  assert.equal(offset, 3600000);
  // device says 09:30, so server time is 10:30; deadline 10:45 leaves 15 minutes
  assert.equal(remainingMs("2026-10-23T10:45:00Z", offset, Date.parse("2026-10-23T09:30:00Z")), 15 * 60000);
  assert.equal(remainingMs("2026-10-23T10:00:00Z", offset, Date.parse("2026-10-23T09:30:00Z")), 0);
  assert.equal(remainingMs(null, 0), null);
  assert.equal(clockOffset("nope"), null);
});
test("countdown formatting and phases", () => {
  assert.equal(formatCountdown(65000), "01:05");
  assert.equal(formatCountdown(3725000), "1:02:05");
  assert.equal(formatCountdown(90000000), "1 ngày 1 giờ");
  assert.equal(formatCountdown(-5), "00:00");
  assert.equal(timerPhase(null), "none");
  assert.equal(timerPhase(300000), "running");
  assert.equal(timerPhase(120000), "warning");
  assert.equal(timerPhase(1), "warning");
  assert.equal(timerPhase(0), "expired");
});
test("availability helpers", () => {
  assert.equal(canStart("resume"), true);
  assert.equal(canStart("open"), true);
  for (const a of ["not_open_yet", "closed", "limit_reached", "done"]) assert.equal(canStart(a), false);
  assert.equal(startLabel("resume"), "Tiếp tục");
  assert.equal(startLabel("open"), "Bắt đầu làm bài");
  const groups = groupByAvailability([{ availability: "closed", id: 1 }, { availability: "open", id: 2 }, { availability: "resume", id: 3 }]);
  assert.deepEqual(groups.map(g => g.availability), ["resume", "open", "closed"]);
  const off = 0, now = Date.parse("2026-10-23T10:00:00Z");
  assert.match(windowHint("2026-10-23T11:00:00Z", null, off, now), /^Mở sau/);
  assert.match(windowHint("2026-10-23T09:00:00Z", "2026-10-23T10:30:00Z", off, now), /^Đóng sau/);
  assert.equal(windowHint("2026-10-23T09:00:00Z", "2026-10-23T09:30:00Z", off, now), "Đã quá hạn");
});
test("idempotency keys are stable per scope until cleared", () => {
  const store = new Map();
  const storage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k) };
  let n = 0;
  const gen = () => "generated-key-" + ++n;
  const a = getIdempotencyKey(storage, "start", "asg1", gen);
  assert.equal(getIdempotencyKey(storage, "start", "asg1", gen), a);
  assert.notEqual(getIdempotencyKey(storage, "start", "asg2", gen), a);
  assert.notEqual(getIdempotencyKey(storage, "submit", "asg1", gen), a);
  clearIdempotencyKey(storage, "start", "asg1");
  assert.notEqual(getIdempotencyKey(storage, "start", "asg1", gen), a);
  // a throwing storage still keeps the key for retries
  const broken = { getItem() { throw new Error("x"); }, setItem() { throw new Error("x"); }, removeItem() { throw new Error("x"); } };
  const b = getIdempotencyKey(broken, "start", "asg9", gen);
  assert.equal(getIdempotencyKey(broken, "start", "asg9", gen), b);
  assert.equal(isIdempotencyKey(b), true);
});
test("BFF idempotency key format", () => {
  assert.equal(isIdempotencyKey("0b9f3c1e-6a52-4c1d-9f0e-2a7d8c4b5e61"), true);
  for (const bad of ["short", "has space here!", "a".repeat(129), "x\r\ny12345678", "", null, 5]) assert.equal(isIdempotencyKey(bad), false);
});
test("autosave: select, save, ack uses increasing sequence and server revision", () => {
  let s = initItem(server(null, 2, 7));
  assert.equal(beginSave(s), null);
  s = selectAnswer(s, "B");
  assert.equal(s.status, "dirty");
  assert.equal(saveLabel(s), "Đang lưu…");
  const first = beginSave(s);
  assert.deepEqual(first.request, { selectedKey: "B", expectedRevision: 2, clientSequence: 8 });
  s = ackSave(first.state, first.request, 3);
  assert.equal(s.status, "saved");
  assert.equal(saveLabel(s), "Đã lưu");
  s = selectAnswer(s, "C");
  const second = beginSave(s);
  assert.deepEqual(second.request, { selectedKey: "C", expectedRevision: 3, clientSequence: 9 });
});
test("autosave: never saved before ack; newer pick during flight stays queued", () => {
  let s = selectAnswer(initItem(server(null, 0, 0)), "A");
  const sent = beginSave(s);
  s = sent.state;
  assert.equal(s.status, "saving");
  assert.equal(beginSave(s), null); // single flight per item
  s = selectAnswer(s, "B");
  assert.equal(s.status, "saving");
  s = ackSave(s, sent.request, 1);
  assert.equal(s.status, "dirty");
  assert.equal(needsSave(s), true);
  const next = beginSave(s);
  assert.deepEqual(next.request, { selectedKey: "B", expectedRevision: 1, clientSequence: 2 });
});
test("autosave: failure shows retry, keeps choice, retry bumps sequence", () => {
  let s = selectAnswer(initItem(server("A", 1, 1)), "D");
  const sent = beginSave(s);
  s = failSave(sent.state);
  assert.equal(s.status, "error");
  assert.equal(saveLabel(s), "Chưa lưu – thử lại");
  assert.equal(s.desiredKey, "D");
  const retry = beginSave(s);
  assert.equal(retry.request.clientSequence, 3);
  assert.equal(retry.request.expectedRevision, 1);
  // reverting to the saved value cancels the pending save
  assert.equal(selectAnswer(s, "A").status, "saved");
});
test("autosave: stale_answer adopts the server value", () => {
  let s = selectAnswer(initItem(server("A", 1, 1)), "C");
  s = beginSave(s).state;
  s = adoptServer(s, server("B", 5, 9));
  assert.equal(s.desiredKey, "B");
  assert.equal(s.status, "saved");
  assert.equal(s.refreshed, true);
  assert.equal(s.revision, 5);
  assert.equal(beginSave(s), null);
  assert.equal(beginSave(selectAnswer(s, "D")).request.clientSequence, 10);
});
test("counts and retry policy", () => {
  const states = [initItem(server("A")), initItem(server(null)), selectAnswer(initItem(server(null)), "B")];
  assert.equal(unansweredCount(states), 1);
  assert.equal(unsavedCount(states), 1);
  assert.equal(retryDelay(0), 1000);
  assert.equal(retryDelay(3), 8000);
  assert.equal(retryDelay(20), 15000);
  assert.equal(isRetryableStatus(null), true);
  assert.equal(isRetryableStatus(503), true);
  assert.equal(isRetryableStatus(422), false);
  assert.equal(isAttemptOver("attempt_expired"), true);
  assert.equal(isAttemptOver("stale_answer"), false);
});
test("null score is pending, never zero", () => {
  assert.equal(scoreText(null, "10.00"), "Chờ chấm");
  assert.equal(scoreText(undefined, null), "Chờ chấm");
  assert.notEqual(scoreText("0.00", "10.00"), "Chờ chấm");
  assert.match(scoreText("8.50", "10.00"), /^8[,.]5 \/ 10$/);
  assert.equal(denominatorsText({ enrolled: 30, started: 20, submitted: 18, graded: 10, pending: 8 }), "đã nộp 18 / đã chấm 10 / chờ chấm 8 / tổng 30");
});
test("time zone conversion", () => {
  assert.equal(zonedToIso("2026-11-01T08:00", "Asia/Ho_Chi_Minh"), "2026-11-01T01:00:00.000Z");
  assert.equal(zonedToIso("2026-11-01T08:00", "UTC"), "2026-11-01T08:00:00.000Z");
  assert.equal(zonedToIso("2026-02-31T08:00", "UTC"), null);
  assert.equal(zonedToIso("", "UTC"), null);
  assert.equal(isoToZoned("2026-11-01T01:00:00.000Z", "Asia/Ho_Chi_Minh"), "2026-11-01T08:00");
});
test("assignment form validation", () => {
  const ok = { ...emptyAssignmentForm(), examVersionId: "v", title: " Kiểm tra 15 phút ", opensAt: "2026-11-01T08:00", closesAt: "2026-11-02T08:00", timeLimitMinutes: "45", maxAttempts: "2" };
  const built = buildAssignmentBody(ok);
  assert.equal(built.ok, true);
  assert.equal(built.body.title, "Kiểm tra 15 phút");
  assert.equal(built.body.timeLimitSeconds, 2700);
  assert.equal(built.body.opensAt, "2026-11-01T01:00:00.000Z");
  assert.equal("instructions" in built.body, false);
  assert.equal(buildAssignmentBody({ ...ok, examVersionId: "" }).ok, false);
  assert.equal(buildAssignmentBody({ ...ok, title: "  " }).ok, false);
  assert.equal(buildAssignmentBody({ ...ok, closesAt: "2026-11-01T08:00" }).ok, false);
  assert.equal(buildAssignmentBody({ ...ok, timeLimitMinutes: "0" }).ok, false);
  assert.equal(buildAssignmentBody({ ...ok, maxAttempts: "x" }).ok, false);
  assert.equal(buildAssignmentBody({ ...ok, closesAt: "", timeLimitMinutes: "" }).ok, true);
});
test("override requires reason and bounded score", () => {
  assert.equal(buildOverrideBody("7,5", "Chấm lại", "10.00").body.score, 7.5);
  assert.equal(buildOverrideBody("7", "  ", "10.00").ok, false);
  assert.equal(buildOverrideBody("11", "x", "10.00").ok, false);
  assert.equal(buildOverrideBody("-1", "x", "10.00").ok, false);
  assert.equal(buildOverrideBody("", "x", "10.00").ok, false);
  assert.equal(buildOverrideBody("0", "x", "10.00").ok, true);
});
