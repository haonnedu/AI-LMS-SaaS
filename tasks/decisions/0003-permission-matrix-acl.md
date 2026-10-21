# Permission Matrix & Access Control (Task ACL-01)

> Ngày: 2026-10-21. Trạng thái: Đề xuất & Đặc tả kỹ thuật.

## 1. Nguyên tắc cốt lõi (Core Principles)
- **Least Privilege (Quyền tối thiểu mặc định):** Mọi request đọc/ghi dữ liệu đều bắt buộc phải qua tầng xác thực tenant và quyền hạn; mặc định từ chối (Deny by Default) nếu không có grant hợp lệ.
- **Tenant Isolation (Cách ly dữ liệu):** Dữ liệu workspace cá nhân, workspace trường học và không gian tự học của học sinh được tách biệt rõ ràng. Không tự động chia sẻ dữ liệu chéo giữa các workspace nếu không có hành động cấp quyền rõ ràng (explicit grant).

---

## 2. Permission Matrix (Bảng ma trận quyền hạn đề xuất)

| Vai trò / Đối tượng | Personal Workspace | School Workspace | Student Independent Self-Study |
|---|---|---|---|
| **Global User (Chưa gia nhập trường)** | Toàn quyền sở hữu tài liệu cá nhân, lớp học riêng. | Không có quyền truy cập. | Sở hữu tiến độ học tập và lịch sử tự học cá nhân. |
| **School Teacher** | Giữ quyền sở hữu tài liệu cá nhân độc lập. | Được giao phân công giảng dạy (Teaching Assignments) trong trường; soạn và nộp duyệt học liệu. | Không tự động chia sẻ tiến độ tự học cá nhân cho nhà trường. |
| **School Admin / Giáo vụ** | Giữ quyền cá nhân riêng. | Quản lý roster giáo viên, tổ chuyên môn, phân công giảng dạy, báo cáo và duyệt tài liệu được phân quyền. | Không có quyền đọc answer keys hoặc hồ sơ tự học cá nhân của học sinh. |
| **Enrolled Student** | Không áp dụng. | Tham gia lớp học được gán, làm bài kiểm tra và nhận kết quả/feedback được release. | Chủ động học theo lộ trình cá nhân, làm bài thi thử (mock exam) và xem diagnostic của chính mình. |

---

## 3. Thực thi kỹ thuật (Enforcement Strategy)
1. **Database Level (RLS):** Sử dụng PostgreSQL Row Level Security (`WORKSPACE_ID` + `USER_ID` checks) kết hợp biến session `app.workspace_id` và `app.user_id` để ngăn chặn rò rỉ dữ liệu ngay từ tầng cơ sở dữ liệu.
2. **Application Level (FastAPI Dependencies):** Các endpoint API đều yêu cầu dependency kiểm tra xem user hiện tại có active membership trong workspace đang yêu cầu hay không.
