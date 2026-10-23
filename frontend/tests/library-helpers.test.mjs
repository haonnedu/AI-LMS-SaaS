import assert from "node:assert/strict";
import { test } from "node:test";
import { buildQueryBody, citationLabel, formatLocation, groupByDocument, isPilotDraft, mergeById, QUERY_MAX, sortUnits, titleMap, toggleId, validateK, validateQuery } from "../src/lib/client/library.ts";

test("query validation", () => {
  assert.equal(validateQuery("   ").ok, false);
  assert.deepEqual(validateQuery("  phân số  "), { ok: true, query: "phân số" });
  assert.equal(validateQuery("a".repeat(QUERY_MAX)).ok, true);
  assert.equal(validateQuery("a".repeat(QUERY_MAX + 1)).ok, false);
});
test("k validation", () => {
  for (const good of [1, 8, 20]) assert.equal(validateK(good), good);
  for (const bad of [0, 21, 1.5, "5", null, NaN]) assert.equal(validateK(bad), null);
});
test("query body", () => {
  assert.deepEqual(buildQueryBody(" x ", []), { query: "x", k: 8 });
  assert.deepEqual(buildQueryBody("x", ["d1"], 3), { query: "x", k: 3, documentIds: ["d1"] });
  assert.equal(buildQueryBody("", []), null);
  assert.equal(buildQueryBody("x", [], 99), null);
});
test("citation labels and location", () => {
  assert.equal(formatLocation({ pageNo: 3, sectionPath: "Chương 1 > Bài 2" }), "Trang 3 · Chương 1 > Bài 2");
  assert.equal(formatLocation({ pageNo: null, sectionPath: null }), "");
  assert.equal(citationLabel({ citation: " [Toán 6, tr. 3] ", pageNo: 3, sectionPath: null }, "x"), "[Toán 6, tr. 3]");
  assert.equal(citationLabel({ citation: "", pageNo: 2, sectionPath: null }, "a.pdf"), "a.pdf, Trang 2");
  assert.equal(citationLabel({ pageNo: null, sectionPath: null }), "");
});
test("group by document keeps rank order", () => {
  const items = [{ documentId: "b", n: 1 }, { documentId: "a", n: 2 }, { documentId: "b", n: 3 }];
  const groups = groupByDocument(items);
  assert.deepEqual(groups.map(g => g.documentId), ["b", "a"]);
  assert.deepEqual(groups[0].items.map(i => i.n), [1, 3]);
  assert.deepEqual(groupByDocument([]), []);
});
test("misc helpers", () => {
  assert.deepEqual(titleMap([{ id: "1", fileName: "a.pdf" }]), { 1: "a.pdf" });
  assert.deepEqual(toggleId(["a"], "b"), ["a", "b"]);
  assert.deepEqual(toggleId(["a", "b"], "a"), ["b"]);
  assert.deepEqual(mergeById([{ id: "1" }], [{ id: "1" }, { id: "2" }]), [{ id: "1" }, { id: "2" }]);
  assert.deepEqual(sortUnits([{ sortOrder: 2, unitCode: "b" }, { sortOrder: 1, unitCode: "z" }, { sortOrder: 1, unitCode: "a" }]).map(u => u.unitCode), ["a", "z", "b"]);
  assert.equal(isPilotDraft("seed:pilot-draft"), true);
  assert.equal(isPilotDraft("other"), false);
});
