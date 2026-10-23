# ADR 002: Quản lý Session, Token và Trust Boundary cho Eduvia

> Ngày: 2026-10-21. Trạng thái: Đề xuất (Task AUTH-02).

## 1. Ngữ cảnh
Sau khi chọn Identity Provider (ADR 001), Eduvia cần định nghĩa rõ cơ chế lưu trữ phiên làm việc giữa trình duyệt (Next.js frontend) và API backend (FastAPI), cũng như quy tắc bảo mật chống rò rỉ token, CSRF và revocation.

---

## 2. Mô hình Trust Boundary & Token Flow

1. **Browser ↔ Frontend (Next.js BFF / Route Handler):**
   - Trình duyệt không lưu Access Token hoặc Refresh Token của IdP trực tiếp trong `localStorage` hay `sessionStorage` để tránh XSS lấy cắp token.
   - Sử dụng HttpOnly, Secure, SameSite=Lax cookies để lưu session token / session ID phiên làm việc phía frontend nếu cần, hoặc chuyển tiếp thông qua Header Authorization an toàn.

2. **Frontend ↔ Backend (FastAPI):**
   - Mỗi request từ client gọi tới FastAPI đều kèm theo `Authorization: Bearer <JWT>`.
   - FastAPI middleware/dependency kiểm tra:
     - Chữ ký số của JWT (JWKS từ IdP).
     - Thời hạn (`exp`, `nbf`).
     - `iss` (Issuer) và `aud` (Audience) đúng cấu hình.

---

## 3. Threat Cases & Biện pháp giảm thiểu

| Mối đe dọa (Threat Case) | Biện pháp phòng ngừa (Mitigation) |
|---|---|
| **XSS (Cross-Site Scripting):** Kẻ tấn công chèn mã độc đánh cắp token. | Không lưu token nhạy cảm ở `localStorage`. Sử dụng HttpOnly cookies hoặc memory state an toàn. |
| **CSRF (Cross-Site Request Forgery):** Kẻ xấu ép trình duyệt gọi API. | Dùng token trong Header `Authorization` thay vì cookie thuần túy cho API state-changing, kèm cấu hình CORS chặt chẽ (`CORS_ORIGINS`). |
| **Token Replay / Stale Token sau khi Revoke:** User đăng xuất hoặc bị khóa tài khoản nhưng token chưa hết hạn. | Kết hợp kiểm tra trạng thái active của user/membership trong database hoặc cache ngắn hạn (Redis) tại backend cho các resource nhạy cảm. |


## Chốt triển khai — 2026-10-23

Next.js BFF dùng SDK Auth0 v4 và Redis sessionStore; cookie HttpOnly, SameSite=Lax, host-only, Secure khi HTTPS chỉ chứa session ID được bảo vệ. Session data/token mã hóa AES-256-GCM trong Redis bằng khóa riêng. Absolute 24 giờ, idle 2 giờ; access token RS256 5 phút, refresh rotation ở provider. Browser không nhận token; tắt `/auth/access-token`. Origin + session CSRF token bắt buộc trên mutation BFF. API chỉ nhận access token đúng audience, không nhận ID token hay header identity giả.

Refresh/session update/logout serialized bằng lock Redis; atomic update không tạo lại session đã xóa. Redis timeout/lỗi trả 503, không fallback mock. Backend kiểm active user/membership mỗi request; user bị khóa ở Auth0 hoặc JWT đã phát không đồng nghĩa thu hồi JWT ngay. Local `is_active=false` chặn request tiếp theo. [Runbook](../../deploy/auth0/README.md) ghi rõ lifetime token 5 phút cộng clock tolerance 30 giây và smoke còn thiếu.

## Better Auth transition — 2026-10-23

Next.js giữ vai trò BFF nhưng dùng Better Auth Redis sessions, opaque cookie và JWT plugin RS256 5 phút chỉ server-to-server. Public handler allowlist chặn token/get-session/link/unlink nội bộ; cookie cache tắt. FastAPI chọn verifier theo allowlist issuer rồi kiểm chữ ký; issuer không bao giờ cung cấp JWKS URL. Transfer proof có issuer/audience riêng và receipt transactional, không dùng access token thông thường làm bằng chứng chuyển. Auth0 SDK/config chỉ giữ trong giai đoạn xác minh tài khoản cũ. Xem runbook Better Auth và execution record mới.
