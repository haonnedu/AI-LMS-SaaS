## 2026-10-24 — PILOT-05 consent/xóa/xuất dữ liệu + văn bản pháp lý nháp — bàn giao

- Tác giả: Hao Nguyen (3 agent)
- Task / trao đổi chi tiết: [Core tracker](../tasks/CORE.md) (record đợt 6), [docs/legal/lawyer-brief.md](../docs/legal/lawyer-brief.md) để gửi luật sư
- Branch / commit / PR: `feat/privacy-consent` stack trên `feat/m5-m6-ui-m7-pilot-readiness`; migration `0016_privacy_consent`. Chưa mở PR.
- Đã thay đổi: xem record đợt 6. Hai số quan trọng trong `backend/.env`: `PRIVACY_CONSENT_AGE` (16) và `PRIVACY_POLICY_VERSION` (`2026-10-draft`); đổi version khi văn bản được duyệt.
- Kiểm chứng: backend 1125 passed / 45 skipped; frontend lint/typecheck/build + 58 unit tests.
- Chưa kiểm chứng: SQL 0016 trên PostgreSQL; browser; `erase_self` với Better Auth (cần Duc: xóa `auth.user` + revoke session khi user bị erase).
- Đề nghị Duc: nối `edu.erase_self` với Better Auth (xóa `auth.user`, `session_revocations`); review rate limit public `/v1/public/consent-links`.
- Hao: gửi `docs/legal/lawyer-brief.md` + `privacy-notice.md` + `guardian-consent.md` cho luật sư; sau khi duyệt đổi `PRIVACY_POLICY_VERSION`.

## 2026-10-23 23:30 +07:00 — Đợt 3–5: RAG, authoring, exams, assessment, UI, M7 — bàn giao cho Duc review

- Tác giả: Hao Nguyen (agent thực hiện theo chỉ đạo, 11 work package qua 3 đợt)
- Task / trao đổi chi tiết: [Core tracker](../tasks/CORE.md) (3 execution record 2026-10-23 đợt 3/4/5), [threat model](../tasks/decisions/0007-threat-model-pilot.md), [privacy](../tasks/decisions/0008-privacy-consent-retention.md), [release checklist](../deploy/CHECKLIST-release.md)
- Branch / commit / PR: stack 4 branch, mỗi branch một PR để review theo phần: `feat/m2-m5-know-lean-slice` → `feat/m3-rag-m4-authoring-foundation` → `feat/m4-generation-m5-m6-assessment` → `feat/m5-m6-ui-m7-pilot-readiness`. Đã push, chưa mở PR (gh chưa đăng nhập; Hao mở trên web).
- Đã thay đổi: migrations 0009–0015 (classes, jobs/storage, knowledge, retrieval, authoring, exams, assessment); router đầy đủ `/v1`; worker jobs; frontend dashboard giáo viên (lớp, tài liệu, thư viện, soạn bài, câu hỏi, ma trận, đề, giao bài, kết quả) và `/student/*` làm bài; M7 artifacts (E2E skeleton, QA gates, runbooks, alerts, restore drill, checklist).
- Kiểm chứng: backend 999 passed / 37 skipped; frontend lint/typecheck/build, 51 unit tests; OpenAPI/generated types không drift.
- Chưa kiểm chứng / việc còn lại: toàn bộ SQL 0009–0015 chưa chạy trên PostgreSQL thật (CI của PR đầu là lần đầu); UI chưa chạy browser; provider AI/embedding thật; PILOT-03/08.
- Đề nghị Duc: review theo thứ tự PR; ưu tiên `workspace_access.py`, 25 SECURITY DEFINER (liệt kê trong quyết định 0007), migration 0015 phía học sinh; chạy integration bằng `compose.auth-test.yaml` + `AUTH_TEST_DATABASE_URL` trên máy có Docker.
- Đề xuất phiên tiếp theo: chốt 5 quyết định treo (embedding model, cấu trúc đề, pháp lý NĐ13, ngưỡng eval, pypdf/font PDF) rồi chạy stack đầy đủ và E2E.

## 2026-10-23 18:30 +07:00 — M2 lean + CLASS-01..04 + KNOW-01..05 — bàn giao cho Duc review

- Tác giả: Hao Nguyen (code do agent thực hiện theo chỉ đạo, 5 work package song song)
- Task / trao đổi chi tiết: [Core tracker](../tasks/CORE.md) (execution record 2026-10-23 cuối file), [review M1 nháp](REVIEW.md)
- Branch / commit / PR: working tree trên `main` sau `5f05030`, chưa commit/push/PR.
- Đã thay đổi: `backend/app/api/workspace_access.py` (BE-05 dùng chung); migrations 0009 classes, 0010 jobs/storage/usage, 0011 knowledge; router classes/documents/jobs/knowledge; worker `app.tasks.jobs`; MinIO trong compose; frontend `/dashboard/classes`, `/dashboard/documents`, `/join/[token]`, `backend()` mở rộng cho JSON/raw body; OpenAPI + generated types.
- Kiểm chứng: backend ruff + 333 passed/23 skipped; frontend lint/typecheck/build + 11 unit tests; không có Docker nên integration PostgreSQL/MinIO chưa chạy.
- Chưa kiểm chứng / việc còn lại: toàn bộ SQL 0009–0011 trên DB thật; upload stream; browser 375px; `pypdf` chưa vào lock.
- Đề nghị Duc: (1) chạy `AUTH_TEST_DATABASE_URL` integration cho 0009–0011 và `compose up` với MinIO; (2) xem 5 P2 ở REVIEW.md và phản hồi; (3) review `workspace_access.py` + RLS pattern trước khi merge.
- Đề xuất phiên tiếp theo: chốt embedding provider (KNOW-06), cấu trúc đề thực tế (trước M4) rồi mới mở AUTHR/BP.

## 2026-10-21 21:15 +07:00 — Tiếp nhận bàn giao và tiến hành xử lý D-01, D-02

- Tác giả: Hao Nguyen
- Task / trao đổi chi tiết: [Core tracker](../tasks/CORE.md), [Source Review](2026-10-21-source-review.md), [BASE-02 fix](BASE-02-lint-format.md)
- Đã thay đổi: Đã đọc kỹ các ghi chú review của Đức (`2026-10-21-source-review.md`, `BASE-02-lint-format.md`, `QUESTIONS.md`, `REVIEW.md`). Xác nhận các finding D-01 đến D-07 là chính xác.
- Kế hoạch phiên này:
  1. Ghi nhận file update HAO.md.
  2. Áp dụng bản sửa lint/format migration `0002_identity_and_workspaces.py` để giải quyết dứt điểm D-01 / BASE-02.
  3. Bắt tay xử lý D-02 / DB-01: cấu hình phân tách migrator và runtime roles trong PostgreSQL/Compose/Alembic.
- Đề nghị Duc: Theo dõi các PR/Commit tiếp theo sau khi push code lên repo.
