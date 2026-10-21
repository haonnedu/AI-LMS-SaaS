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
