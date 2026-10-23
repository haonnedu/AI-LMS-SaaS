import assert from "node:assert/strict";
import { test } from "node:test";
import {
  acceptanceBody, isAgreementRetryCode, isAgreementStatus, isAgreementVersion, needsAgreement, sanitizeAcceptance,
} from "../src/lib/client/agreements.ts";
import { USER_AGREEMENT_SECTIONS, USER_AGREEMENT_VERSION } from "../src/content/user-agreement.ts";
import { PRIVACY_NOTICE_VERSION } from "../src/content/privacy-notice.ts";

const status = (accepted = { userAgreement: null, privacy: null }, upToDate = false) => ({
  required: { userAgreement: "2026-10-draft", privacy: "2026-10-draft" }, accepted, upToDate,
});

test("agreement status shape is validated", () => {
  assert.equal(isAgreementStatus(status()), true);
  assert.equal(isAgreementStatus(status({ userAgreement: "2026-10-draft", privacy: "2026-10-draft" }, true)), true);
  for (const bad of [null, undefined, "x", {}, { ...status(), upToDate: "no" }, { ...status(), required: { userAgreement: null, privacy: "v" } },
    { ...status(), required: { userAgreement: "bad version", privacy: "v" } }, { ...status(), accepted: null }]) assert.equal(isAgreementStatus(bad), false);
});

test("only an out-of-date status needs the checkbox", () => {
  assert.equal(needsAgreement(status()), true);
  assert.equal(needsAgreement(status({ userAgreement: "2026-09-draft", privacy: "2026-10-draft" })), true);
  assert.equal(needsAgreement(status({ userAgreement: "2026-10-draft", privacy: "2026-10-draft" }, true)), false);
  assert.equal(needsAgreement(null), false);
  assert.equal(needsAgreement(undefined), false);
});

test("acceptance body always carries the server-required versions", () => {
  assert.deepEqual(acceptanceBody(status({ userAgreement: "old", privacy: "old" })), { userAgreementVersion: "2026-10-draft", privacyVersion: "2026-10-draft", accepted: true });
  assert.throws(() => acceptanceBody({ required: { userAgreement: null, privacy: "v" }, accepted: { userAgreement: null, privacy: null }, upToDate: false }));
});

test("BFF accepts exactly the expected keys with an explicit true", () => {
  const good = { userAgreementVersion: "2026-10-draft", privacyVersion: "2026-11-v1", accepted: true };
  assert.deepEqual(sanitizeAcceptance(good), good);
  for (const bad of [null, [], "x", { ...good, accepted: false }, { ...good, accepted: "true" }, { userAgreementVersion: "v", privacyVersion: "v" },
    { ...good, clientHash: "a".repeat(64) }, { ...good, ip: "1.2.3.4" }, { ...good, privacyVersion: "../x" }, { ...good, userAgreementVersion: "x".repeat(33) }]) {
    assert.equal(sanitizeAcceptance(bad), null, JSON.stringify(bad));
  }
});

test("version format and retry codes", () => {
  for (const ok of ["2026-10-draft", "2026-11-v1", "a.b_c"]) assert.equal(isAgreementVersion(ok), true);
  for (const bad of ["", "has space", "x".repeat(33), 5, null]) assert.equal(isAgreementVersion(bad), false);
  assert.equal(isAgreementRetryCode("agreement_required"), true);
  assert.equal(isAgreementRetryCode("agreement_version_outdated"), true);
  assert.equal(isAgreementRetryCode("onboarding_required"), false);
  assert.equal(isAgreementRetryCode(undefined), false);
});

test("in-app user agreement is a short versioned draft", () => {
  assert.equal(USER_AGREEMENT_VERSION, "2026-10-draft");
  assert.equal(USER_AGREEMENT_VERSION, PRIVACY_NOTICE_VERSION, "bump both documents together");
  const words = USER_AGREEMENT_SECTIONS.flatMap(section => [section.title, ...section.paragraphs]).join(" ").split(/\s+/).filter(Boolean).length;
  assert.ok(words <= 900, `user agreement has ${words} words`);
  assert.match(USER_AGREEMENT_SECTIONS[0].paragraphs.join(" "), /dự thảo/i);
});
