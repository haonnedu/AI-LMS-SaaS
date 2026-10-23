// TODO replace with generated types after api:generate
export type ConsentStatus = "unknown" | "not_required" | "pending" | "granted" | "revoked";
export type ConsentMethod = "paper_school" | "self_adult";
export type PrivacyKind = "export" | "erasure";

export type ConsentRecord = { id: string; method: ConsentMethod | string; policyVersion: string; grantedAt: string | null; revokedAt: string | null };
export type ClassConsentItem = { studentId: string; displayName: string; birthYear: number | null; consentStatus: ConsentStatus; consents: ConsentRecord[] };
export type ConsentSummary = { granted: number; pending: number; notRequired: number; revoked: number; unknown: number };
export type ClassConsents = { items: ClassConsentItem[]; summary: ConsentSummary };

export type RecordConsentBody = { method: ConsentMethod; guardianName?: string; guardianContact?: string; evidenceNote?: string };
export type ConsentLinkCreated = { token: string; expiresAt: string };

export type PrivacyRequest = { id: string; kind: PrivacyKind; status: string; downloadUrl?: string | null; downloadExpiresAt?: string | null };
export type PrivacyRequestCreated = { request: { id: string; kind: PrivacyKind; status: string }; job?: unknown };

export type StudentConsentItem = { workspaceId: string; className: string; consentStatus: ConsentStatus; consentRequired: boolean; policyVersion: string };
/** Decision 0009: "signup" (default) = no guardian consent; "guardian" = the optional 0016 flow. */
export type ConsentMode = "signup" | "guardian";
export type StudentConsentStatus = { items: StudentConsentItem[]; mode?: ConsentMode; consentAge?: number };

export type PublicConsentLink = { studentDisplayName: string; workspaceName: string; policyVersion: string; expiresAt: string };
export type PublicConsentSubmit = { guardianName: string; guardianContact: string; agree: true };
