import assert from "node:assert/strict";
import { test } from "node:test";
import {
  blueprintTotals, bodyKey, buildBlueprintBody, buildBody, buildQuestionBody, canSave, conflictMessage, conflictRevision, deriveMatrix, emptyBody,
  emptyQuestionForm, initialSave, moveItem, normalizeBlueprintBody, normalizeBody, parseCsv, previewCsv, questionQuery, saveLabel, saveReducer,
  shouldSchedule, validateQuestionForm, CSV_COLUMNS,
} from "../src/lib/client/authoring.ts";

const chunk = "0b9f3c1e-6a52-4c1d-9f0e-2a7d8c4b5e61";
const unit = "1b9f3c1e-6a52-4c1d-9f0e-2a7d8c4b5e62";

test("normalizeBody is tolerant and keeps only valid citations", () => {
  assert.deepEqual(normalizeBody(null), emptyBody());
  assert.deepEqual(normalizeBody({ sections: [] }), emptyBody());
  const body = normalizeBody({ sections: [{ heading: 5, blocks: [{ type: "weird", text: "a", citations: [{ chunkId: chunk, label: "T1" }, { chunkId: "x" }] }, "junk"] }] });
  assert.equal(body.sections[0].heading, "");
  assert.equal(body.sections[0].blocks.length, 1);
  assert.equal(body.sections[0].blocks[0].type, "paragraph");
  assert.deepEqual(body.sections[0].blocks[0].citations, [{ chunkId: chunk, label: "T1" }]);
  assert.equal(bodyKey(body), bodyKey(buildBody(body)));
});
test("moveItem reorders and ignores out-of-range moves", () => {
  assert.deepEqual(moveItem([1, 2, 3], 0, 2), [2, 3, 1]);
  assert.deepEqual(moveItem([1, 2, 3], 2, 1), [1, 3, 2]);
  assert.deepEqual(moveItem([1, 2, 3], 0, 3), [1, 2, 3]);
  assert.deepEqual(moveItem([1, 2, 3], -1, 1), [1, 2, 3]);
});

test("autosave: edit -> save -> saved", () => {
  let s = initialSave(3);
  assert.equal(canSave(s), false);
  s = saveReducer(s, { type: "edit" });
  assert.equal(s.phase, "dirty");
  assert.equal(shouldSchedule(s), true);
  assert.equal(canSave(s), true);
  s = saveReducer(s, { type: "saveStart" });
  assert.equal(s.phase, "saving");
  assert.equal(canSave(s), false);
  s = saveReducer(s, { type: "saveOk", revisionNo: 3, savedAt: "2026-01-01T08:05:00" });
  assert.equal(s.phase, "saved");
  assert.equal(saveLabel(s, () => "08:05"), "Đã lưu lúc 08:05");
});
test("autosave: edits during a save stay dirty afterwards", () => {
  let s = saveReducer(initialSave(1), { type: "edit" });
  s = saveReducer(s, { type: "saveStart" });
  s = saveReducer(s, { type: "edit" });
  assert.equal(s.phase, "saving");
  s = saveReducer(s, { type: "saveOk", revisionNo: 1, savedAt: "2026-01-01T08:05:00" });
  assert.equal(s.phase, "dirty");
  assert.equal(canSave(s), true);
});
test("autosave: failure is retryable, conflict blocks saving until reset", () => {
  let s = saveReducer(initialSave(1), { type: "edit" });
  s = saveReducer(s, { type: "saveStart" });
  s = saveReducer(s, { type: "saveFail" });
  assert.equal(s.phase, "error");
  assert.equal(saveLabel(s), "Lỗi lưu");
  assert.equal(canSave(s), true);
  s = saveReducer(s, { type: "saveStart" });
  s = saveReducer(s, { type: "conflict", latestRevisionNo: 5 });
  assert.equal(s.phase, "conflict");
  assert.equal(s.latestRevisionNo, 5);
  s = saveReducer(s, { type: "edit" });
  assert.equal(s.phase, "conflict");
  assert.equal(canSave(s), false);
  assert.equal(saveReducer(s, { type: "saveStart" }), s);
  assert.equal(saveReducer(s, { type: "reset", revisionNo: 5 }).phase, "idle");
});
test("conflict helpers", () => {
  assert.equal(conflictRevision({ code: "revision_conflict", latestRevisionNo: 7 }), 7);
  assert.equal(conflictRevision({ latestRevisionNo: "7" }), null);
  assert.equal(conflictRevision(undefined), null);
  assert.equal(conflictMessage(7), "Bản nháp đã được sửa ở nơi khác (bản 7)");
});

test("question form validation and body", () => {
  const form = emptyQuestionForm();
  assert.equal(validateQuestionForm(form).ok, false);
  form.stem = " 1+1? "; form.choices = ["1", "2", "3"]; form.correctKey = "B"; form.difficulty = "3"; form.curriculumUnitId = unit;
  assert.deepEqual(validateQuestionForm(form), { ok: true });
  const body = buildQuestionBody(form, 4);
  assert.equal(body.stem, "1+1?");
  assert.deepEqual(body.choices.map(c => c.key), ["A", "B", "C"]);
  assert.equal(body.correctKey, "B");
  assert.equal(body.difficulty, 3);
  assert.equal(body.expectedRevisionNo, 4);
  assert.equal("expectedRevisionNo" in buildQuestionBody(form), false);
  assert.equal(validateQuestionForm({ ...form, choices: ["1", "2"] }).ok, false);
  assert.equal(validateQuestionForm({ ...form, choices: ["1", "2", "3", "4", "5", "6"] }).ok, false);
  assert.equal(validateQuestionForm({ ...form, correctKey: "D" }).ok, false);
  assert.equal(validateQuestionForm({ ...form, choices: ["1", " ", "3"] }).ok, false);
  assert.equal(validateQuestionForm({ ...form, difficulty: "9" }).ok, false);
});
test("question query drops empty filters", () => {
  assert.equal(questionQuery({ status: "", q: " abc " }, null, 10), "?q=abc&limit=10");
  assert.equal(questionQuery({}, "cur"), "?limit=25&cursor=cur");
});

test("csv parsing handles quotes, newlines and BOM", () => {
  assert.deepEqual(parseCsv("﻿a,\"b,1\",\"he said \"\"hi\"\"\"\r\n\"x\ny\",z\n"), [["a", "b,1", 'he said "hi"'], ["x\ny", "z"]]);
  assert.deepEqual(parseCsv(""), []);
});
test("csv preview checks header and column count", () => {
  const header = CSV_COLUMNS.join(",");
  const good = header + "\nQ?,a,b,c,,,A,2,remember,,why\n\n";
  const ok = previewCsv(good);
  assert.equal(ok.ok, true);
  assert.equal(ok.rowCount, 1);
  const bad = previewCsv(header + "\nQ?,a,b\n");
  assert.equal(bad.ok, false);
  assert.deepEqual(bad.problems, [{ row: 2, message: "Số cột của dòng không đúng." }]);
  assert.equal(previewCsv("foo,bar\n1,2").headerOk, false);
  assert.equal(previewCsv("").ok, false);
});

const slot = (u, c, points = 0.5) => ({ itemType: "single_choice", points, curriculumUnitId: u, cognitiveLevel: c });
test("blueprint normalise renumbers slots and defaults", () => {
  const body = normalizeBlueprintBody({ parts: [{ code: "I", title: "P1", slots: [slot(unit, "apply"), { ...slot(unit, "bogus"), difficulty: 9 }] }, { code: "II", title: "P2", slots: [slot(unit, "remember")] }], matrix: [{ curriculumUnitId: unit, cognitiveLevel: "apply", count: "2" }] });
  assert.deepEqual(body.parts.flatMap(p => p.slots.map(s => s.index)), [1, 2, 3]);
  assert.equal(body.parts[0].slots[1].cognitiveLevel, "remember");
  assert.equal("difficulty" in body.parts[0].slots[1], false);
  assert.equal(body.matrix[0].count, 2);
  assert.equal(normalizeBlueprintBody(null).parts.length, 1);
});
test("blueprint totals and matrix mismatches", () => {
  const body = normalizeBlueprintBody({ parts: [{ code: "I", title: "", slots: [slot(unit, "apply", 0.25), slot(unit, "apply", 0.25), slot(unit, "remember", 0.5)] }], matrix: [{ curriculumUnitId: unit, cognitiveLevel: "apply", count: 1 }] });
  const totals = blueprintTotals(body);
  assert.equal(totals.slots, 3);
  assert.equal(totals.points, 1);
  assert.deepEqual(totals.byLevel, { remember: 1, understand: 0, apply: 2, analyze: 0 });
  assert.deepEqual(totals.mismatches.map(m => [m.cognitiveLevel, m.slots, m.matrix]), [["apply", 2, 1], ["remember", 1, 0]]);
  const derived = { ...body, matrix: deriveMatrix(body) };
  assert.equal(blueprintTotals(derived).mismatches.length, 0);
  assert.equal(blueprintTotals(derived).matrixCount, 3);
});
test("buildBlueprintBody trims and drops empty matrix rows", () => {
  const body = normalizeBlueprintBody({ parts: [{ code: " I ", title: " T ", slots: [slot(unit, "apply")] }], matrix: [{ curriculumUnitId: "", cognitiveLevel: "apply", count: 2 }, { curriculumUnitId: unit, cognitiveLevel: "apply", count: 0 }, { curriculumUnitId: unit, cognitiveLevel: "apply", count: 1 }] });
  const out = buildBlueprintBody(body);
  assert.equal(out.parts[0].code, "I");
  assert.equal(out.parts[0].title, "T");
  assert.equal(out.matrix.length, 1);
});
