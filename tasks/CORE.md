# Core backlog — M0–M7

[Tracker và quy ước](BACKLOG.md) · [Delivery plan](../IMPLEMENTATION_PLAN.md)

Các ID SET/BASE/AUTH/ACL/DATA/DB/BE/FE/QA/DOC giữ từ backlog ban đầu. Phạm vi FE-02 thu hẹp về workspace onboarding; Library/Classes triển khai ở milestone tương ứng. Mỗi hàng có nghiệm thu tối thiểu; áp dụng thêm Definition of Done ở tracker. `—` nghĩa chưa phân công, không phải cả hai cùng chịu trách nhiệm. Dependencies dạng Mx là gate toàn milestone, không chỉ đã bắt đầu.

## M0 — Baseline và quyết định

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| SET-01 | done | Hao | — | Chốt branch/PR/review conventions; một owner/task, người còn lại review; lưu quy tắc và mẫu PR. |
| SET-02 | done | Hao | — | Ghi working-tree baseline; phân biệt thay đổi có sẵn, không xóa/revert file không thuộc task. |
| BASE-01 | done | Hao | SET-02 | Đọc manifests/locks/setup để xác minh phiên bản Node/Python/package manager/Compose; ghi kết quả cho cả hai máy, không tự nâng phiên bản. |
| BASE-02 | done | Hao | BASE-01 | Chạy backend lint/format-check/tests theo scripts thực tế; ghi command, exit code và lỗi thành task riêng. |
| BASE-03 | done | Hao | BASE-01 | Chạy frontend lint/typecheck/build theo scripts thực tế; lưu kết quả, không coi scaffold là domain hoàn chỉnh. |
| BASE-04 | done | Hao | BASE-01 | Xác minh tên services Compose rồi chạy DB/Redis và migrations trên DB dev; ghi upgrade path, không dùng production data. (Lưu ý: Docker Desktop chưa cài/chạy trên máy phát triển này, các test DB/migration chạy qua pytest/sqlite hoặc cần cài Docker cho môi trường compose đầy đủ). |
| BASE-05 | done | Hao | BASE-02, BASE-03, BASE-04 | Smoke health/live/ready và frontend–API; mô phỏng dependency down, ghi behavior thực tế và lỗi cần sửa. (Đã chạy unit tests cho health endpoints, kết quả 7/7 passed). |
| AUTH-01 | done | Hao | SET-01 | ADR chọn identity provider, issuer/subject binding, chi phí, dev setup; không tự xây auth khi chưa review. (Đã tạo ADR tại tasks/decisions/0001-identity-provider-adr.md). |
| AUTH-02 | done | Hao | AUTH-01 | ADR session/login/logout/callback, CSRF, cookie, audience, expiry, revocation và browser–API trust boundary; có threat cases. (Đã tạo ADR tại tasks/decisions/0002-session-token-trust-boundary-adr.md). |
| ACL-01 | done | Hao | SET-01 | Permission matrix user/workspace/member/resource; personal/school/learner boundaries rõ, least privilege và deny defaults. (Đã đặc tả tại tasks/decisions/0003-permission-matrix-acl.md). |
| DATA-01 | done | Hao | ACL-01 | Review identity/tenant schema, composite FK, provisioning uniqueness, archive/deletion; chốt migration plan. (Đã đặc tả tại tasks/decisions/0004-schema-tenant-migration-plan.md). |
| SCOPE-01 | done | Hao | SET-01 | Chọn 1 cấp, 1–2 môn và nhóm 10–20 giáo viên; định nghĩa pilot success/failure với owner nghiệp vụ. (Đã đặc tả tại tasks/decisions/0005-pilot-scope-success-criteria.md). |
| OPS-01 | done | Hao | BASE-05 | Chốt dev/staging/prod separation, secrets, budget và deployment ADR; secret scan baseline không lộ credentials. (Đã đặc tả tại tasks/decisions/0006-ops-environment-security-adr.md). |

## M1 — Identity và isolation

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| DB-01 | done | Hao | M0 | Tách migrator/runtime roles; runtime không owner/superuser/BYPASSRLS; kiểm tra grants bằng DB thật. |
| DB-02 | done | Hao | DB-01, DATA-01 | Migration users/workspaces/members và audit tối thiểu; tenant FK/unique constraints và upgrade tests. (Đã tạo migration backend/migrations/versions/0002_identity_and_workspaces.py). |
| DB-03 | done | Hao | DB-02 | Transaction-local verified actor/workspace context; reset an toàn khi commit/rollback/pool reuse. (Đã hiện thực tại backend/app/infrastructure/context.py và unit test). |
| DB-04 | done | Hao | DB-03 | RLS + FORCE RLS, active membership checks; missing context deny, bootstrap flow không mở quyền tùy ý. (Đã tạo migration backend/migrations/versions/0003_row_level_security.py). |
| DB-05 | done | Hao | DB-04 | Runtime-role integration tests: tenant A/B, forged IDs, revoked member, pool reuse, negative writes và joins. (Đã chạy deploy/test/rls-smoke.sql trên PostgreSQL 17 staging bằng role eduvia_runtime: 8/8 PASS, transaction rollback. Lưu ý: chưa có test connection-pool thật; pool reuse dựa trên ngữ nghĩa set_config(... , true).) |
| BE-01 | in_progress | Duc | DB-02, AUTH-02 | Verify provider identity/session server-side; bad issuer/audience/expiry/signature và spoofed headers bị chặn. Đã thay verifier bằng RS256/JWKS và negative tests; đã smoke Auth0 local, còn các gate phát hành và review. Xem execution record 2026-10-23. |
| BE-02 | in_progress | Duc | BE-01, DB-04 | Idempotent user provisioning theo stable provider subject; không merge email tùy tiện. Đã có issuer-scoped identity, async bootstrap và PostgreSQL concurrency/migration tests; đã smoke provider local, còn review và gate phát hành. |
| BE-03 | in_progress | Duc | BE-02 | Personal workspace provisioning atomic; concurrent requests chỉ tạo một ownership hợp lệ. |
| BE-04 | in_progress | Duc | BE-03 | Current-user/workspace-list endpoints, paginated DTO tối thiểu; chỉ membership hợp lệ. |
| BE-05 | in_progress | Duc | BE-04, DB-05 | Workspace auth dependency; client-selected context luôn được verify; revoke có hiệu lực không dựa UI. |
| BE-06 | in_progress | Duc | BE-05 | Export OpenAPI và generate frontend types theo scripts repo; CI phát hiện contract drift. |
| FE-01 | in_progress | Duc | BE-01 | Login/logout/callback UI; loading/error/session expiry, không chứa provider secrets. |
| FE-02 | in_progress | Duc | BE-06, FE-01 | Onboarding + dashboard workspace thật; không cần Library/Classes API chưa tồn tại. |
| FE-02a | in_progress | Duc | — | Chuẩn bị onboarding/workspace mock độc lập; prerequisite phần mock FE-01 đã merge PR #5 (2379a6e), không thay gate FE-02 thật. React-memory theo session; pending/retry/logout/expiry và responsive có evidence. |
| FE-03 | in_progress | Duc | FE-02 | Protected routes và 401/403 states; không rò dữ liệu qua SSR/cache; server authorization độc lập. |
| FE-04 | in_progress | Duc | FE-02 | Workspace selector và tên context hiện hành; switch invalidate tenant caches. |
| QA-01 | in_progress | Duc | FE-03, FE-04 | Automated E2E login → provision → workspace → logout; bổ sung manual smoke cho provider. |
| QA-02 | in_progress | Duc | QA-01, DB-05 | Security suite hai users, CSRF, session/revocation, concurrent onboarding và workspace switch; evidence pass. |
| DOC-01 | in_progress | Duc | QA-02 | Setup/auth troubleshooting và implemented-status cập nhật, người thứ hai chạy lại được. |

## M2 — Jobs, cost, storage

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| JOB-01 | review | Hao | M1 | Migration job state machine + outbox, idempotency key/request hash scoped owner; duplicate conflict không tạo job mới. (Dạng lean (plan 3.4): bảng `background_jobs` là nguồn sự thật, idempotency key + request hash theo owner, duplicate trả job cũ/409 (migration 0010).) |
| JOB-02 | review | Hao | JOB-01 | Dispatcher publish/ack/retry với durable outbox; broker downtime không mất accepted command. (Dạng lean: Celery `acks_late` + lease 5 phút trong PostgreSQL, sweeper 60s re-dispatch job mất message; chưa có outbox đầy đủ.) |
| JOB-03 | todo | — | JOB-02 | Worker leases/fencing/heartbeat; stale worker không commit kết quả sau khi lease đổi. |
| JOB-04 | review | Hao | JOB-03 | Retry/backoff/cancel/sweeper và terminal states; poison job có recovery path không retry vô hạn. (Dạng lean: retry/backoff tối đa 3 lần, cancel (queued→cancelled, running→cancel_requested), sweeper fail job quá lease.) |
| JOB-05 | review | Hao | JOB-04 | Authorized progress/retry/cancel API và UI; reconnect không nhân đôi action, worker reauthorize actor-sensitive work. (API `/v1/workspaces/{id}/jobs` list/get/cancel/retry; reconnect không nhân đôi retry. UI progress mới có trang Tài liệu (poll 3s).) |
| COST-01 | review | Hao | JOB-01 | Ledger/reservation schema và unit policy; provider execution ID khác logical job ID, số tiền fixed precision. (Dạng lean: `usage_events` append-only, `workspace_quotas` cap cứng/tháng (trigger tạo quota khi tạo workspace).) |
| COST-02 | review | Hao | COST-01 | Atomic quota reserve/settle/release; concurrent requests không vượt ceiling, timeout không tự giả định free. (Dạng lean: reserve trong transaction với `SELECT ... FOR UPDATE` quota; vượt cap → 429. Concurrency chỉ có integration test chưa chạy local.) |
| COST-03 | todo | — | COST-02, JOB-04 | Reconcile uncertain executions và expired holds; không double charge logical retry, vẫn ghi actual duplicate provider cost. |
| STORE-01 | review | Hao | M1 | Private bucket, object metadata, scoped signed upload; validate size/type/path/expiry, tenant không chọn key người khác. (Dạng lean: upload qua API (raw body, MIME allowlist pdf/docx/txt, ≤25 MiB, magic bytes), object key do server đặt, MinIO trong compose.) |
| STORE-02 | review | Hao | STORE-01, COST-02 | Upload finalize/quarantine checks; live+held bytes tính quota, abandoned multipart cleanup idempotent. (Dạng lean: sha256 streaming, kiểm tra size/khớp object khi ingest; thiếu/khác size → quarantined. Chưa có held bytes/multipart.) |
| STORE-03 | review | Hao | STORE-02 | Authorized short-lived download/export URLs và file lifecycle; revoke chặn cấp URL mới, không hứa thu hồi file đã tải. (Signed GET ≤5 phút, attachment; soft delete + job `document.delete` xóa object; chưa thu hồi URL đã cấp.) |
| STORE-04 | review | Hao | STORE-03, JOB-05 | Upload/progress/failure/retry UI; lỗi file không publish, quota messages rõ và accessible. (Trang `/dashboard/documents`: upload có checkbox quyền sử dụng, trạng thái, tải về, xóa; chưa kiểm browser.) |
| AUDIT-01 | review | Hao | JOB-01 | Structured audit/trace IDs cho sensitive mutations; redaction secrets/PII và admin access scope tests. (Tối thiểu: `app/core/audit.py` log JSON có request/user/workspace, redaction token/secret/email; gọi ở upload/delete/cancel/retry/reingest/tags.) |
| M2-QA | todo | — | JOB-05, COST-03, STORE-04, AUDIT-01 | Fault tests broker/worker kill, fencing, quota race, storage leak, duplicate messages; recovery chứng minh không mất command. |

## M3 — Knowledge và RAG

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| KNOW-01 | review | Hao | M2 | Curriculum metadata migration/seeds cho pilot; grade/subject/year/source provenance được version hóa. (Migration 0011: `curriculum_subjects`/`curriculum_units` platform-wide, seed Toán/Văn/Anh + 15 đơn vị Toán 10–12 (`seed:pilot-draft`, chuyên môn cần duyệt).) |
| KNOW-02 | review | Hao | KNOW-01 | Rights attestation và source access policy; upload không tự thành shared corpus, missing rights bị reject. (`documents.rights_attested` bắt buộc khi upload/reingest; `rights_scope` chỉ `private` (shared corpus chưa bật theo quyết định 3.5).) |
| KNOW-03 | review | Hao | KNOW-02 | Immutable document versions + activation transaction; failed ingest không thay active version. (`document_versions` immutable, partial unique active, trigger chuyển trạng thái; ingest thất bại không thay active version.) |
| KNOW-04 | review | Hao | KNOW-03 | Sandboxed PDF-text/DOCX/TXT parsing, resource limits và malformed files tests; scan PDF chưa OCR hiển thị unsupported. (Parser TXT/DOCX (stdlib, chống zip bomb, timeout 30s); PDF cần thêm `pypdf` (chưa thêm dependency), PDF scan → `no_text_layer` hiển thị unsupported.) |
| KNOW-05 | review | Hao | KNOW-04 | Versioned chunking pipeline; preserve page/section offsets, dedupe và reproducible fixtures. (`document_chunks` theo version, offsets page/section/char, dedupe, golden fixtures `tests/fixtures/chunking`.) |
| KNOW-06 | review | Hao | KNOW-05 | Embedding provider adapter + model/index versions; retries metered, reindex không trộn incompatible vectors. (Adapter `services/embeddings.py`: local hash embedder (dev/test, production từ chối) + OpenAI-compatible HTTP; migration 0012 cột vector(1024) + embedding_runs; provider/model CHƯA chốt.) |
| KNOW-07 | review | Hao | KNOW-06 | Authorized hybrid retrieval/reranking; tenant/license filters trước trả context, cross-tenant negative evals. (`services/retrieval.py`: hybrid tsvector(simple)+cosine, RRF, chỉ version active/attested/private, đúng model version; rỗng = abstain, không nới scope.) |
| KNOW-08 | review | Hao | KNOW-07 | Citation resolver và source preview UI; snippets map đúng version/page, không bịa nguồn khi thiếu context. (`services/citations.py` + API citations/{chunkId}; superseded → 404 trừ allowSuperseded; UI drawer `/dashboard/library`.) |
| KNOW-09 | review | Hao | KNOW-08 | Library search/version/delete UI + deletion jobs; remove index/cache/blob theo retention policy, replay không hồi sinh deleted data. (UI thư viện + xóa mềm; `edu.purge_document_chunks` SECURITY DEFINER trong job delete, replay idempotent.) |
| KNOW-10 | review | Hao | KNOW-09 | RAG eval dataset được phép dùng; retrieval/citation/abstention và prompt-injection tests, ngưỡng pilot được phê duyệt. (`app/eval/rag_eval.py` + 18 câu tiếng Việt seed (12 factual/3 abstain/3 injection); ngưỡng CHƯA được duyệt, chỉ báo cáo.) |

## M4 — Authoring và exam blueprint

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| AUTHR-01 | review | Hao | M3 | Content/revision/review schema + optimistic concurrency; version history và editing conflict tests. (Migration 0013: content_items/revisions/review_requests, optimistic concurrency, trigger immutability.) |
| AUTHR-02 | review | Hao | AUTHR-01 | Manual lesson/study-guide editor và autosave; AI outage vẫn soạn/sửa/nộp duyệt được. (API autosave `PUT /content-items/{id}/draft` + UI `/dashboard/lessons` (đang làm đợt 4).) |
| AUTHR-03 | review | Hao | AUTHR-02 | AI draft adapter dùng authorized retrieval, schema validation và token/cost budget; source injection không đổi system policy. (Job `content.generate`/`questions.generate`; adapter LLM (fake dev / Anthropic qua stdlib), prompt tiếng Việt coi nguồn là dữ liệu không tin cậy; citation không khớp nguồn bị loại, draft không tự duyệt. Metered qua usage.) |
| AUTHR-04 | review | Hao | AUTHR-03 | Review/edit/approve exact content revision; provenance/citations visible, chưa review không tự publish. (API provenance + `approve-with-provenance` (409 khi citation không resolve); UI panel "Soạn cùng AI" đang làm đợt 5.) |
| QB-01 | review | Hao | AUTHR-01 | Single-choice question bank + revision/key separation; constraints choices/correct key, teacher-only DTO. (questions/question_revisions + `question_keys` tách riêng, runtime chỉ INSERT, đọc qua `edu.question_key` cho giáo viên.) |
| QB-02 | review | Hao | QB-01 | Question editor/filter/import theo format đã chốt; validation từng record, duplicate review và objective mappings. (CSV import atomic có báo lỗi từng dòng và duplicate review; export teacher/student là hai hàm riêng.) |
| BP-01 | review | Hao | QB-02 | Blueprint draft/version/parts/slots/matrix schema và editor; scope/provenance/effective year rõ. (blueprints/blueprint_versions với parts/slots/matrix, provenance, effective_year.) |
| BP-02 | review | Hao | BP-01 | Validator counts/points/topic/cognitive matrix; difficulty không đồng nhất cognitive demand, unsupported item type fail. (`services/blueprints.py` validator: counts/points/matrix/cognitive/unsupported type theo EXAM_BLUEPRINTS.) |
| BP-03 | review | Hao | BP-02, AUTHR-03 | Constrained pool selection/generation; insufficient pool báo thiếu slot, không âm thầm đổi matrix. (`services/exam_builder.py`: chọn câu theo slot deterministic theo seed; thiếu pool → 409 `insufficient_pool` kèm missingSlots và gợi ý sinh câu, không đổi matrix.) |
| BP-04 | review | Hao | BP-03, AUTHR-04 | Review và publish immutable exam snapshot pin question/blueprint/scoring versions; approved draft không tự sửa published exam. (Migration 0014: exams/exam_versions/exam_items/exam_answer_keys (runtime INSERT-only, đọc qua `edu.exam_item_key`/`edu.exam_keys_for_scoring`), publish validate + trigger immutability, content_hash.) |
| EXPORT-01 | review | Hao | BP-04 | Student/teacher Word/PDF export riêng qua durable jobs; layout fixtures, student artifacts tuyệt đối không có key/rubric. (Job `export.render`: DOCX bằng stdlib OOXML có golden test, bản học sinh không có key; PDF fail-closed `pdf_unicode_unsupported` (cần dependency nhúng font, chưa thêm).) |
| M4-QA | review | Hao | EXPORT-01 | Blueprint unsatisfiable/type rejection, key leakage SSR/API/export, license revoke, AI outage và publish races tests. (`tests/test_qa_gates.py`: key-leak scan trên OpenAPI DTO học sinh, 401/404 mọi route tenant, FORCE RLS 37 bảng 0009–0015, không DELETE trên bảng key/ledger, forward-only, 1 head. Integration PostgreSQL chưa chạy local.) |

## M5 — Teaching portal

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| CLASS-01 | review | Hao | M1 | Class/teacher/roster schema + CRUD; tenant FKs, archive policy và class-scoped authorization. (Migration 0009: classes/class_teachers/students/enrollments với composite FK, FORCE RLS; API CRUD + archive, teacher chỉ thấy lớp mình dạy.) |
| CLASS-02 | review | Hao | CLASS-01 | Invitation tokens hash/expiry/single-use/rate limits; token không là credential đọc nội dung. (`class_invitations` lưu sha256 token, hết hạn ≤30 ngày, max_uses 1..500, single-use atomic qua SECURITY DEFINER; rate limit in-process (Redis ở M7).) |
| CLASS-03 | review | Hao | CLASS-02 | Student identity/enrollment acceptance và withdrawal; không merge học sinh chỉ qua tên, giữ lịch sử theo policy. (Accept theo user đã đăng nhập, không merge học sinh theo tên; withdraw idempotent; học sinh không thành member workspace giáo viên.) |
| CLASS-04 | review | Hao | CLASS-03 | Teacher roster/invite UI, student join UI và empty/error states; người ngoài lớp không thấy roster. (UI `/dashboard/classes`, chi tiết lớp/roster, tạo mã mời một lần, thu hồi, rút; `/join/[token]`; chưa kiểm browser.) |
| ASSIGN-01 | review | Hao | CLASS-04, M4 | Assignment pin immutable publication, windows/attempt policy/timezone; sửa draft không đổi đề đã giao. (Migration 0015 `assignments` pin exam_version đã publish, window/time limit/timezone (zoneinfo), max_attempts, release policy; trigger khóa pin sau publish, closes_at chỉ nới.) |
| ASSIGN-02 | review | Hao | ASSIGN-01 | Student mobile assignment list/detail; only enrolled + release checks, revoke chặn thao tác mới. (API `/v1/student/assignments` qua SECURITY DEFINER theo `edu.actor_id()` + enrollment active; UI học sinh đang làm đợt 5.) |
| M5-QA | in_progress | Hao | ASSIGN-02 | E2E invite→join→assign→withdraw, guessing IDs, replay token và mobile accessibility tests. (E2E skeleton `frontend/tests/e2e/pilot-journey.spec.ts` (skip trừ EDUVIA_E2E=1); mobile accessibility chưa kiểm browser.) |

## M6 — Assessment và results

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| ASMT-01 | review | Hao | M5 | Attempt/answer/submission schema và start endpoint; atomic attempt limits, server deadline và snapshot binding. (`quiz_attempts` + `edu.student_start_attempt` (advisory lock, partial unique in_progress, deadline = least(closes_at, start+limit)).) |
| ASMT-02 | review | Hao | ASMT-01 | Autosave expected revision + client sequence; stale retry không ghi đè câu trả lời mới. (`edu.student_save_answer` với expected_revision + client_sequence; stale → EV014.) |
| ASMT-03 | review | Hao | ASMT-02 | Quiz mobile UI/timer/reconnect/save indicators; không báo saved khi server chưa acknowledge. (UI `/student/attempts/[id]`: một câu/màn, autosave theo revision+sequence, chỉ báo "Đã lưu" sau ack server, timer theo serverNow, offline banner, submit idempotent; chưa chạy browser.) |
| ASMT-04 | review | Hao | ASMT-02 | Locked idempotent submit; submit timeout lookup cùng key, concurrent submit chỉ một accepted snapshot. (`edu.student_submit` idempotent theo Idempotency-Key + request hash, snapshot sha256; hash khác → EV011.) |
| ASMT-05 | review | Hao | ASMT-04 | Deadline sweeper/expiry policy; late answers reject, race autosave/submit/expiry có deterministic outcome. (`edu.expire_attempts` trong sweep 60s; late answer → EV010; submit vs expiry deterministic (first commit wins).) |
| ASMT-06 | review | Hao | ASMT-05 | Pure single-choice scoring + grading snapshot/job; fixed precision fixtures, pending không coi là zero. (`services/scoring.py` Decimal 2dp, run_key idempotent, job `attempt.grade`; pending không hiển thị 0.) |
| ASMT-07 | review | Hao | ASMT-06 | Separate score/solution release policies; student API/SSR/cache không lộ key trước release. (Score/solution release tách riêng (immediate/after_close/manual); `edu.student_results` chỉ trả key sau solutions_released_at.) |
| ASMT-08 | review | Hao | ASMT-07 | Authorized grade override append-only revision/reason/audit; aggregate reproject không double count. (`services/overrides.py`: grading_result manual + grade revision append-only có reason, audit; không tự release.) |
| ASMT-09 | review | Hao | ASMT-08, ASMT-03 | Teacher results và student feedback UI; mẫu số enrolled/submitted/graded/pending, export scoped. (UI `/dashboard/assignments/[id]` kết quả với mẫu số đã nộp/đã chấm/chờ chấm/tổng, CSV export, điều chỉnh điểm có lý do; `/student/.../results` chỉ hiện lời giải sau release.) |
| M6-QA | in_progress | Hao | ASMT-09 | Automated start/submit/deadline races, disconnect, grading retries, solution leaks và correction fixtures. (Race tests ở `test_attempts_unit.py` (fake definer) + `test_assessment_integration.py` (cần DB); chưa chạy trên PostgreSQL.) |

## M7 — Pilot readiness

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| PILOT-01 | in_progress | Hao | M6 | Automated teacher→draft→review→assign→student→score E2E; core failures chặn release. (Spec Playwright teacher→draft→exam→assign→student→score viết xong, chưa chạy; cần stack đầy đủ (worker --beat, S3, fake LLM).) |
| PILOT-02 | review | Hao | M6 | Threat-model review + penetration regression tenant/key/file/auth checks; findings có severity/owner và fix gate. (Threat model `tasks/decisions/0007-threat-model-pilot.md` (STRIDE, 25 SECURITY DEFINER được liệt kê, checklist pentest regression). Findings mở: CSP/HSTS, Redis rate limit, audit chỉ log.) |
| PILOT-03 | todo | — | M6 | Load/soak profile theo pilot size, API/worker/DB budgets; capacity và latency targets được chốt trước đo. |
| PILOT-04 | review | Hao | M6 | Alerts/dashboard/runbooks cho queue lag, scoring failures, quota/provider cost, auth incidents; thực hiện alert drill. (Runbooks `deploy/runbooks/*`, `deploy/alerts/queries.sql` + `check.py` (exit 0/1/2), chưa chạy alert drill thật.) |
| PILOT-05 | review | Hao | M6 | Privacy/consent/retention/export/erasure policy và UI cần thiết; minor-data review bởi người phù hợp, không tuyên bố compliant tự động. (`tasks/decisions/0008-privacy-consent-retention.md` + test inventory chống drift; đề xuất schema `student_consents` chưa tạo; CẦN tư vấn pháp lý NĐ13/2023, chưa có erasure/export học sinh.) |
| PILOT-06 | in_progress | Hao | PILOT-05 | DB + object restore drill, tombstones/revocations reapplied; đo RPO/RTO với targets được duyệt. (`deploy/restore-drill.sh` (dry-run mặc định) viết xong, chưa `--execute`; RPO/RTO chờ duyệt.) |
| PILOT-07 | in_progress | Hao | PILOT-01, PILOT-02, PILOT-03, PILOT-04, PILOT-06 | Staging→production deployment/rollback checklist; không rollback schema phá accepted submissions, secrets/env isolation kiểm chứng. (`deploy/CHECKLIST-release.md` viết xong; staging compose đã thêm env EMBEDDING/LLM bắt buộc và worker --beat; `deploy/test-staging.py` còn lỗi thiếu service sessions.) |
| PILOT-08 | todo | — | PILOT-07 | Pilot onboarding/support/feedback và go-no-go signoff; không còn lỗi chặn isolation, mất bài hoặc sai điểm. |

### BASE-01 — execution record: acceptance clarification / tooling

- Owner theo tracker: Hao; reviewer cho đợt tooling chưa có người xác nhận.
- Người dùng đã miễn yêu cầu evidence môi trường/chạy lại trên máy thứ hai trong phiên 2026-10-21. Không coi ngoại lệ này là bằng chứng đã chạy trên hai máy.
- Branch triển khai tooling: `fix/tooling-ci`; Codex thực hiện theo yêu cầu người dùng, không tự thay owner task.
- Scope bổ sung: sửa setup PowerShell 5.1/7, cập nhật verifier cho migration head hiện tại, thêm regression checks và CI. Evidence/giới hạn: [bàn giao tooling](../discuss/BASE-tooling-ci.md).
- Trạng thái các hàng task giữ nguyên; đợt tooling mới chưa được reviewer con người nghiệm thu. Pilot/ngân sách/region vẫn chưa chốt; DB roles/RLS ngoài phạm vi đợt này.

### FE-01 — execution record
Owner: Duc
Reviewer: Hao (đề xuất; chưa review)
Branch: fe-01-auth-mock
Phạm vi: frontend mock auth; session trong React memory, không provider/token/backend/authorization. BE-01 vẫn là dependency cho tích hợp thật; chưa nghiệm thu toàn bộ FE-01.
Scenario dev: thành công, lỗi, callback bị hủy, hết hạn sau 5 giây. Production chỉ có đăng nhập thử thành công.
Ngày cập nhật: 2026-10-22
Kiểm tra: frontend lint/typecheck pass; production build + standalone pass ngoài sandbox (sandbox EPERM). Browser xác nhận success/loading/logout/error/cancel/expiry/reload; DOM 375px không tràn ngang. Desktop visual pass; mobile visual capture chưa đáng tin cậy, còn chờ signoff. Chi tiết: frontend/FE-01.md.

FE-01 follow-up (2026-10-22): đã bổ sung operation ID để hủy login khi rời route, bỏ kết quả cũ và bảo vệ timer/session mới; menu reset theo pathname. Lint/typecheck và production build+standalone pass. Browser checks đạt cho cancel/retry/expiry/logout/reload/keyboard/production. Evidence và draft PR body: frontend/FE-01.md, frontend/FE-01-PR.md. Capture raster vẫn không khớp DOM ở cả desktop/mobile; visual signoff chưa đạt, chưa ghi mock sẵn sàng review. FE-01 giữ in_progress; chưa push/PR/deploy.

### FE-02a — execution record
Owner: Duc
Reviewer: Hao (đề xuất; chưa review)
Branch: feat/fe-02-workspace-mock
Prerequisite: FE-01 mock đã merge PR #5 / 2379a6e; không tuyên bố FE-01 thật hoặc BE-06 đã đạt.
Phạm vi: frontend onboarding + workspace mock; reset theo sessionVersion, bỏ kết quả cũ theo operation/session, không HTTP/provider/migration/API contract.
Kiểm tra: lint/typecheck pass; 4 Node adapter tests pass; build production + standalone pass. Browser dev/production: success/existing/error-retry/cancel/logout/expiry/reload/keyboard đạt. DOM 375x812 và 1440x900 không tràn ngang; capture vẫn không khớp DOM nên visual signoff chưa đạt.
Evidence: frontend/FE-02a.md; frontend/evidence/fe-02a/geometry.json. PR body local: frontend/FE-02a-PR.md.
Trạng thái: in_progress; FE-02 giữ todo, FE-01 giữ in_progress. Chưa commit/push/PR/deploy.
Ngày cập nhật: 2026-10-22

FE-02a review trước commit (2026-10-22): đã rà diff + toàn bộ file mới, chưa xác nhận lỗi chức năng mới trong phạm vi mock; lượt review chỉ cập nhật docs, không sửa source/test. Baseline lint/typecheck/build + 4 adapter tests + 14 backlog tests được giữ nguyên, không tuyên bố là lượt chạy mới. Findings còn mở: visual acceptance (P2), CI frontend chưa gọi test:workspace (P2, phối hợp Hào; không sửa workflow), provider/race E2E coverage chỉ manual. FE-02a.md có checklist visual, file manifest và review boundaries; FE-02a-PR.md theo PR template. FE-02a/FE-01 vẫn in_progress, FE-02 todo; chưa có reviewer approval/commit/push/PR/deploy.

Bàn giao discuss (2026-10-22 22:12 +07:00): đã thêm ghi chú phía Duc tại [discuss/DUC.md](../discuss/DUC.md) và yêu cầu review đề xuất tại [discuss/REVIEW.md](../discuss/REVIEW.md); chưa có phản hồi/chấp thuận của Hao. Discuss chỉ dẫn evidence và hành động phối hợp, không thay authority owner/status tại tracker.


### BE-01..06 / FE-01..04 / QA-01..02 / DOC-01 — execution record 2026-10-23

Owner tích hợp: Duc, theo người dùng xác nhận Hào đã bàn giao scope backend/frontend của flow đăng ký và đăng nhập. Đây là một slice tích hợp đang thực hiện qua các work package M1; không phải nhiều luồng agent song song. Reviewer đề xuất: Hào, chưa có xác nhận review.

Thay đổi: Auth0-hosted email/password signup/login, verification/resend, Redis server sessions, RS256 verifier, identity/workspace bootstrap và các endpoint thật; frontend dashboard riêng, CSRF và server route guards. Dùng migration mới 0004, không sửa SQL của các migration đã phát hành. Runtime role và NOLOGIN function owner tách biệt.

Evidence và giới hạn: [bản ghi triển khai](../discuss/2026-10-23-auth-implementation.md); setup tại [Auth0 runbook](../deploy/auth0/README.md). Tenant development đã tạo; người dùng xác nhận smoke Auth0/verification/reset email thật trên local. Resend bị skip, refresh thật chưa xác nhận, HTTPS staging/máy thứ hai chưa kiểm chứng. Người dùng quyết định giữ Auth0. CI workflow đã thêm test, chưa chạy GitHub CI cho diff này. Giữ các task liên quan `in_progress`, chưa nghiệm thu M1, chưa xác nhận review/merge/deploy.


### CLASS-01..04 / JOB-01,02,04,05 / COST-01,02 / STORE-01..04 / AUDIT-01 / KNOW-01..05 — execution record 2026-10-23

Owner: Hao (thực hiện bằng agent theo yêu cầu người dùng, chia 5 work package song song, file không trùng). Reviewer đề xuất: Duc. Trạng thái `review` nghĩa là code + unit test có, **chưa** có evidence PostgreSQL thật và chưa có người thứ hai duyệt; không coi gate M2/M3/M5 đạt.

Phạm vi: migrations `0009_classes`, `0010_jobs_storage`, `0011_knowledge` (forward-only trừ 0009); `app/api/workspace_access.py` (BE-05 dùng chung: membership + RLS context cho mọi route tenant); router classes/documents/jobs/knowledge mount trong `main.py`; worker `app.tasks.jobs` (acks_late, lease, sweeper beat 60s); MinIO trong `compose.yaml`; frontend `/dashboard/classes`, `/dashboard/documents`, `/join/[token]` qua BFF `backend()` mở rộng (JSON/raw body, CSRF giữ nguyên). Dạng lean theo IMPLEMENTATION_PLAN 3.4.

Kiểm chứng local (Windows, không Docker): backend `ruff check`/`format --check` PASS; `pytest -q` 333 passed, 23 skipped (toàn bộ integration cần `AUTH_TEST_DATABASE_URL`); OpenAPI export + `npm run api:generate` không drift; frontend lint/typecheck/build PASS, `test:unit` 11/11, `test:workspace` PASS. Review M1 của Duc (nháp) tại [discuss/REVIEW.md](../discuss/REVIEW.md): 0 P1, 5 P2, 18 P3.

Chưa kiểm chứng: SQL của 0009–0011 (RLS, SECURITY DEFINER, trigger, grants) chưa chạy trên PostgreSQL; MinIO image tag/healthcheck chưa chạy; upload stream qua Next→FastAPI; UI ở browser 375px; `pypdf` chưa thêm vào lock (cần uv). Quyết định còn treo trước khi đi tiếp: embedding model/provider (KNOW-06), cấu trúc đề thực tế (trước M4), pháp lý dữ liệu (3.5).


### KNOW-06..10 / AUTHR-01,02 / QB-01,02 / BP-01,02 — execution record 2026-10-23 (đợt 3)

Owner: Hao (agent). Branch `feat/m3-rag-m4-authoring-foundation`, commit `90fe49c`, stack trên `feat/m2-m5-know-lean-slice`. Kiểm chứng local: backend 600 passed / 31 skipped, ruff sạch; frontend lint/typecheck/build + 17 unit tests. Chưa chạy SQL 0012–0013 trên PostgreSQL/pgvector; provider embedding từ xa chỉ test với HTTP giả. Quyết định cần chốt: embedding model (đề xuất bge-m3 hoặc multilingual-e5-large, 1024 chiều), ngưỡng eval, metering query.


### AUTHR-03,04 / BP-03,04 / EXPORT-01 / ASSIGN-01,02 / ASMT-01..08 — execution record 2026-10-23 (đợt 4)

Owner: Hao (agent). Branch `feat/m4-generation-m5-m6-assessment`, commit `911c959`, stack trên đợt 3. Kiểm chứng local: backend 965 passed / 37 skipped, ruff sạch, một Alembic head `0015_assessment`; frontend lint/typecheck/build + 30 unit tests (UI soạn bài/câu hỏi/blueprint). Chưa chạy SQL 0014–0015 trên PostgreSQL (toàn bộ plpgsql SECURITY DEFINER phía học sinh chưa compile thật); chưa gọi Anthropic thật; worker cần consume queue `generation`/`export` (compose đã có). PDF export chưa dùng được với tiếng Việt.


### ASMT-03,09 / M4-QA / M5-QA / M6-QA / PILOT-01..07 + sửa lỗi staging — execution record 2026-10-23 (đợt 5)

Owner: Hao (agent). Branch `feat/m5-m6-ui-m7-pilot-readiness` stack trên đợt 4. Kiểm chứng local: backend 999 passed / 37 skipped, ruff sạch; frontend lint/typecheck/build + 51 unit tests; YAML compose/CI parse ok. Sửa theo findings M7: (F1) `compose.staging.yaml` yêu cầu `EMBEDDING_PROVIDER`/`LLM_PROVIDER` thật vì production từ chối provider local/fake; (F2) worker staging chạy `--beat`; (F3) rate limit accept mã mời chuyển sang theo actor+token thay vì IP (mọi request đến từ BFF); (F4) CI job `auth-integration` chạy toàn bộ integration 0009–0015.

Chưa làm: PILOT-03 (load/soak), PILOT-08 (go/no-go). Chưa kiểm chứng ở bất kỳ đợt nào: SQL 0009–0015 trên PostgreSQL thật (CI của PR sẽ là lần đầu), browser UI, provider AI/embedding thật, restore drill, E2E. Quyết định treo: embedding model, cấu trúc đề thực tế, pháp lý dữ liệu, ngưỡng RAG eval, `pypdf` + font PDF.
### Better Auth / Account Center — execution 2026-10-23

Người dùng thay quyết định provider và duyệt implementation: email/password + Google, Account Center, explicit linking cùng email, giữ user/workspace cũ qua chuyển đổi có hai bằng chứng; không merge user đã có dữ liệu. Owner Duc, reviewer đề xuất Hào. Các task liên quan tiếp tục `in_progress`, chưa signoff/cutover. [Evidence](../discuss/2026-10-23-better-auth-account-center.md), [runbook](../deploy/better-auth/README.md). Checkpoint Auth0 `912c0d2` giữ lịch sử; không diễn giải smoke Auth0 cũ như nghiệm thu Better Auth.


### Gộp `main` (Better Auth, 0005–0007 của Duc) vào stack — 2026-10-24

Sau khi Duc push `b2f06c8` (Better Auth, `user_identities`, migrations `0005_multi_identity`/`0006_identity_transfer`/`0007_auth_revocation`), 4 PR stack bị conflict và Alembic có hai head. Xử lý trên branch `feat/m5-m6-ui-m7-pilot-readiness`: merge `origin/main`; đánh số lại 7 migration của Hao thành `0009_classes` … `0015_assessment`, `0009_classes` revises `0007_auth_revocation`; port phần mở rộng `backend()` (JSON/raw body, 204, passthrough) sang `auth.ts` mới của Duc dưới dạng `accessToken()` dùng chung cho Auth0 legacy và Better Auth; `getCsv` dùng helper này; login page giữ cả `PasswordLogin` và `returnTo`; QA gates/privacy inventory cập nhật (thêm `user_identities`, `identity_transfers`). Kiểm chứng: backend 1004 passed / 38 skipped, một head `0015_assessment`; frontend lint/typecheck/build + 51 unit tests. Đề xuất: đóng 3 PR đầu, giữ một PR từ branch này vào `main`; review theo commit. Vẫn chưa chạy SQL trên PostgreSQL thật.
## 2026-10-23 — Better Auth only / Auth0 retirement

Owner Duc; reviewer đề xuất Hào, chưa signoff. User chốt bỏ một account/workspace thử Auth0, không chuyển dữ liệu. SDK/config/transfer endpoints được gỡ, migration 0008 tiến tới, cleanup có dry-run/transaction. Local backup restore đã kiểm; dữ liệu cũ đã xóa. Evidence và phần Google/SMTP thật, cloud teardown, staging còn thiếu: [discuss](../discuss/2026-10-23-auth0-retirement.md).

2026-10-23 — Owner Duc; reviewer đề xuất Hào. Mailpit dev-mail + native local email smoke đã triển khai, Google/manual local/staging chưa nghiệm thu. [Evidence](../discuss/2026-10-23-local-auth-mailpit.md).


### Gộp `main` lần 2 (Auth0 retired, `0008_remove_auth0_transfer`) — 2026-10-24

Duc push `947856e` (bỏ Auth0 hoàn toàn, migration `0008_remove_auth0_transfer`, xóa `legacy-auth.ts` và `playwright.config.ts`). Xử lý: merge lại; migration của Hao thành `0009_classes` … `0015_assessment` (`0009_classes` revises `0008_remove_auth0_transfer`), một head `0015_assessment`; `auth.ts` chỉ còn Better Auth với `accessToken()`/`backend(options)`; E2E chuyển sang `playwright.e2e.config.ts` (`npm run test:e2e`); DEVELOPMENT.md ghi trạng thái theo Better Auth. Kiểm chứng: backend 1000 passed / 41 skipped; frontend lint/typecheck/build + 51 unit tests. Đề nghị thống nhất với Duc: ai thêm migration thì báo trước số kế tiếp để tránh trùng.
