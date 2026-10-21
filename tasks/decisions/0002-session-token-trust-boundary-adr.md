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
