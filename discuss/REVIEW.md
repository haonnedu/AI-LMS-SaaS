# Review và phản hồi

Mỗi yêu cầu ghi task và revision. Người yêu cầu đề xuất reviewer; người review tự ghi kết luận của mình.

## 2026-10-21 — BASE-02 / DB-02 — sửa lint/format migration 0002

- Người chuẩn bị: Codex theo yêu cầu người dùng; chưa có reviewer con người xác nhận nhận review.
- Task: [BASE-02 và DB-02 trong Core](../tasks/CORE.md); finding [D-01](2026-10-21-source-review.md).
- Revision: base `c99874481683692c84b58ac7ae99da87a31e4637` cộng migration local có Git blob `4e2b4b4cebe533ff7635660fcd434434f4ef3356`; chưa có commit/PR cho bản sửa.
- Phạm vi: xóa 2 import thừa, format lệnh tạo index; SQL, revision và upgrade/downgrade không đổi. Không có dependency/API/contract/workflow change.
- [Evidence và phạm vi commit](BASE-02-lint-format.md): lint/format pass, 16 tests pass, OpenAPI không drift, DB trống upgrade/repeat upgrade và readiness thật 200.
- Cần reviewer: xác nhận diff chỉ đổi import/format, xem evidence đúng revision và kiểm tra Foundation CI sau push. Không coi bản sửa này đã hoàn tất identity/RLS hoặc M0.
- Chưa kiểm chứng: GitHub CI trên SHA mới; chưa có người review chấp thuận. Các thiếu sót schema/roles/RLS vẫn mở.
- Kết luận reviewer / revision đã xem / ngày: **chưa có**; để reviewer tự bổ sung.

## Mẫu yêu cầu

```markdown
## YYYY-MM-DD — <TASK-ID> — <chủ đề>

- Người yêu cầu / reviewer đề xuất: <tên> / <người còn lại>
- Task: <link tracker>
- PR / commit cần review: <link hoặc SHA>
- Phạm vi: <behavior thay đổi; migration/contract/dependency impact>
- Acceptance cần kiểm tra: <điều kiện quan sát được>
- Evidence: <lệnh, exit code, môi trường; phân biệt mock và integration>
- Điểm cần tập trung: <rủi ro/câu hỏi cụ thể>
- Chưa kiểm chứng: <giới hạn và blocker>

### Phản hồi — <reviewer> — <ngày giờ>

- Revision đã xem: <SHA>
- Kết luận: <cần sửa / chấp thuận / cần thêm bằng chứng>
- Finding: <file:dòng, vấn đề, kết quả mong đợi>
- Kiểm tra đã thực hiện: <evidence hoặc chỉ đọc source>

### Xử lý phản hồi — <tác giả> — <ngày giờ>

- Finding đã xử lý / còn mở: <liên kết>
- Revision mới và kiểm tra bổ sung: <SHA/evidence>
- Yêu cầu reviewer xem lại: <phạm vi>
```

Trước khi chốt: acceptance đạt, tests phù hợp, migration/contract được xem xét, không rò secrets/dữ liệu, giới hạn evidence được ghi. Reviewer chấp thuận chưa tự đồng nghĩa task `done`; áp dụng đầy đủ [Definition of Done](../tasks/BACKLOG.md).
