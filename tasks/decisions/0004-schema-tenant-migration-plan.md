# Review Schema Tenant, Composite FK & Migration Plan (Task DATA-01)

> Ngày: 2026-10-21. Trạng thái: Đề xuất đặc tả kỹ thuật chuẩn bị cho M1 (DB-01 đến DB-05).

## 1. Mục tiêu
Chuẩn bị chi tiết thiết kế schema cơ sở dữ liệu cho các bảng cốt lõi (`users`, `workspaces`, `workspace_members`) tuân thủ tuyệt đối quy tắc cách ly tenant, khóa ngoại tổng hợp (composite foreign keys) và tính toàn vẹn dữ liệu.

---

## 2. Quy chuẩn thiết kế Schema (Schema Conventions)

1. **Global Users & Local Workspaces:**
   - Bảng `users` lưu danh tính toàn cục (ID, email, provider subject, created_at).
   - Bảng `workspaces` lưu không gian làm việc (cá nhân hoặc trường học).
   - Bảng `workspace_members` liên kết user với workspace kèm vai trò (`owner`, `admin`, `teacher`, `student`) và trạng thái `status` (`active`, `suspended`, `departed`).

2. **Composite Tenant Foreign Keys:**
   - Mọi bảng dữ liệu thuộc workspace (như tài liệu, lớp học, bài kiểm tra) phải có cột `workspace_id`.
   - Các bảng liên quan phụ thuộc (ví dụ phân công giảng dạy, bài nộp) phải dùng **Composite Foreign Key** trỏ tới `(workspace_id, entity_id)` của bảng cha thay vì chỉ trỏ đơn lẻ `entity_id`, nhằm đảm bảo không thể liên kết chéo dữ liệu giữa các workspace khác nhau.

3. **Row Level Security (RLS):**
   - Bật RLS trên toàn bộ bảng dữ liệu nhạy cảm thuộc schema `edu`.
   - Sử dụng function PostgreSQL kiểm tra biến `current_setting('app.workspace_id', true)` và `current_setting('app.user_id', true)` để tự động lọc dữ liệu theo đúng ngữ cảnh request.

4. **Migration Plan:**
   - Migration tiếp theo (`0002_identity_and_workspaces.py`) sẽ tạo các bảng này, thiết lập indexes, RLS policies và phân tách migrator/runtime roles ở task `DB-01` & `DB-02`.
