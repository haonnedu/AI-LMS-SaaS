# ADR 001: Lựa chọn Identity Provider (IdP) cho Eduvia

> Ngày: 2026-10-21. Trạng thái: Đề xuất (Task AUTH-01).

## 1. Ngữ cảnh và Yêu cầu
Eduvia cần hệ thống xác thực (Authentication) đáp ứng các tiêu chí sau:
- Hỗ trợ chuẩn OIDC/OAuth2 và JWT xác thực phía server-side.
- Định danh người dùng toàn cục (Global User Identity) qua stable subject ID (`sub`) và issuer (`iss`), cho phép một user tham gia nhiều trường hoặc workspace khác nhau mà không bị trùng lặp tài khoản.
- Chi phí tối ưu cho giai đoạn pilot (10–20 giáo viên) và dễ mở rộng khi thương mại hóa.
- Cho phép chạy môi trường dev cục bộ dễ dàng (không phụ thuộc dịch vụ bên ngoài bắt buộc nếu mất kết nối mạng ở dev).

---

## 2. Các phương án xem xét

### Phương án A: Tự xây dựng hệ thống Auth riêng (Custom Auth Service)
- **Ưu điểm:** Kiểm soát hoàn toàn database, bảng `users`, mã hóa password bcrypt.
- **Nhược điểm:** Phải tự làm cơ chế quản lý session, reset password, OAuth social login (Google, Microsoft cho trường học), bảo mật chống tấn công brute-force, CSRF phức tạp. Tốn thời gian phát triển core business.

### Phương án B: Managed IdP (Auth0 / Supabase Auth / Clerk)
- **Ưu điểm:** Sẵn giao diện login, hỗ trợ sẵn OIDC/OAuth, quản lý token, session và bảo mật chuẩn công nghiệp.
- **Nhược điểm:** Chi phí scale theo số lượng active users (MAU) khi sang production; cấu hình phụ thuộc bên thứ ba.

### Phương án C: Kết hợp chuẩn OIDC / FastAPI Security + Supabase Auth hoặc Keycloak (Hybrid / Managed Auth)
- **Ưu điểm:** Tận dụng managed service cho production/pilot để tiết kiệm thời gian, đồng thời backend FastAPI chỉ nhận Bearer JWT, kiểm tra `iss`, `sub`, và ánh xạ vào bảng `users` cục bộ của Eduvia một cách độc lập.

---

## 3. Quyết định đề xuất

Chọn **Phương án C (Managed OIDC Provider / Supabase Auth hoặc Auth0 kết hợp FastAPI JWT Middleware)**:
1. **Issuer/Subject Binding:** Backend FastAPI xác thực JWT dựa trên `iss` và `sub` chuẩn OIDC. Không tin tưởng bất kỳ thông tin user định danh nào do client gửi lên ngoài token đã được verify chữ ký số.
2. **Local Provisioning:** Khi token hợp lệ lần đầu, backend tự động khởi tạo bản ghi trong bảng `users` cục bộ theo cơ chế idempotent (dựa trên stable subject ID).
3. **Dev Mode:** Hỗ trợ mode phát triển giả lập token (mock token) để dev không có mạng hoặc chưa cấu hình IdP bên ngoài vẫn chạy được toàn bộ test suite.


## Chốt triển khai — 2026-10-23

Theo yêu cầu trực tiếp của người dùng sau bàn giao từ Hào: dùng **Auth0 Database Connection + Universal Login**, email/mật khẩu, tự đăng ký và bắt buộc xác minh email. Google/social login không thuộc slice này. Password/verification/reset do Auth0 quản lý; Eduvia định danh theo `(issuer, subject)`, không gộp email. Ban đầu chưa có tenant; sau đó đã setup tenant development và smoke Auth0/email thật trên local. Người dùng cân nhắc chi phí rồi xác nhận giữ Auth0; chưa xác nhận gói production hoặc email provider production. [Runbook](../../deploy/auth0/README.md), [evidence](../../discuss/2026-10-23-auth-implementation.md). Quyết định này thay các lựa chọn provider còn mở phía trên; chưa phải xác nhận reviewer hay nghiệm thu production.

## Thay thế quyết định — Better Auth, 2026-10-23

Người dùng chốt chuyển hoàn toàn khỏi Auth0 sang Better Auth self-hosted, email/password + Google và Account Center. Eduvia nay quản lý auth database/password hashes qua thư viện chính thức, SMTP và cập nhật bảo mật; không tự viết crypto password. Giữ Auth0 tạm thời chỉ cho chuyển dữ liệu có xác thực hai phía. Không implicit/email-only linking; giữ UUID/workspace và chặn gộp hai user đã tồn tại. Quyết định Auth0 phía trên là lịch sử checkpoint, không còn mục tiêu cuối. [Runbook](../../deploy/better-auth/README.md), [execution evidence](../../discuss/2026-10-23-better-auth-account-center.md). Chưa nghiệm thu production/cutover.
