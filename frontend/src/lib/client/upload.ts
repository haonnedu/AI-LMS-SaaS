// Pure upload helpers (no DOM access) so they can be unit tested.
export const ALLOWED_UPLOAD_TYPES: Record<string, string> = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  txt: "text/plain",
};
export const UPLOAD_ACCEPT = ".pdf,.docx,.txt";
export function uploadContentType(fileName: string): string | null {
  const ext = fileName.includes(".") ? fileName.split(".").pop()!.toLowerCase() : "";
  // Extension decides: browsers often report "" or odd types for docx/txt.
  return ALLOWED_UPLOAD_TYPES[ext] ?? null;
}
export function buildUploadHeaders(file: { name: string }, csrfToken: string, idempotencyKey?: string): Record<string, string> | null {
  const contentType = uploadContentType(file.name);
  if (!contentType) return null;
  return {
    "Content-Type": contentType,
    "X-File-Name": encodeURIComponent(file.name),
    "X-Rights-Attested": "true",
    "X-CSRF-Token": csrfToken,
    ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
  };
}
