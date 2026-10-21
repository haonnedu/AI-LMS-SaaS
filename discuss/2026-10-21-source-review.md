# Đối chiếu source — 2026-10-21

Người ghi: Codex. Snapshot tham chiếu: `c99874481683692c84b58ac7ae99da87a31e4637`. Đây là kết quả kiểm tra để hai thành viên thảo luận; không phải nghiệm thu hoặc phân công mới. Khi code thay đổi, bổ sung revision/kết quả xử lý thay vì coi các finding luôn còn đúng.

## Bằng chứng tại snapshot

- [Foundation CI](https://github.com/haonnedu/AI-LMS-SaaS/actions/runs/39556937893): frontend và container build pass; backend fail lint nên các bước test/migration/readiness sau đó bị skip.
- [MCP CI](https://github.com/haonnedu/AI-LMS-SaaS/actions/runs/39556937805): pass.
- Kiểm tra local Python 3.12.15: backend `python -m pytest -q` đạt 16 passed; MCP đạt 61 passed, 1 skipped. Backend lint có 5 lỗi; format-check có 1 file cần format.
- Các unit test backend không thay thế migration/RLS integration tests. Lượt Docker trước đó thuộc commit `c89b185`, không nghiệm thu migration mới.

## Các mục đề nghị xử lý

| Mục | Task liên quan | Vấn đề / điều kiện xác nhận đã xử lý |
|---|---|---|
| D-01 | BASE-02, DB-02 | Tại snapshot có import thừa/sai thứ tự và dòng dài. Đã sửa local, lint/format/tests và migration/readiness thật pass; xem [bàn giao bản sửa](BASE-02-lint-format.md). Chờ commit/push và Foundation CI trên SHA mới; chưa khép finding. |
| D-02 | DB-01 | Chưa thấy tạo/tách migrator/runtime roles; Compose dùng cùng DATABASE_URL cho migrate/API/worker. Cần role hạn chế và evidence grants bằng PostgreSQL thật. |
| D-03 | DB-02, DATA-01 | Schema thiếu issuer trong identity, ràng buộc personal workspace/owner, CHECK cho type/role/status, audit tối thiểu và migration tests. Review thêm unique email và downgrade CASCADE trước mở rộng. |
| D-04 | DB-03..05 | Chưa có verified transaction-local actor/workspace context, RLS/FORCE RLS hoặc tests tenant A/B, revoke, pool reuse. Chưa mở API tenant cho đến khi các gate đạt. |
| D-05 | AUTH-01/02, ACL-01, DATA-01 | [Decision records](../tasks/decisions/) đang ghi đề xuất, provider còn nhiều lựa chọn; tracker ghi done. Cần khóa quyết định, bổ sung chi tiết và reviewer/evidence trước nghiệm thu. |
| D-06 | SCOPE-01, OPS-01 | Pilot và ngân sách/region chưa chốt theo người dùng. Xem [Q-01/Q-02](QUESTIONS.md); không ký duyệt thay. |
| D-07 | BASE, DOC-01 | [DEVELOPMENT.md](../DEVELOPMENT.md) và [DATABASE.md](../DATABASE.md) vẫn mô tả chỉ bootstrap/empty UI; cần cập nhật đúng migration và 11 trang mẫu hiện có. |

## Phần sản phẩm chưa triển khai tại snapshot

Backend chỉ có health endpoints. Chưa có auth/session thật, provisioning/workspace API, tenant authorization, upload/RAG/AI generation, enrollment/assignment/submission/grading. Frontend dùng dữ liệu mẫu; worker mới có ping. Đây là phạm vi roadmap, không tự động là lỗi cần làm toàn bộ trong M0.

## Phần local còn dở cần tách khi review

Tại lúc kiểm tra, `scripts/setup.ps1`, `scripts/smoke-test.mjs`, `.github/pull_request_template.md` và `scripts/verify-m0.py` là thay đổi local từ phiên trước, chưa commit; không tính là phần đã pull/merge. Script verify hiện dành cho bootstrap cũ, cần cập nhật acceptance trước khi dùng với migration 0002.

## Cách tiếp tục

Người nhận chọn task trong tracker, ghi owner/status tại đó, rồi cập nhật file cá nhân và mở yêu cầu review theo revision cụ thể. Không có owner/reviewer mới nào được tự gán qua báo cáo này.

## Cập nhật sau snapshot — 2026-10-21 13:57 +07:00

Codex đã sửa riêng import/format migration 0002, giữ nguyên AST ngoài import và toàn bộ SQL/revision. Backend lint, format-check, 16 unit tests, contract comparison và PostgreSQL/Redis integration đều pass. Evidence integration này áp dụng cho source `c998744` cộng bản sửa migration local, không phải lượt Docker bootstrap cũ.

[Bản ghi bàn giao](BASE-02-lint-format.md) lưu kết quả cần thiết ngay trong repo để co-worker không cần thư mục `tmp/` trên máy tác giả. Các mục D-02 đến D-07 chưa được xử lý bởi bản sửa lint/format. Task tracker không đổi; chưa có review chấp thuận hoặc CI xanh của SHA chứa bản sửa.
