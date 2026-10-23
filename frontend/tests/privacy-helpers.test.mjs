import assert from "node:assert/strict";
import { test } from "node:test";
import {
  activeConsentId, ageFromBirthYear, birthYearOptions, blockingConsents, consentLabel, consentLinkOutcome, consentLinkUrl, givenName, guardianFlowEnabled, isConsentToken, isMinor, showsGuardianCard,
  isRequestFailed, isRequestTerminal, isValidBirthYear, latestPolicyVersion, needsBirthYear, requestPollDelay, requestStatusText, safeDownloadUrl, shouldPollRequest,
  REQUEST_POLL_MAX_ATTEMPTS, REQUEST_POLL_MAX_MS,
} from "../src/lib/client/privacy.ts";

const now = new Date("2026-10-23T00:00:00Z");

test("age and minor threshold are configurable", () => {
  assert.equal(ageFromBirthYear(2012, now), 14);
  assert.equal(isMinor(2012, 16, now), true);
  assert.equal(isMinor(2010, 16, now), false);
  assert.equal(isMinor(2010, 17, now), true);
  assert.equal(isMinor(null, 16, now), false);
  assert.equal(isMinor(2010.5, 16, now), false);
});

test("birth year validation and options", () => {
  assert.equal(isValidBirthYear(2010, now), true);
  assert.equal(isValidBirthYear(1989, now), false);
  assert.equal(isValidBirthYear(2027, now), false);
  assert.equal(isValidBirthYear("2010", now), false);
  const options = birthYearOptions(now);
  assert.equal(options[0], 2026);
  assert.equal(options.at(-1), 1990);
  assert.equal(options.length, 37);
});

test("status labels, names and link builder", () => {
  assert.equal(consentLabel("granted"), "Đã đồng ý");
  assert.equal(consentLabel("weird"), "Không rõ");
  assert.equal(givenName("Nguyễn Văn An"), "An");
  assert.equal(givenName("  "), "");
  assert.equal(consentLinkUrl("https://eduvia.test/", "abc"), "https://eduvia.test/consent/abc");
  assert.equal(isConsentToken("a".repeat(32)), true);
  assert.equal(isConsentToken("short"), false);
  assert.equal(isConsentToken("a".repeat(31) + "/"), false);
});

test("student gate helpers", () => {
  const items = [
    { workspaceId: "1", className: "A", consentStatus: "granted", consentRequired: true, policyVersion: "v1" },
    { workspaceId: "2", className: "B", consentStatus: "pending", consentRequired: true, policyVersion: "v1" },
    { workspaceId: "3", className: "C", consentStatus: "not_required", consentRequired: false, policyVersion: "v1" },
  ];
  assert.equal(needsBirthYear(items), false);
  assert.deepEqual(blockingConsents(items).map(item => item.className), ["B"]);
  assert.equal(needsBirthYear([{ ...items[0], consentStatus: "unknown" }]), true);
});

test("consent record helpers", () => {
  const consents = [{ id: "x", grantedAt: "t", revokedAt: "r", policyVersion: "v1" }, { id: "y", grantedAt: "t", revokedAt: null, policyVersion: "v2" }];
  assert.equal(activeConsentId(consents), "y");
  assert.equal(activeConsentId([]), null);
  assert.equal(latestPolicyVersion([{ consents: [] }, { consents }]), "v1");
  assert.equal(latestPolicyVersion([]), null);
});

test("request polling state", () => {
  assert.equal(isRequestTerminal("queued"), false);
  assert.equal(isRequestTerminal("completed"), true);
  assert.equal(isRequestFailed("failed"), true);
  assert.equal(shouldPollRequest(null, 0), false);
  assert.equal(shouldPollRequest({ status: "queued" }, 0), true);
  assert.equal(shouldPollRequest({ status: "running", downloadUrl: "https://x/y" }, 0), false);
  assert.equal(shouldPollRequest({ status: "completed" }, 1), false);
  assert.equal(shouldPollRequest({ status: "queued" }, REQUEST_POLL_MAX_ATTEMPTS), false);
  assert.equal(requestPollDelay(0), 2000);
  assert.equal(requestPollDelay(5), 4000);
  assert.equal(requestPollDelay(0, 2), 8000);
  assert.equal(requestPollDelay(100, 9), REQUEST_POLL_MAX_MS);
  assert.match(requestStatusText("export", "queued"), /Đang chuẩn bị/);
  assert.match(requestStatusText("erasure", "failed"), /chưa thực hiện/);
});

test("download urls and public link outcomes", () => {
  assert.equal(safeDownloadUrl("https://files.test/a.zip?sig=1"), "https://files.test/a.zip?sig=1");
  assert.equal(safeDownloadUrl("/files/a.zip"), "/files/a.zip");
  assert.equal(safeDownloadUrl("//evil.test/a"), null);
  assert.equal(safeDownloadUrl("javascript:alert(1)"), null);
  assert.equal(safeDownloadUrl(null), null);
  assert.equal(consentLinkOutcome(200), "ok");
  assert.equal(consentLinkOutcome(404), "invalid");
  assert.equal(consentLinkOutcome(410, "gone"), "expired");
  assert.equal(consentLinkOutcome(410, "link_used"), "used");
  assert.equal(consentLinkOutcome(429), "rate_limited");
  assert.equal(consentLinkOutcome(503), "error");
});

test("guardian consent UI follows the server mode (decision 0009)", () => {
  assert.equal(guardianFlowEnabled("guardian"), true);
  for (const mode of ["signup", undefined, null, "other"]) assert.equal(guardianFlowEnabled(mode), false);
  assert.equal(showsGuardianCard("signup"), false);
  for (const mode of ["guardian", undefined, null]) assert.equal(showsGuardianCard(mode), true);
});
