# Chiến lược Vận hành, Môi trường & Bảo mật (Task OPS-01)

> Ngày: 2026-10-21. Trạng thái: Đề xuất đặc tả kỹ thuật.

## 1. Phân tách Môi trường (Environment Separation)
Eduvia quy định rõ 3 môi trường riêng biệt:
1. **Development (Dev):** Môi trường chạy cục bộ trên máy lập trình viên (`docker compose`, `localhost`, SQLite/PostgreSQL local), không chứa dữ liệu thực tế hay API keys thật.
2. **Staging:** Môi trường kiểm thử tích hợp gần giống Production, dùng để chạy E2E tests, load tests và review tính năng trước khi release.
3. **Production (Prod):** Môi trường vận hành chính thức phục vụ các trường học và giáo viên pilot.

---

## 2. Quản lý Secrets & Cấu hình
- **Tuyệt đối không** hardcode API keys, database passwords, hoặc secret tokens vào trong source code hay repository git.
- Sử dụng biến môi trường (`.env` trên dev, các secret manager bảo mật trên cloud cho staging/prod).
- Chạy kiểm tra định kỳ (Secret Scan baseline) để đảm bảo không có credentials nào bị lọt vào commit lịch sử của git.

---

## 3. Ngân sách & Giới hạn tài nguyên (Budget & Quota)
- Quản lý hạn mức gọi LLM (AI Provider) thông qua hệ thống định mức theo workspace và execution ID để tránh vượt ngân sách hoặc bị lạm dụng tài nguyên.
