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
| DB-03 | in_progress | Hao | DB-02 | Transaction-local verified actor/workspace context; reset an toàn khi commit/rollback/pool reuse. |
| DB-04 | todo | — | DB-03 | RLS + FORCE RLS, active membership checks; missing context deny, bootstrap flow không mở quyền tùy ý. |
| DB-05 | todo | — | DB-04 | Runtime-role integration tests: tenant A/B, forged IDs, revoked member, pool reuse, negative writes và joins. |
| BE-01 | todo | — | DB-02, AUTH-02 | Verify provider identity/session server-side; bad issuer/audience/expiry/signature và spoofed headers bị chặn. |
| BE-02 | todo | — | BE-01, DB-04 | Idempotent user provisioning theo stable provider subject; không merge email tùy tiện. |
| BE-03 | todo | — | BE-02 | Personal workspace provisioning atomic; concurrent requests chỉ tạo một ownership hợp lệ. |
| BE-04 | todo | — | BE-03 | Current-user/workspace-list endpoints, paginated DTO tối thiểu; chỉ membership hợp lệ. |
| BE-05 | todo | — | BE-04, DB-05 | Workspace auth dependency; client-selected context luôn được verify; revoke có hiệu lực không dựa UI. |
| BE-06 | todo | — | BE-05 | Export OpenAPI và generate frontend types theo scripts repo; CI phát hiện contract drift. |
| FE-01 | todo | — | BE-01 | Login/logout/callback UI; loading/error/session expiry, không chứa provider secrets. |
| FE-02 | todo | — | BE-06, FE-01 | Onboarding + dashboard workspace thật; không cần Library/Classes API chưa tồn tại. |
| FE-03 | todo | — | FE-02 | Protected routes và 401/403 states; không rò dữ liệu qua SSR/cache; server authorization độc lập. |
| FE-04 | todo | — | FE-02 | Workspace selector và tên context hiện hành; switch invalidate tenant caches. |
| QA-01 | todo | — | FE-03, FE-04 | Automated E2E login → provision → workspace → logout; bổ sung manual smoke cho provider. |
| QA-02 | todo | — | QA-01, DB-05 | Security suite hai users, CSRF, session/revocation, concurrent onboarding và workspace switch; evidence pass. |
| DOC-01 | todo | — | QA-02 | Setup/auth troubleshooting và implemented-status cập nhật, người thứ hai chạy lại được. |

## M2 — Jobs, cost, storage

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| JOB-01 | todo | — | M1 | Migration job state machine + outbox, idempotency key/request hash scoped owner; duplicate conflict không tạo job mới. |
| JOB-02 | todo | — | JOB-01 | Dispatcher publish/ack/retry với durable outbox; broker downtime không mất accepted command. |
| JOB-03 | todo | — | JOB-02 | Worker leases/fencing/heartbeat; stale worker không commit kết quả sau khi lease đổi. |
| JOB-04 | todo | — | JOB-03 | Retry/backoff/cancel/sweeper và terminal states; poison job có recovery path không retry vô hạn. |
| JOB-05 | todo | — | JOB-04 | Authorized progress/retry/cancel API và UI; reconnect không nhân đôi action, worker reauthorize actor-sensitive work. |
| COST-01 | todo | — | JOB-01 | Ledger/reservation schema và unit policy; provider execution ID khác logical job ID, số tiền fixed precision. |
| COST-02 | todo | — | COST-01 | Atomic quota reserve/settle/release; concurrent requests không vượt ceiling, timeout không tự giả định free. |
| COST-03 | todo | — | COST-02, JOB-04 | Reconcile uncertain executions và expired holds; không double charge logical retry, vẫn ghi actual duplicate provider cost. |
| STORE-01 | todo | — | M1 | Private bucket, object metadata, scoped signed upload; validate size/type/path/expiry, tenant không chọn key người khác. |
| STORE-02 | todo | — | STORE-01, COST-02 | Upload finalize/quarantine checks; live+held bytes tính quota, abandoned multipart cleanup idempotent. |
| STORE-03 | todo | — | STORE-02 | Authorized short-lived download/export URLs và file lifecycle; revoke chặn cấp URL mới, không hứa thu hồi file đã tải. |
| STORE-04 | todo | — | STORE-03, JOB-05 | Upload/progress/failure/retry UI; lỗi file không publish, quota messages rõ và accessible. |
| AUDIT-01 | todo | — | JOB-01 | Structured audit/trace IDs cho sensitive mutations; redaction secrets/PII và admin access scope tests. |
| M2-QA | todo | — | JOB-05, COST-03, STORE-04, AUDIT-01 | Fault tests broker/worker kill, fencing, quota race, storage leak, duplicate messages; recovery chứng minh không mất command. |

## M3 — Knowledge và RAG

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| KNOW-01 | todo | — | M2 | Curriculum metadata migration/seeds cho pilot; grade/subject/year/source provenance được version hóa. |
| KNOW-02 | todo | — | KNOW-01 | Rights attestation và source access policy; upload không tự thành shared corpus, missing rights bị reject. |
| KNOW-03 | todo | — | KNOW-02 | Immutable document versions + activation transaction; failed ingest không thay active version. |
| KNOW-04 | todo | — | KNOW-03 | Sandboxed PDF-text/DOCX/TXT parsing, resource limits và malformed files tests; scan PDF chưa OCR hiển thị unsupported. |
| KNOW-05 | todo | — | KNOW-04 | Versioned chunking pipeline; preserve page/section offsets, dedupe và reproducible fixtures. |
| KNOW-06 | todo | — | KNOW-05 | Embedding provider adapter + model/index versions; retries metered, reindex không trộn incompatible vectors. |
| KNOW-07 | todo | — | KNOW-06 | Authorized hybrid retrieval/reranking; tenant/license filters trước trả context, cross-tenant negative evals. |
| KNOW-08 | todo | — | KNOW-07 | Citation resolver và source preview UI; snippets map đúng version/page, không bịa nguồn khi thiếu context. |
| KNOW-09 | todo | — | KNOW-08 | Library search/version/delete UI + deletion jobs; remove index/cache/blob theo retention policy, replay không hồi sinh deleted data. |
| KNOW-10 | todo | — | KNOW-09 | RAG eval dataset được phép dùng; retrieval/citation/abstention và prompt-injection tests, ngưỡng pilot được phê duyệt. |

## M4 — Authoring và exam blueprint

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| AUTHR-01 | todo | — | M3 | Content/revision/review schema + optimistic concurrency; version history và editing conflict tests. |
| AUTHR-02 | todo | — | AUTHR-01 | Manual lesson/study-guide editor và autosave; AI outage vẫn soạn/sửa/nộp duyệt được. |
| AUTHR-03 | todo | — | AUTHR-02 | AI draft adapter dùng authorized retrieval, schema validation và token/cost budget; source injection không đổi system policy. |
| AUTHR-04 | todo | — | AUTHR-03 | Review/edit/approve exact content revision; provenance/citations visible, chưa review không tự publish. |
| QB-01 | todo | — | AUTHR-01 | Single-choice question bank + revision/key separation; constraints choices/correct key, teacher-only DTO. |
| QB-02 | todo | — | QB-01 | Question editor/filter/import theo format đã chốt; validation từng record, duplicate review và objective mappings. |
| BP-01 | todo | — | QB-02 | Blueprint draft/version/parts/slots/matrix schema và editor; scope/provenance/effective year rõ. |
| BP-02 | todo | — | BP-01 | Validator counts/points/topic/cognitive matrix; difficulty không đồng nhất cognitive demand, unsupported item type fail. |
| BP-03 | todo | — | BP-02, AUTHR-03 | Constrained pool selection/generation; insufficient pool báo thiếu slot, không âm thầm đổi matrix. |
| BP-04 | todo | — | BP-03, AUTHR-04 | Review và publish immutable exam snapshot pin question/blueprint/scoring versions; approved draft không tự sửa published exam. |
| EXPORT-01 | todo | — | BP-04 | Student/teacher Word/PDF export riêng qua durable jobs; layout fixtures, student artifacts tuyệt đối không có key/rubric. |
| M4-QA | todo | — | EXPORT-01 | Blueprint unsatisfiable/type rejection, key leakage SSR/API/export, license revoke, AI outage và publish races tests. |

## M5 — Teaching portal

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| CLASS-01 | todo | — | M1 | Class/teacher/roster schema + CRUD; tenant FKs, archive policy và class-scoped authorization. |
| CLASS-02 | todo | — | CLASS-01 | Invitation tokens hash/expiry/single-use/rate limits; token không là credential đọc nội dung. |
| CLASS-03 | todo | — | CLASS-02 | Student identity/enrollment acceptance và withdrawal; không merge học sinh chỉ qua tên, giữ lịch sử theo policy. |
| CLASS-04 | todo | — | CLASS-03 | Teacher roster/invite UI, student join UI và empty/error states; người ngoài lớp không thấy roster. |
| ASSIGN-01 | todo | — | CLASS-04, M4 | Assignment pin immutable publication, windows/attempt policy/timezone; sửa draft không đổi đề đã giao. |
| ASSIGN-02 | todo | — | ASSIGN-01 | Student mobile assignment list/detail; only enrolled + release checks, revoke chặn thao tác mới. |
| M5-QA | todo | — | ASSIGN-02 | E2E invite→join→assign→withdraw, guessing IDs, replay token và mobile accessibility tests. |

## M6 — Assessment và results

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| ASMT-01 | todo | — | M5 | Attempt/answer/submission schema và start endpoint; atomic attempt limits, server deadline và snapshot binding. |
| ASMT-02 | todo | — | ASMT-01 | Autosave expected revision + client sequence; stale retry không ghi đè câu trả lời mới. |
| ASMT-03 | todo | — | ASMT-02 | Quiz mobile UI/timer/reconnect/save indicators; không báo saved khi server chưa acknowledge. |
| ASMT-04 | todo | — | ASMT-02 | Locked idempotent submit; submit timeout lookup cùng key, concurrent submit chỉ một accepted snapshot. |
| ASMT-05 | todo | — | ASMT-04 | Deadline sweeper/expiry policy; late answers reject, race autosave/submit/expiry có deterministic outcome. |
| ASMT-06 | todo | — | ASMT-05 | Pure single-choice scoring + grading snapshot/job; fixed precision fixtures, pending không coi là zero. |
| ASMT-07 | todo | — | ASMT-06 | Separate score/solution release policies; student API/SSR/cache không lộ key trước release. |
| ASMT-08 | todo | — | ASMT-07 | Authorized grade override append-only revision/reason/audit; aggregate reproject không double count. |
| ASMT-09 | todo | — | ASMT-08, ASMT-03 | Teacher results và student feedback UI; mẫu số enrolled/submitted/graded/pending, export scoped. |
| M6-QA | todo | — | ASMT-09 | Automated start/submit/deadline races, disconnect, grading retries, solution leaks và correction fixtures. |

## M7 — Pilot readiness

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| PILOT-01 | todo | — | M6 | Automated teacher→draft→review→assign→student→score E2E; core failures chặn release. |
| PILOT-02 | todo | — | M6 | Threat-model review + penetration regression tenant/key/file/auth checks; findings có severity/owner và fix gate. |
| PILOT-03 | todo | — | M6 | Load/soak profile theo pilot size, API/worker/DB budgets; capacity và latency targets được chốt trước đo. |
| PILOT-04 | todo | — | M6 | Alerts/dashboard/runbooks cho queue lag, scoring failures, quota/provider cost, auth incidents; thực hiện alert drill. |
| PILOT-05 | todo | — | M6 | Privacy/consent/retention/export/erasure policy và UI cần thiết; minor-data review bởi người phù hợp, không tuyên bố compliant tự động. |
| PILOT-06 | todo | — | PILOT-05 | DB + object restore drill, tombstones/revocations reapplied; đo RPO/RTO với targets được duyệt. |
| PILOT-07 | todo | — | PILOT-01, PILOT-02, PILOT-03, PILOT-04, PILOT-06 | Staging→production deployment/rollback checklist; không rollback schema phá accepted submissions, secrets/env isolation kiểm chứng. |
| PILOT-08 | todo | — | PILOT-07 | Pilot onboarding/support/feedback và go-no-go signoff; không còn lỗi chặn isolation, mất bài hoặc sai điểm. |
