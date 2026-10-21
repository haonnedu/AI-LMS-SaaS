# Discuss — phối hợp công việc Eduvia

Thư mục dùng để Hao Nguyen và Duc Quach trao đổi, bàn giao và review công việc qua Git. Ghi theo task ID để người còn lại tìm được code, bằng chứng và việc cần phản hồi.

## Mở file nào?

| File | Dùng khi nào |
|---|---|
| [HAO.md](HAO.md) | Hao ghi cập nhật sau phiên làm việc và bàn giao cho Duc |
| [DUC.md](DUC.md) | Duc ghi cập nhật sau phiên làm việc và bàn giao cho Hao |
| [REVIEW.md](REVIEW.md) | Chuẩn bị yêu cầu review và ghi phản hồi của reviewer |
| [QUESTIONS.md](QUESTIONS.md) | Theo dõi câu hỏi/blocker cần người có trách nhiệm quyết định |
| [TASK_TEMPLATE.md](TASK_TEMPLATE.md) | Mẫu tạo file trao đổi riêng cho task có nhiều chi tiết |
| [2026-10-21-source-review.md](2026-10-21-source-review.md) | Các điểm còn thiếu tại commit `c998744`, để hai người xử lý tiếp |
| [BASE-02-lint-format.md](BASE-02-lint-format.md) | Bản sửa migration 0002, evidence local/integration và phạm vi chuẩn bị commit |
| [BASE-tooling-ci.md](BASE-tooling-ci.md) | Sửa setup/verifier, regression tests và CI; giới hạn kiểm chứng của đợt tiếp theo |

## Quy tắc sử dụng

1. Trước khi nhận việc, đọc [backlog](../tasks/BACKLOG.md) và tracker tương ứng: [Core](../tasks/CORE.md), [School](../tasks/SCHOOL.md), [Student](../tasks/STUDENT.md), [OMR/Billing](../tasks/OMR_BILLING.md).
2. **Owner/status task chỉ cập nhật tại tracker.** Discuss giữ nội dung trao đổi, không tạo board trạng thái thứ hai. Mỗi ghi chú phải dẫn về task; không sao chép danh sách `todo/done` vào các file cá nhân.
3. Mỗi người một task chính đang làm. Ghi phạm vi file/migration/contract sắp sửa và thống nhất trước khi cùng chạm một khu vực. Đặt tên branch theo thống nhất của nhóm; đợt tooling/CI dùng `fix/tooling-ci`, không thêm prefix `codex/` theo yêu cầu người dùng.
4. Cuối phiên, cập nhật file cá nhân: ngày giờ theo Asia/Ho_Chi_Minh, task, commit/branch/PR, thay đổi, kiểm tra, phần còn thiếu và hành động cần người kia làm. Đặt mục mới nhất lên đầu.
5. Khi cần bàn sâu, copy mẫu thành `<TASK-ID>-<slug>.md`, liên kết từ file cá nhân. Giữ một file thảo luận cho cùng chủ đề, thêm phản hồi có ngày/tên thay vì ghi đè ý kiến người khác.
6. Review phải trỏ tới revision cụ thể. Sau sửa code, reviewer xem lại revision mới trước khi chốt; không coi đề nghị review là đã được duyệt. Link kết quả review/evidence từ execution record trong tracker.
7. Quyết định kiến trúc được chấp thuận cập nhật vào [decision records](../tasks/decisions/); ghi chú discuss chỉ dẫn link. Pilot/ngân sách cần người có trách nhiệm duyệt, không tự điền hoặc ký thay.

Không lưu secrets, file `.env`, token, URL chứa credential hoặc dữ liệu học sinh. Không tự gán việc/ngày hẹn cho người khác; đề xuất phải được người nhận xác nhận. Git chỉ chia sẻ ghi chú sau commit/push/pull, không tự gửi thông báo hay khóa task.
