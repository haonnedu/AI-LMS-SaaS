# Review và phản hồi

Mỗi yêu cầu ghi task và revision. Người yêu cầu đề xuất reviewer; người review tự ghi kết luận của mình.

## 2026-10-22 — FE-02a — onboarding/workspace mock

- Người chuẩn bị: Codex theo yêu cầu người dùng, phía Duc; reviewer đề xuất: Hao (chưa xác nhận nhận review).
- Task/revision: [Core FE-02a](../tasks/CORE.md), branch `feat/fe-02-workspace-mock`; base `2379a6e5e70b5c65645880202cae6bab5b11ac8b` cộng diff/file mới chưa commit. Chưa có source SHA mới hoặc remote PR. Cập nhật SHA sau commit; reviewer phải xem revision đó, không duyệt chỉ theo base.
- Thay đổi: login thử đi qua onboarding, workspace mẫu gắn với từng auth generation, reuse/retry và bỏ kết quả cũ khi rời route/logout/expiry. Không có backend, migration, HTTP contract, dependency hay authorization change.
- Evidence và phạm vi commit: [FE-02a.md](../frontend/FE-02a.md); nội dung PR chuẩn bị tại [FE-02a-PR.md](../frontend/FE-02a-PR.md). Baseline lint/typecheck/build, 4 adapter tests, 14 backlog tests pass; review docs không phải lượt chạy lại.
- Cần tập trung: guard sau mỗi await/catch/finally, pending Promise reuse, session mới cùng user ID không kế thừa workspace cũ; onboarding chưa login không provisioning, preview vẫn truy cập được.
- Còn mở P2: visual gate chưa đạt vì capture sai so với DOM; frontend CI chưa gọi `test:workspace`. Đề nghị phối hợp workflow riêng; trong lúc chưa có CI step, reviewer chạy test thủ công. Không tự gán deadline hoặc xác nhận Hao đã nhận việc.
- Checklist visual: kiểm trực tiếp login/onboarding/dashboard ở 375×812 và 1440×900, chữ/nút không bị cắt, scroll/focus/logout truy cập được; lưu ảnh đáng tin cậy. Ảnh hiện có chỉ để chẩn đoán.
- Kết luận reviewer / SHA đã xem / ngày / kiểm tra đã chạy: **chưa có**; để Hao tự bổ sung. Chưa tuyên bố acceptance đầy đủ hoặc sẵn sàng merge.

## 2026-10-21 — BASE-01 / BASE-05 — tooling và CI

- Người chuẩn bị: Codex theo yêu cầu người dùng; branch `fix/tooling-ci`, base `302762b` cộng diff chưa commit.
- Phạm vi: setup tương thích PowerShell 5.1/7; verifier theo Alembic head và schema identity; regression tests và CI Windows/Linux.
- Evidence và hành động cần review: [BASE-tooling-ci.md](BASE-tooling-ci.md).
- Cần reviewer xác nhận: setup không thay môi trường trong CheckOnly; migration chỉ chạy trên DB tạm; timeout/cleanup/report an toàn; CI artifact không chứa env file.
- Reviewer con người / SHA duyệt: chưa có. CI của branch mới chưa chạy trước khi push; không coi CI xanh của base là bằng chứng cho diff này.

## Cập nhật yêu cầu lint/format bên dưới

Bản sửa đã merge qua PR #1; [Foundation CI tại 302762b](https://github.com/haonnedu/AI-LMS-SaaS/actions/runs/39560321514) xanh. Yêu cầu bên dưới là bản ghi trước commit; không còn chờ push bản sửa lint. Không tự ghi nhận reviewer con người nếu chưa có thông tin review cụ thể.

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

2026-10-23 — Đề xuất Hào review [retirement diff](2026-10-23-auth0-retirement.md): single-issuer verifier, cleanup guards/transaction, migration 0008 và session boundaries. Chưa có reviewer signoff.

2026-10-23 — Đề xuất Hào review Compose loopback/profile isolation và native smoke không reset dữ liệu; chưa reviewer signoff. [Evidence](2026-10-23-local-auth-mailpit.md).
