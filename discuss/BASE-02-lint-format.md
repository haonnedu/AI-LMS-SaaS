# BASE-02 / DB-02 — bàn giao sửa lint/format migration 0002

> Cập nhật sau merge: bản sửa đã vào main qua PR #1; [Foundation CI tại 302762b](https://github.com/haonnedu/AI-LMS-SaaS/actions/runs/39560321514) pass. Các câu "chưa commit/push" bên dưới là lịch sử tại thời điểm bàn giao. Commit 302762b còn bỏ SQL comments nên blob hiện tại khác blob local cũ. Đợt tooling tiếp theo xem [bàn giao mới](BASE-tooling-ci.md).

Người ghi: Codex, 2026-10-21 13:57 +07:00. Task chính thức: [Core tracker](../tasks/CORE.md). Finding liên quan: [D-01](2026-10-21-source-review.md). Đây là evidence kỹ thuật chuẩn bị commit/review, chưa phải nghiệm thu task.

## Revision và thay đổi

- Base commit: `c99874481683692c84b58ac7ae99da87a31e4637`.
- File code duy nhất của bản sửa: [migration 0002](../backend/migrations/versions/0002_identity_and_workspaces.py).
- Git blob của migration đã kiểm tra: `4e2b4b4cebe533ff7635660fcd434434f4ef3356` (`git hash-object backend/migrations/versions/0002_identity_and_workspaces.py`).
- SHA256 raw bytes tại máy kiểm chứng: `0868a6628693b14efc37cddf124a694ccb1073b84510224365e15177dd44b45e`. Raw hash có thể khác trên checkout dùng newline khác.
- Xóa import `sqlalchemy` và `sqlalchemy.dialects.postgresql` không được sử dụng. Format hai lệnh tạo index; chuỗi dài được tách bằng Python adjacent string literals, giá trị SQL giữ nguyên.
- AST sau khi loại import giống bản HEAD; revision/down_revision, SQL và logic upgrade/downgrade không thay đổi. Không sửa API, schema, dependency/lock hoặc workflow.

## Kết quả kiểm chứng

Môi trường local: Windows, backend virtualenv riêng Python 3.12.15, Ruff 0.17.1 từ dependency lock hiện có. Các command dưới chạy từ `backend/`, trừ khi ghi khác.

| Kiểm tra | Lệnh/cách thực hiện | Kết quả |
|---|---|---|
| Lint | `.venv\Scripts\python.exe -m ruff check .` | Exit 0, all checks passed |
| Format | `.venv\Scripts\python.exe -m ruff format --check .` | Exit 0, 26 files already formatted |
| Unit tests | `.venv\Scripts\python.exe -m pytest -q` | Exit 0, 16 passed; 1 deprecation warning về TestClient/httpx, không đổi dependency để xử lý warning |
| Migration semantics | Parse HEAD và file sửa bằng `ast.parse`; loại node import rồi so sánh `ast.dump` | Exit 0, AST còn lại giống nhau; bao gồm SQL và revision |
| OpenAPI | `.venv\Scripts\python.exe scripts/export_openapi.py ../tmp/ci-lint-openapi.json`; so sánh với `git show HEAD:contracts/openapi.json` | Exit 0; nội dung khớp sau chuẩn hóa CRLF/LF, không có drift |
| Whitespace | `git diff --check` từ repo root | Exit 0 |

Unit tests ở trên không phải bằng chứng RLS hoặc migration integration. Integration thật được chạy riêng như phần dưới.

## Integration PostgreSQL / Redis thật

Lượt kiểm chứng dùng script tạm riêng, không dùng `scripts/verify-m0.py` đang giả định bootstrap cũ. Script tạm nằm trong `tmp/`, không đưa vào commit này. Phần kết quả cần chia sẻ được lưu ở đây; không phụ thuộc link tới artifact local bị ignore.

- Compose project: `eduvia-ci-lint-20261021065525-8b55b6`; API loopback port `62260`. Không publish cổng DB/Redis.
- Backend image được build từ source hiện tại; PostgreSQL pgvector và Redis dùng đúng image digest đã khóa trong Compose của repo.
- Dùng DB/volume mới, credential ngẫu nhiên cho lượt chạy, không tái sử dụng volume hay cấu hình stack người dùng. Log không lưu giá trị credential.
- Các lệnh Compose bên dưới đều dùng `-p <project-trên> -f <compose-tạm>`; không chạy trên default project.

| Bước | Lệnh/kiểm tra | Kết quả |
|---|---|---|
| Build backend | `docker compose ... build api` | Exit 0 |
| Start dependencies | `docker compose ... up -d --wait db redis` | Exit 0 |
| DB trống | Query schema `edu` trước migration bằng `psql -v ON_ERROR_STOP=1 -Atc` | Exit 0; count = 0 |
| Upgrade | `docker compose ... run --rm migrate` chạy `alembic upgrade head` | Exit 0 |
| Revision | `SELECT version_num FROM alembic_version` | `0002_identity_and_workspaces` |
| Tables | `SELECT tablename FROM pg_tables WHERE schemaname='edu' ORDER BY tablename` | `users`, `workspace_members`, `workspaces` |
| Extension | `SELECT count(*) FROM pg_extension WHERE extname='vector'` | 1 |
| Upgrade lặp | Chạy lại service migrate với `alembic upgrade head` | Exit 0 |
| API | `docker compose ... up -d --no-build --wait api`; GET `/health/ready` | HTTP 200; PostgreSQL và Redis đều `ok` |
| Cleanup | `docker compose ... down --volumes --remove-orphans`; xóa đúng image riêng của lượt chạy | Exit 0; không còn stack kiểm chứng |

Kết quả readiness:

```json
{"status":"ready","checks":{"postgres":"ok","redis":"ok"}}
```

Integration hoàn tất lúc **2026-10-21 13:55:45 +07:00**, result `passed`, cleanup `passed`. Đây không phải downgrade, DB role, tenant isolation hoặc security acceptance; các mục đó vẫn cần task/check riêng.

## Chuẩn bị commit và review

1. Phạm vi code của bản sửa chỉ là migration nêu trên. Có thể đưa thư mục `discuss/` vào commit tài liệu riêng để chia sẻ quy tắc, snapshot và evidence; không trộn các script M0 chưa hoàn tất.
2. Giữ ngoài bản sửa CI: `scripts/setup.ps1`, `scripts/smoke-test.mjs`, `.github/pull_request_template.md`, `scripts/verify-m0.py`. Không reset/xóa chúng và không dùng `git add .`.
3. Stage theo đường dẫn rõ ràng rồi kiểm tra `git diff --cached --name-only` và `git diff --cached --check` trước commit.
4. Gợi ý commit code: `fix: resolve identity migration lint and formatting`; commit tài liệu: `docs: add coworker discussion and CI fix evidence`.
5. Sau push, ghi SHA mới, link Foundation run và kết quả reviewer vào [REVIEW.md](REVIEW.md). Chỉ khép D-01 khi backend/frontend/containers trên SHA chứa bản sửa đều pass.

Hiện **chưa commit/push**, chưa có reviewer chấp thuận và chưa có GitHub run của bản sửa. [Run cũ](https://github.com/haonnedu/AI-LMS-SaaS/actions/runs/39556937893) vẫn là kết quả thất bại của base commit; rerun nó không tự bao gồm thay đổi local.

Các mục D-02..D-07 vẫn mở; không đổi task status hoặc tuyên bố M0/DB-02 done từ bản sửa định dạng này. Frontend/container checks của base đã pass; không lặp lại frontend local vì code frontend không thay đổi trong bản sửa.
