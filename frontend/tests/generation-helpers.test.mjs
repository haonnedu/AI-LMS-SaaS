import assert from "node:assert/strict";
import { test } from "node:test";
import {
  approveMessage, buildDraftRequest, buildExamFromBlueprint, buildManualExam, canViewSource, exportFailureMessage, exportFileName, expiryLabel, generationOutcome,
  parseObjectives, provenanceStatus, reportFromError, safeDownloadUrl, sourceLocation, sourceSnippet, suggestionsToRequests, totalPoints,
} from "../src/lib/client/generation.ts";

const UNIT = "11111111-1111-4111-8111-111111111111";
const form = { purpose: "lesson_plan", curriculumUnitId: UNIT, grade: 6, subject: "toan", objectivesText: "- Hiểu phân số\n2) Cộng phân số\n\nHiểu phân số", duration: "45", documentIds: [] };

test("objectives parsing dedupes and strips bullets", () => {
  assert.deepEqual(parseObjectives("- a\n* b\n1. c\n\n a "), ["a", "b", "c"]);
});
test("draft request builds and validates", () => {
  const ok = buildDraftRequest(form);
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.value.objectives, ["Hiểu phân số", "Cộng phân số"]);
  assert.equal(ok.value.durationMinutes, 45);
  assert.equal("documentIds" in ok.value, false);
  assert.equal(buildDraftRequest({ ...form, objectivesText: "  " }).ok, false);
  assert.equal(buildDraftRequest({ ...form, curriculumUnitId: "" }).ok, false);
  assert.equal(buildDraftRequest({ ...form, duration: "2" }).ok, false);
  assert.equal(buildDraftRequest({ ...form, documentIds: ["x"] }).ok, false);
  assert.equal(buildDraftRequest({ ...form, objectivesText: "a".repeat(301) }).ok, false);
  assert.equal(buildDraftRequest({ ...form, duration: "" }).ok, true);
});
test("generation outcome mapping", () => {
  assert.equal(generationOutcome({ validationStatus: "pending", errorCode: null, reasons: [] }).kind, "pending");
  assert.equal(generationOutcome({ validationStatus: "failed", errorCode: "provider_unavailable", reasons: [] }).kind, "unavailable");
  const invalid = generationOutcome({ validationStatus: "invalid", errorCode: null, reasons: ["thiếu nguồn"] });
  assert.equal(invalid.kind, "invalid"); assert.deepEqual(invalid.reasons, ["thiếu nguồn"]);
  assert.equal(generationOutcome({ validationStatus: "failed", errorCode: "boom", reasons: [] }).kind, "failed");
  const ok = generationOutcome({ validationStatus: "valid", errorCode: null, reasons: [], contentItemId: UNIT, revisionNo: 3 });
  assert.equal(ok.kind, "success"); assert.equal(ok.revisionNo, 3);
});
test("provenance statuses never invent withdrawn text", () => {
  assert.equal(provenanceStatus("withdrawn").label, "Nguồn không còn tồn tại");
  assert.equal(provenanceStatus("unknown").label, "Nguồn không còn tồn tại");
  const withdrawn = { snippet: "đoán", status: "withdrawn", chunkId: "c", pageNo: 2, sectionPath: null };
  assert.equal(sourceSnippet(withdrawn), null);
  assert.equal(canViewSource(withdrawn), false);
  assert.equal(canViewSource({ ...withdrawn, status: "active" }), true);
  assert.equal(canViewSource({ ...withdrawn, status: "active", chunkId: null }), false);
  assert.equal(sourceLocation({ ...withdrawn, sectionPath: "Chương 1" }), "trang 2 · Chương 1");
  assert.match(approveMessage("citations_unresolved", "x"), /trích dẫn/);
  assert.equal(approveMessage("other", "fallback"), "fallback");
});
test("export file names and messages", () => {
  assert.equal(exportFileName("Đề kiểm tra giữa kỳ I – Toán 6", "teacher", "docx"), "de-kiem-tra-giua-ky-i-toan-6-giao-vien.docx");
  assert.equal(exportFileName("???", "student", "pdf"), "tai-lieu-hoc-sinh.pdf");
  assert.match(exportFailureMessage("pdf_font_missing", "pdf"), /pdf_font_missing.*PDF chưa hỗ trợ tiếng Việt, dùng DOCX/);
  assert.doesNotMatch(exportFailureMessage("x", "docx"), /PDF chưa/);
  assert.equal(safeDownloadUrl("javascript:alert(1)"), null);
  assert.equal(safeDownloadUrl(null), null);
  assert.ok(safeDownloadUrl("https://files.example.com/a?sig=1"));
  const now = Date.parse("2026-01-01T00:00:00Z");
  assert.match(expiryLabel("2026-01-01T00:10:00Z", now), /10 phút/);
  assert.match(expiryLabel("2025-12-31T00:00:00Z", now), /hết hạn/);
});
test("exam from blueprint and selection report mapping", () => {
  assert.equal(buildExamFromBlueprint("bad", "", "").ok, false);
  assert.deepEqual(buildExamFromBlueprint(UNIT, "  ", "").value, { blueprintVersionId: UNIT });
  assert.deepEqual(buildExamFromBlueprint(UNIT, "s-1", " Đề ").value, { blueprintVersionId: UNIT, seed: "s-1", title: "Đề" });
  assert.equal(buildExamFromBlueprint(UNIT, "bad seed!", "").ok, false);
  assert.equal(reportFromError(null), null);
  assert.equal(reportFromError({ code: "insufficient_pool" }), null);
  const report = reportFromError({ selectionReport: { missingSlots: [{}], suggestedGeneration: [{ cognitiveLevel: "apply", count: 3, curriculumUnitId: UNIT, difficulty: 2, purpose: "questions" }, { cognitiveLevel: "apply", count: 0, curriculumUnitId: UNIT, difficulty: null, purpose: "questions" }] } });
  const requests = suggestionsToRequests(report, { grade: 6, subject: "toan" });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].purpose, "questions"); assert.equal(requests[0].count, 3); assert.equal(requests[0].cognitiveLevel, "apply");
  assert.equal(buildDraftRequest({ ...form, purpose: "questions", objectivesText: requests[0].objectives.join("\n") }).ok, true);
});
test("manual exam", () => {
  const picks = [{ id: UNIT, points: "0.25" }, { id: "22222222-2222-4222-8222-222222222222", points: "1" }];
  assert.equal(totalPoints(picks), 1.25);
  assert.deepEqual(buildManualExam(" Đề 1 ", picks).value, { title: "Đề 1", questionIds: picks.map(p => p.id), points: [0.25, 1] });
  assert.equal(buildManualExam("", picks).ok, false);
  assert.equal(buildManualExam("x", []).ok, false);
  assert.equal(buildManualExam("x", [{ id: UNIT, points: "0" }]).ok, false);
});
