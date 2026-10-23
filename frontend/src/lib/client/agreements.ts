// Pure, dependency-free helpers for accepting the user agreement + privacy notice (decision 0009).
// Used by the onboarding screen (client) and the BFF route (server); node:test friendly.
// TODO replace the local types with generated ones after api:generate.

export type AgreementVersions = { userAgreement: string | null; privacy: string | null };
export type AgreementStatus = { required: AgreementVersions; accepted: AgreementVersions; upToDate: boolean };
export type AgreementAcceptance = { userAgreementVersion: string; privacyVersion: string; accepted: true };

const VERSION = /^[A-Za-z0-9._-]{1,32}$/;
export const isAgreementVersion = (value: unknown): value is string => typeof value === "string" && VERSION.test(value);

const isVersions = (value: unknown): value is AgreementVersions => {
  if (typeof value !== "object" || value === null) return false;
  const { userAgreement, privacy } = value as Record<string, unknown>;
  return (userAgreement === null || isAgreementVersion(userAgreement)) && (privacy === null || isAgreementVersion(privacy));
};
export function isAgreementStatus(value: unknown): value is AgreementStatus {
  if (typeof value !== "object" || value === null) return false;
  const { required, accepted, upToDate } = value as Record<string, unknown>;
  return isVersions(required) && isVersions(accepted) && typeof upToDate === "boolean"
    && isAgreementVersion(required.userAgreement) && isAgreementVersion(required.privacy);
}
/** True when the caller still has to accept the current versions (unknown status counts as "not needed" here: bootstrap enforces it). */
export const needsAgreement = (status: AgreementStatus | null | undefined): boolean => Boolean(status && !status.upToDate);
/** Body for POST /api/backend/auth/agreements: always the versions the server says are required. */
export function acceptanceBody(status: AgreementStatus): AgreementAcceptance {
  if (!isAgreementVersion(status.required.userAgreement) || !isAgreementVersion(status.required.privacy)) throw new Error("Phiên bản văn bản không hợp lệ.");
  return { userAgreementVersion: status.required.userAgreement, privacyVersion: status.required.privacy, accepted: true };
}
/** BFF allowlist: exactly the three expected keys, valid versions and an explicit `accepted: true`. */
export function sanitizeAcceptance(value: unknown): AgreementAcceptance | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  if (keys.join(",") !== "accepted,privacyVersion,userAgreementVersion") return null;
  if (record.accepted !== true || !isAgreementVersion(record.userAgreementVersion) || !isAgreementVersion(record.privacyVersion)) return null;
  return { userAgreementVersion: record.userAgreementVersion, privacyVersion: record.privacyVersion, accepted: true };
}
/** Server error codes after which the onboarding screen re-reads the required versions. */
export const isAgreementRetryCode = (code: string | undefined): boolean => code === "agreement_required" || code === "agreement_version_outdated";

export const AGREEMENT_REQUIRED_MESSAGE = "Để tiếp tục, vui lòng đồng ý với Thỏa thuận người dùng và Thông báo quyền riêng tư.";
export const AGREEMENT_OUTDATED_MESSAGE = "Văn bản vừa được cập nhật. Vui lòng đọc lại và đồng ý với phiên bản mới.";
