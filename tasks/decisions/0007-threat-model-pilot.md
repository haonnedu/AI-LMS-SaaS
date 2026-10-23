# 0007 — Threat model cho pilot (PILOT-02)

> Ngày: 2026-10-23. Trạng thái: **Đề xuất, chờ review bảo mật bởi người thứ hai.** Owner: —.
> Phạm vi: code trên nhánh `feat/m5-m6-ui-m7-pilot-readiness` (migrations 0001–0011, backend FastAPI/Celery, BFF Next.js, `compose.staging.yaml`). Số dòng `file:line` là ở thời điểm viết; khi code đổi, cập nhật bảng hoặc tham chiếu theo tên hàm.
> Đây là phân tích tĩnh + đối chiếu test hiện có. **Chưa có pentest thực tế nào** trên staging; mọi test integration (gắn với `AUTH_TEST_DATABASE_URL`) bị skip trên máy dev Windows và CI chỉ chạy một phần (xem mục 5).

Thang mức độ: **Cao** = lộ dữ liệu chéo tenant/đáp án/điểm hoặc mất bài; **Trung bình** = cần điều kiện tiên quyết (lỗi khác, nội gián) hoặc ảnh hưởng khả dụng pilot; **Thấp** = phòng thủ chiều sâu.
Cột "Test": tệp test bao phủ; `(PG)` = cần PostgreSQL thật qua `AUTH_TEST_DATABASE_URL`; `(E2E)` = Playwright với OIDC fixture; `—` = chưa có.

## 1. Ranh giới tin cậy

```
Trình duyệt ──cookie eduvia_session (httpOnly, SameSite=Lax)──► Next.js BFF ──Bearer JWT RS256──► FastAPI (eduvia_runtime)
                                   │ Redis "sessions" (AES-256-GCM)                    │ set_config(edu.issuer/subject, workspace) ─► PostgreSQL FORCE RLS
                                   └ Auth0 (OIDC, refresh)                              └ Celery (Redis broker, chỉ job id) ─► worker (cùng role, context từ edu.job_actor)
                                                                                         └ S3/MinIO (presigned GET ≤ 300 s), LLM/embedding provider (HTTPS)
```

Giả định then chốt: **PostgreSQL tin các GUC giao dịch** (`edu.issuer`, `edu.subject`, `edu.current_workspace_id`, `edu.current_user_id`). Chỉ API/worker đặt chúng sau khi xác minh JWT hoặc đọc actor đã lưu của job. Bất kỳ ai thực thi SQL tùy ý bằng `eduvia_runtime` đều có thể tự xưng là bất kỳ identity nào → RLS là lớp phòng thủ chống lỗi lập trình (quên filter, IDOR), **không** chống được SQL injection/RCE trong API.

## 2. Bảng STRIDE

### 2.1 Auth0 / phiên BFF

| ID | STRIDE | Mối đe dọa | Kiểm soát trong code | Rủi ro còn lại | Mức | Owner | Test |
|---|---|---|---|---|---|---|---|
| A1 | S | Token giả/ký sai thuật toán, `alg=none`, đổi issuer/audience | `backend/app/core/auth.py:25-49` chỉ RS256, `kid` bắt buộc, issuer/audience/`exp`/`iat` bắt buộc, JWKS endpoint cố định, token ≤ 16 KiB | Leeway 30 s; JWKS cache 300 s → khóa bị thu hồi còn hiệu lực tối đa ~5 phút | Thấp | — | `backend/tests/test_auth.py` |
| A2 | S | Đánh cắp cookie phiên → dùng lại | Cookie httpOnly, SameSite=Lax, Secure khi origin https (`frontend/src/lib/server/auth.ts:25`); phiên lưu server-side Redis mã hóa AES-256-GCM (`frontend/src/lib/server/session-store.ts:29`); TTL tuyệt đối 24 h / không hoạt động 2 h; logout xóa phiên → cookie replay bị từ chối | Không gắn phiên với thiết bị/IP; trong 2 h cookie bị lộ vẫn dùng được | Trung bình | — | `frontend/tests/auth/login.spec.ts` (E2E: replay sau logout, phiên hết hạn) |
| A3 | T | CSRF trên route ghi của BFF | `checkCsrf` so Origin chính xác + token đồng bộ timing-safe (`frontend/src/lib/server/auth.ts:60-66`), áp cho mọi method ≠ GET (`auth.ts:88`) | GET phải luôn an toàn (không side effect) — chưa có test tĩnh nào khẳng định mọi BFF `GET` chỉ gọi backend `GET` | Thấp | — | `frontend/tests/auth/login.spec.ts`, `frontend/tests/bff-helpers.test.mjs` |
| A4 | E | Open redirect / redirect_uri giả ở callback | `frontend/src/proxy.ts` + test callback giả mạo | — | Thấp | — | `login.spec.ts` "invalid callback and external return URL" (E2E) |
| A5 | S | Email chưa xác minh tạo workspace/nhận lời mời | `requireSession(verified=true)` (`auth.ts:53-58`); backend `bootstrap_identity` yêu cầu identity đã xác minh | Phụ thuộc claim `email_verified` của Auth0 Action (`deploy/auth0/post-login.js`) | Thấp | — | `login.spec.ts` (E2E), `backend/tests/test_identity_integration.py` (PG) |
| A6 | R | Không truy vết hành động nhạy cảm | Audit JSON một dòng, redact token/secret/email/url/key (`backend/app/core/audit.py:16-28`) | Audit chỉ là log stdout xoay vòng 3×10 MiB; không bảng audit, không chống sửa, không log tập trung | Trung bình | — | `backend/tests/test_audit.py` |
| A7 | I | Thiếu CSP/HSTS → XSS khuếch đại, hạ cấp HTTPS | Header hiện có: nosniff, `X-Frame-Options: DENY`, Referrer-Policy, Permissions-Policy (`frontend/next.config.ts`) | **Không có Content-Security-Policy và Strict-Transport-Security**; staging chạy loopback/SSH tunnel nên HSTS phải đặt ở reverse proxy khi public | Trung bình | — | — |

### 2.2 Cô lập tenant bằng RLS

| ID | STRIDE | Mối đe dọa | Kiểm soát trong code | Rủi ro còn lại | Mức | Owner | Test |
|---|---|---|---|---|---|---|---|
| R1 | I/E | IDOR: đổi `workspace_id`/id tài nguyên để đọc tenant khác | `workspace_transaction` kiểm membership active rồi mới đặt context, trả 404 thay vì 403 (`backend/app/api/workspace_access.py:30-55`); mọi bảng 0005–0011 ENABLE+FORCE RLS với predicate `workspace_id = current_setting(...) AND edu.can_read_workspace(...)`; FK composite `(workspace_id, id)` | Không có | Cao (nếu hỏng) | — | `backend/tests/test_qa_gates.py` (FORCE RLS, 401/404), `test_classes_integration.py`, `test_jobs_integration.py`, `test_knowledge_integration.py`, `test_knowledge_retrieval_integration.py`, `test_authoring_integration.py`, `test_assessment_integration.py` (PG) |
| R2 | E | Thiếu context → policy rơi về "thấy hết" | Predicate so sánh với `current_setting(..., true)`; chuỗi rỗng không khớp UUID nào; `can_read_workspace` dựa trên `edu.actor_id()` | — | Cao (nếu hỏng) | — | `backend/tests/test_identity_integration.py` (PG), `deploy/test/rls-smoke.sql` |
| R3 | E | Role runtime có BYPASSRLS/owner → RLS vô hiệu | `deploy/postgres/bootstrap.sql`: runtime `NOBYPASSRLS`, không sở hữu bảng, không `CREATE` trên schema; migration REVOKE ALL rồi GRANT tập tối thiểu | Admin `postgres` và `eduvia_migrator` (owner) vẫn bỏ qua RLS — chỉ dùng cho migration/vận hành | Trung bình | — | `test_identity_integration.py::test_runtime_cannot_change_roles_and_rollback` (PG), `backend/tests/test_migration_00*.py` |
| R4 | S/E | SQL injection hoặc RCE trong API → tự đặt GUC identity | Truy vấn tham số hóa SQLAlchemy; `set_config` nhận bind params (`backend/app/infrastructure/context.py:10-34`) | **Rủi ro kiến trúc chấp nhận**: GUC là nguồn tin cậy; không có chữ ký/khóa phiên DB | Cao | — | — (cần SAST/dependency scan) |
| R5 | I | Cache SSR/BFF trả dữ liệu người khác | BFF gửi `cache: "no-store"` (`auth.ts:103`), backend `Cache-Control: no-store` trên lỗi | Chưa có test cho mọi route mới | Thấp | — | `frontend/tests/bff-helpers.test.mjs` |
| R6 | E | Membership bị thu hồi nhưng job/phiên cũ vẫn chạy | Worker dựng lại context từ `edu.job_actor` + `can_read_workspace` mỗi lần chạy (`backend/app/tasks/jobs.py:280-294`) → job của thành viên bị thu hồi thất bại | Job `attempt.grade` chạy dưới tác giả bài giao; nếu tác giả bị thu hồi, chấm điểm treo (xem runbook scoring-failures) | Trung bình | — | `test_identity_integration.py::test_isolation_revocation_and_pool` (PG) |

### 2.3 Bề mặt SECURITY DEFINER

Tất cả function thuộc sở hữu role NOLOGIN `eduvia_identity_owner` (không BYPASSRLS), `SET search_path=pg_catalog,edu`, `REVOKE ALL ... FROM PUBLIC`, chỉ GRANT EXECUTE cho `eduvia_runtime`. Bảng chi tiết ở mục 3.

| ID | STRIDE | Mối đe dọa | Kiểm soát | Rủi ro còn lại | Mức | Owner | Test |
|---|---|---|---|---|---|---|---|
| D1 | E | Search-path hijack trong definer | `SET search_path=pg_catalog,edu` trên mọi definer; runtime không có `CREATE` trên `edu`; migration REVOKE `CREATE` khỏi owner role sau khi tạo | — | Thấp | — | `backend/tests/test_migration_0005.py` … `test_migration_0011.py` |
| D2 | E | Gọi function "chỉ dành cho worker" từ API | — | **API và worker dùng chung `eduvia_runtime`**: `edu.job_actor` (ánh xạ job id → workspace/user/issuer/subject chéo tenant), `edu.overdue_job_ids`, `edu.expire_attempts`, `edu.apply_due_releases` không kiểm context. Chúng không có route API, và hai function cuối kẹp `p_now` ≤ `clock_timestamp()` | Trung bình | — | `backend/tests/test_attempts_unit.py::test_sweeper_cannot_be_driven_by_a_future_clock` |
| D3 | I | Thành viên workspace bất kỳ vai trò đọc đáp án qua `edu.exam_keys_for_scoring` | Function yêu cầu context + `can_read_workspace` + version đã publish | **Không kiểm vai trò** (thiết kế cho worker chấm). Không có route nào gọi nó cho người dùng; rủi ro chỉ khi có SQL tùy ý (R4) | Thấp | — | `test_generation_integration.py::test_exam_keys_are_only_readable_through_functions` (PG) |
| D4 | E | Học sinh truyền `student_id`/`workspace_id` của người khác | Các `edu.student_*` không nhận id học sinh/workspace; suy ra từ `edu.actor_id()` + `students.user_id` | — | Cao (nếu hỏng) | — | `backend/tests/test_migration_0011.py::test_student_functions_derive_the_student_from_verified_identity`, `test_attempts_unit.py::test_another_students_attempt_is_not_found`, `test_assessment_integration.py` (PG) |

### 2.4 Đáp án (answer keys)

| ID | STRIDE | Mối đe dọa | Kiểm soát | Rủi ro còn lại | Mức | Owner | Test |
|---|---|---|---|---|---|---|---|
| K1 | I | Đáp án lộ qua DTO học sinh/API | DTO học sinh không có trường key/explanation (`backend/app/api/student.py:46-48`, `generation.py:172-180`); `ResultItemDTO.solution` nullable chỉ được DB điền sau `solutions_released_at` (`0011_assessment.py:826-900`) | — | Cao (nếu hỏng) | — | `backend/tests/test_qa_gates.py` (quét OpenAPI), `test_assessment_api.py::test_student_dtos_have_no_key_or_explanation_fields`, `::test_student_results_before_release_contain_no_key` |
| K2 | I | Đáp án lộ qua JOIN vô tình | `question_keys`/`exam_answer_keys`: runtime chỉ INSERT, **không SELECT** (`0009_authoring.py` grants, `0010_generation_exams.py` grants); đọc qua `edu.question_key`, `edu.exam_item_key`, `edu.exam_item_explanation` (kiểm vai trò owner/admin/teacher) | — | Cao (nếu hỏng) | — | `test_qa_gates.py` (không DELETE, REVOKE ALL), `test_authoring_integration.py::test_question_keys_only_via_definer_function` (PG), `test_generation_integration.py` (PG) |
| K3 | I | Đáp án lộ qua export học sinh | CSV học sinh dùng `STUDENT_EXPORT_COLUMNS` (`backend/app/services/question_bank.py:68`, `:344`); đề học sinh dựng bởi `student_exam_document` (`backend/app/services/exports.py:199`) không đọc key | — | Cao (nếu hỏng) | — | `test_qa_gates.py::test_student_question_export_has_no_key_columns`, `backend/tests/test_export_render_unit.py` |
| K4 | I | Đáp án lộ qua log | Prompt/nguồn/output không ghi log (`generation.py` docstring); audit redact khóa `key` (`audit.py:18`) | Log ứng dụng khác chưa có test quét | Thấp | — | `test_audit.py` |
| K5 | T | Sửa đáp án/điểm sau publish | Trigger bất biến: `exam_snapshot_guard`, `exam_version_guard`, `grade_guard` (append-only), `assignment_guard` (khóa pin khi publish) | Override điểm hợp lệ qua API có lý do bắt buộc | Thấp | — | `test_generation_integration.py::test_published_snapshot_is_immutable_and_publication_revalidated`, `test_assessment_integration.py::test_published_pin_is_immutable` (PG) |

### 2.5 Tải lên và parse tệp

| ID | STRIDE | Mối đe dọa | Kiểm soát | Rủi ro còn lại | Mức | Owner | Test |
|---|---|---|---|---|---|---|---|
| U1 | D | Tệp quá lớn | Giới hạn khai báo + đếm luồng (`backend/app/services/storage.py:74-110`, `backend/app/api/documents.py:132-152`), mặc định 25 MiB, tối đa 100 MiB | BFF stream không giới hạn riêng; dựa vào backend | Thấp | — | `backend/tests/test_storage_unit.py` |
| U2 | T | Giả MIME / đuôi tệp | Allowlist MIME + đuôi khớp + magic bytes (`storage.py:26-66`, `:119-126`) | — | Thấp | — | `test_storage_unit.py::test_magic_bytes` |
| U3 | D/E | Zip bomb, XXE, entity expansion trong DOCX; PDF độc | Giới hạn zip entries/tổng/tỉ lệ (`backend/app/services/parsing.py:29-36`), từ chối `<!DOCTYPE`/`<!ENTITY` (`parsing.py:174`), timeout 30 s bằng thread (`parsing.py:385`), giới hạn trang/ký tự | **Không sandbox OS** (không seccomp/rlimit/subprocess); thread quá hạn không bị kill, chỉ Celery hard limit 360 s. `pypdf` **không có trong dependencies** → PDF luôn `unsupported` (an toàn nhưng là lỗi chức năng) | Trung bình | — | `backend/tests/test_parsing_unit.py` |
| U4 | I | Tên tệp/đường dẫn điều khiển object key | Object key do server sinh `ws/{workspace}/doc/{id}` + CHECK trong DB (`0006_jobs_storage.py`) | — | Thấp | — | `test_storage_unit.py::test_object_key_is_server_derived` |
| U5 | — | Tài liệu chứa dữ liệu học sinh bị gửi provider | Không có quét PII | Xem ADR 0008 mục 5 | Trung bình | — | — |

### 2.6 Signed URL

| ID | STRIDE | Mối đe dọa | Kiểm soát | Rủi ro còn lại | Mức | Owner | Test |
|---|---|---|---|---|---|---|---|
| S1 | I | URL tải bị chia sẻ/lộ qua log/Referer | Presigned GET TTL ≤ 300 s, `attachment` + content-type cố định (`storage.py:200-218`); cấp sau `workspace_transaction` (`documents.py:267`, `generation.py:762`); audit redact `url`/`signed_url` | URL dùng lại được trong TTL bởi bất kỳ ai có link; không ràng buộc IP | Thấp | — | `test_storage_unit.py::test_presigned_download_is_short_lived_attachment` |
| S2 | I | Bucket public / metadata credentials | Staging: S3 chưa cấu hình, endpoint rỗng → fail closed; `AWS_EC2_METADATA_DISABLED` (`compose.staging.yaml`) | Chưa có bucket policy/versioning/lifecycle được review | Trung bình | — | — |

### 2.7 Prompt injection qua nguồn RAG

| ID | STRIDE | Mối đe dọa | Kiểm soát | Rủi ro còn lại | Mức | Owner | Test |
|---|---|---|---|---|---|---|---|
| P1 | T | Văn bản trong tài liệu ra lệnh cho LLM ("bỏ qua hướng dẫn…") | System prompt cố định khai báo nguồn là dữ liệu không tin cậy; chunk nằm trong `<source id="[n]">` với `<`/`>` được escape (`backend/app/services/generation.py:11-18`, `:268-272`); output phải qua schema check thuần Python | LLM vẫn có thể bị ảnh hưởng nội dung; giáo viên **bắt buộc review** — bản nháp không bao giờ tự publish | Trung bình | — | `test_generation_unit.py::test_system_prompt_is_constant_and_sources_stay_in_tags`, `::test_teacher_parameters_are_escaped_and_no_file_names` |
| P2 | T | Trích dẫn bịa/ngoài tập nguồn | Citation ánh xạ về chunk đã truy xuất; ngoài tập → bị bỏ và đánh dấu `invalid` (`generation.py:445-451`) | — | Thấp | — | `test_generation_unit.py::test_citation_outside_sources_is_stripped_and_marked_invalid` |
| P3 | I | Truy xuất nguồn của tenant khác vào prompt | Retrieval chạy trong context job, cùng SQL được ủy quyền (`backend/app/services/retrieval.py`) | — | Cao (nếu hỏng) | — | `test_knowledge_retrieval_integration.py::test_tenant_a_never_sees_tenant_b_chunks` (PG), `test_generation_unit.py::test_retrieval_reuses_authorized_sql` |
| P4 | — | Fake provider chạy ở production | `llm.py:314-320` từ chối fake ở production; settings từ chối embedder `local` ở production (`backend/app/core/config.py:171-172`) | Xem phát hiện F1 mục 6 | Thấp | — | `backend/tests/test_llm_unit.py`, `test_settings.py` |

### 2.8 Worker / replay job

| ID | STRIDE | Mối đe dọa | Kiểm soát | Rủi ro còn lại | Mức | Owner | Test |
|---|---|---|---|---|---|---|---|
| J1 | T | Message trùng/replay chạy job hai lần | `background_jobs` là nguồn sự thật; claim có lease 5 phút + số attempt, ghi stage idempotent theo attempt (`backend/app/services/jobs.py:27`, `:202-227`); `acks_late` + `reject_on_worker_lost` (`backend/app/tasks/jobs.py:469-470`) | Không có fencing token ở mức stage ngoài DB (ví dụ object đã ghi) — chấp nhận ở bản gọn (IMPLEMENTATION_PLAN 3.4) | Thấp | — | `backend/tests/test_jobs_unit.py`, `test_jobs_integration.py::test_worker_executes_under_job_context_and_sweeper_recovers` (PG) |
| J2 | T | Idempotency key dùng lại với payload khác | So `request_hash`, trả 409 (`jobs.py:113`), unique `(workspace, user, key)` | — | Thấp | — | `test_jobs_unit.py::test_enqueue_duplicate_different_request_conflicts`, `test_jobs_integration.py` (PG) |
| J3 | S | Message broker giả mạo chạy job của tenant khác | Message chỉ chứa job id; actor/context lấy từ DB (`tasks/jobs.py:280-294`) | Redis broker có mật khẩu và mạng internal; ai ghi được broker chỉ có thể kích hoạt job đã tồn tại | Thấp | — | `test_jobs_unit.py::test_worker_honours_cancel_and_missing_actor` |
| J4 | T | Nộp bài trùng/đua với hạn chót | Advisory lock + partial unique một attempt `in_progress`; khóa hàng attempt; `finalize_attempt` một đường duy nhất; ân hạn 5 s | — | Cao (nếu hỏng) | — | `test_attempts_unit.py`, `test_migration_0011.py::test_single_finalization_path`, `test_assessment_integration.py::test_late_answer_rejected_and_sweeper_expires` (PG) |
| J5 | D | Sweeper không chạy → job treo, attempt quá hạn không được chốt, release `after_close` không xảy ra | Beat lên lịch `app.tasks.jobs.sweep` mỗi 60 s (`backend/app/worker.py:31-33`) | **`compose.staging.yaml` không chạy beat** (worker không có `--beat`, không có service beat) — xem F2 | Cao | — | `deploy/alerts/check.py` (alert `attempts_in_progress_past_deadline`, `queue_lag_seconds`) |

### 2.9 Rate limit và quota

| ID | STRIDE | Mối đe dọa | Kiểm soát | Rủi ro còn lại | Mức | Owner | Test |
|---|---|---|---|---|---|---|---|
| L1 | D/S | Dò token mời | Token ngẫu nhiên, chỉ lưu sha256; token bucket 5/(IP, 8 ký tự đầu token) và 30/IP (`backend/app/api/classes.py:213-226`) | **Bộ đếm trong bộ nhớ từng process**, không chia sẻ giữa worker uvicorn/restart; **IP là peer trực tiếp — sau BFF mọi request có cùng IP của container frontend**, nên giới hạn thành toàn cục: cả lớp 40 học sinh dùng chung một token → chỉ 5 lần join đầu qua ngay, sau đó 1 lần/12 s (xem F3) | Cao (khả dụng pilot) | — | `backend/tests/test_classes_unit.py::test_accept_is_rate_limited_per_ip_and_token_prefix` |
| L2 | D | Lạm dụng AI/upload tốn chi phí | Cap cứng theo tháng, khóa hàng quota `FOR UPDATE` (`backend/app/services/usage.py:45-70`) | Không giới hạn tốc độ theo người dùng; một giáo viên có thể tiêu hết quota workspace | Trung bình | — | `test_jobs_integration.py::test_quota_cap_blocks_concurrent_overflow` (PG), `test_generation_unit.py::test_quota_and_budget_refusals_do_not_call_provider` |
| L3 | D | Spam autosave/start/submit | Idempotency + `client_sequence`; không có rate limit | Một học sinh có thể tạo tải ghi cao | Thấp | — | `test_attempts_unit.py` |
| L4 | D | Gửi lại email xác minh | Cooldown + hạn mức giờ trong Redis (BFF) | — | Thấp | — | `login.spec.ts` (E2E) |

## 3. Kiểm kê SECURITY DEFINER (migrations 0004–0011)

**25 function SECURITY DEFINER** (cộng 3 helper invoker do owner role sở hữu, chỉ chạy bên trong definer). Function `edu.is_active_member` của 0003 đã bị xóa ở 0004.

| # | Function | Migration:dòng | Caller | Kiểm tra thực hiện |
|---|---|---|---|---|
| 1 | `edu.actor_id()` | 0004:82 | RLS policy, mọi definer khác, `backend/app/services/attempts.py` | Trả user active khớp `edu.issuer`+`edu.subject`; NULL nếu không |
| 2 | `edu.can_read_workspace(uuid)` | 0004:88 | Mọi tenant policy, definer khác | Actor có membership `active` trong workspace `is_active` |
| 3 | `edu.bootstrap_identity(text,text)` | 0004:101 | `backend/app/services/user_provisioning.py:13` | Bắt buộc issuer/subject/email; từ chối user bị vô hiệu; không hồi sinh workspace/membership bị thu hồi |
| 4 | `edu.workspace_staff_role(uuid,uuid)` | 0005:160 | `backend/app/services/classes.py:252`, `content.py:218` | Workspace = context hiện tại + `can_read_workspace`; chỉ trả role staff active |
| 5 | `edu.accept_class_invitation(bytea)` | 0005:172 | `backend/app/services/classes.py:439` (route `POST /v1/invitations/{token}/accept`) | Actor bắt buộc; khóa hàng lời mời; hết hạn/thu hồi/hết lượt; lớp và workspace active; học sinh inactive/đã bị rút bởi chính lời mời → từ chối; idempotent khi đã active |
| 6 | `edu.job_actor(uuid)` | 0006:126 | `backend/app/tasks/jobs.py:282` (worker) | Chỉ user `is_active`; **không kiểm context** (D2) |
| 7 | `edu.overdue_job_ids(timestamptz,timestamptz,int)` | 0006:136 | `backend/app/tasks/jobs.py:381` (sweeper) | Chỉ trả id; limit 1..500; **không kiểm context** |
| 8 | `edu.provision_workspace_quota()` | 0006:149 | Trigger `AFTER INSERT ON edu.workspaces` | Chèn một hàng quota mặc định, `ON CONFLICT DO NOTHING` |
| 9 | `edu.purge_document_chunks(uuid)` | 0008:168 | `backend/app/tasks/jobs.py:225` (job `document.delete`) | Document thuộc workspace context + `can_read_workspace`; document phải `deleted`; owner không có bypass policy nên RLS vẫn áp |
| 10 | `edu.question_key(uuid)` | 0009:423 | `backend/app/services/question_bank.py:361`, `:740` | Context + `can_read_workspace` + actor là owner/admin/teacher active |
| 11 | `edu.workspace_staff_count(uuid)` | 0009:438 | `backend/app/services/content.py:211` | Context + `can_read_workspace`; NULL ngoài context |
| 12 | `edu.exam_item_key(uuid)` | 0010:348 | `backend/app/services/exam_builder.py:225`, `exports.py:222` | Như #10 |
| 13 | `edu.exam_item_explanation(uuid)` | 0010:362 | `backend/app/services/exam_builder.py:230`, `exports.py:223` | Như #10 |
| 14 | `edu.exam_keys_for_scoring(uuid)` | 0010:377 | `backend/app/services/scoring.py:244`, `assignments.py:612` | Context + `can_read_workspace` + version đã publish; **không kiểm vai trò** (D3) |
| 15 | `edu.exam_version_publish_error(uuid)` | 0010:406 | Trigger `edu.exam_version_guard` khi publish | Context + `can_read_workspace`; chỉ trả mã lỗi |
| 16 | `edu.student_assignments()` | 0011:489 | `backend/app/services/attempts.py:293` | Học sinh từ `actor_id`; enrollment active; workspace active; bài `published/closed`; ≤ 200 |
| 17 | `edu.student_assignment_detail(uuid)` | 0011:522 | `attempts.py:300` | Như #16 cho một bài |
| 18 | `edu.student_attempt(uuid)` | 0011:560 | `attempts.py:337` | Attempt thuộc học sinh (`assessment_actor_student`) |
| 19 | `edu.student_attempt_items(uuid)` | 0011:576 | `attempts.py:343` | Như #18; choices dựng lại chỉ `{key,text}`, không đọc bảng key |
| 20 | `edu.student_start_attempt(uuid,text,text)` | 0011:598 | `attempts.py:314` | Actor; idempotency key/hash (EV011); enrollment/lớp/cửa sổ (EV012); số lần (EV013); advisory lock |
| 21 | `edu.student_save_answer(uuid,uuid,text,int,bigint)` | 0011:684 | `attempts.py:390` | Attempt của học sinh, `in_progress`, hạn + 5 s (EV010), lựa chọn thuộc item (EV016), chống ghi cũ (EV014), khóa hàng |
| 22 | `edu.student_submit(uuid,text,text)` | 0011:778 | `attempts.py:407` | Attempt của học sinh; idempotent theo key/hash; gọi `finalize_attempt` |
| 23 | `edu.student_results(uuid)` | 0011:826 | `attempts.py:429`, `backend/app/services/releases.py` | Attempt của học sinh; điểm chỉ từ grade đã release; đáp án/giải thích chỉ khi `solutions_released_at` và attempt đã nộp |
| 24 | `edu.expire_attempts(timestamptz)` | 0011:904 | `attempts.py:439` (sweeper) | `p_now` kẹp ≤ thời gian thực; `SKIP LOCKED`; ≤ 500; **không kiểm context** |
| 25 | `edu.apply_due_releases(timestamptz)` | 0011:925 | `backend/app/services/releases.py:134` (sweeper) | Như #24; solutions chỉ khi không còn attempt `in_progress` |
| h1 | `edu.assessment_actor_student(uuid)` (invoker) | 0011:428 | Bên trong #18–#23 | Học sinh active của actor trong workspace active |
| h2 | `edu.attempt_snapshot_sha256(uuid)` (invoker) | 0011:438 | `finalize_attempt` | Snapshot chuẩn khớp `backend/app/services/scoring.py` |
| h3 | `edu.finalize_attempt(...)` (invoker) | 0011:449 | #22, #24 | Chỉ khi `in_progress` dưới khóa; enqueue đúng một job `attempt.grade` (idempotency hệ thống) |

## 4. Danh mục kiểm thử hồi quy xâm nhập (penetration regression checklist)

Chạy trước mỗi release staging→production (`deploy/CHECKLIST-release.md`). "Có" = đã có test tự động; "Thiếu" = phải bổ sung hoặc làm thủ công.

| # | Kiểm tra | Tự động hóa | Trạng thái |
|---|---|---|---|
| 1 | Đổi `workspace_id` sang workspace không phải thành viên → 404 trên mọi route | `test_qa_gates.py` (khai báo 401/404), `test_classes_unit.py::test_workspace_not_member_is_404`, `test_assessment_api.py::test_cross_workspace_teacher_routes_are_404` | Có (unit) |
| 2 | Tenant A không đọc/ghi được hàng tenant B bằng role runtime | 7 tệp `*_integration.py` (PG) | Có, **nhưng CI chỉ chạy `test_bootstrap`, `test_identity_integration`, `test_auth`** (mục 5) |
| 3 | Thiếu context/role BYPASSRLS/owner | `test_identity_integration.py` (PG), `deploy/test/rls-smoke.sql` (staging) | Có |
| 4 | Học sinh đoán id attempt/assignment của người khác → 404 | `test_attempts_unit.py::test_another_students_attempt_is_not_found`, `test_assessment_integration.py` (PG) | Có |
| 5 | Không trường key/explanation/rationale/solution trước release (API, export, OpenAPI) | `test_qa_gates.py`, `test_assessment_api.py`, `test_export_render_unit.py` | Có |
| 6 | Runtime không SELECT/DELETE bảng key, không DELETE ledger/chấm điểm | `test_qa_gates.py`, `test_migration_0009/0010/0011.py`; thực thi trên PG: `test_authoring_integration.py`, `test_generation_integration.py` | Có |
| 7 | Lời mời: dùng một lần dưới đồng thời, hết hạn, thu hồi, học sinh bị rút dùng lại token | `test_classes_integration.py` (PG) | Có |
| 8 | Rate limit join lớp khi cả lớp join cùng lúc qua BFF | — | **Thiếu** (F3); cần limiter dùng Redis và IP client tin cậy từ BFF |
| 9 | CSRF/Origin trên mọi BFF mutation, cookie flags, replay sau logout | `frontend/tests/auth/login.spec.ts` (E2E) | Có cho route auth; **thiếu** test vòng lặp mọi route `app/api/backend/**` |
| 10 | Upload: MIME giả, zip bomb, XXE, quá cỡ, trang quá nhiều | `test_storage_unit.py`, `test_parsing_unit.py` | Có (unit); **thiếu** sandbox OS |
| 11 | Signed URL TTL ≤ 300 s, chỉ sau ủy quyền | `test_storage_unit.py` | Có (unit); kiểm trên MinIO thật: thiếu |
| 12 | Prompt injection: nguồn chứa lệnh, thẻ `</source>` | `test_generation_unit.py` | Có (unit, fake provider); với provider thật: thiếu |
| 13 | Replay job, worker chết giữa chừng, lease hết hạn | `test_jobs_unit.py`, `test_jobs_integration.py` (PG) | Có |
| 14 | Đua start/autosave/submit/hạn chót | `test_attempts_unit.py`, `test_assessment_integration.py` (PG) | Có |
| 15 | Sweeper/beat chạy trên staging | `deploy/alerts/check.py` | **Thiếu triển khai** (F2) |
| 16 | CSP/HSTS | — | **Thiếu** (A7) |
| 17 | Dependency/secret scan | — | **Thiếu** trong CI |
| 18 | Hành trình đầy đủ giáo viên→học sinh→điểm | `frontend/tests/e2e/pilot-journey.spec.ts` (E2E, skip mặc định) | Khung có, **chưa chạy** |

## 5. Khoảng trống của bằng chứng

- Job CI `auth-integration` chỉ chạy `tests/test_bootstrap.py tests/test_identity_integration.py tests/test_auth.py` (`.github/workflows/ci.yml`). Các test PG cho classes/jobs/knowledge/retrieval/authoring/generation/assessment **không chạy trong CI** và bị skip trên máy dev không có Docker → hành vi RLS/trigger/definer của 0005–0011 **chưa được kiểm chứng trên PostgreSQL** bởi pipeline.
- Không có pentest thủ công, không DAST, không dependency scan.

## 6. Phát hiện cần sửa (fix gate)

| ID | Phát hiện | Mức | Gate |
|---|---|---|---|
| F1 | `compose.staging.yaml` không truyền `EMBEDDING_PROVIDER`/`EMBEDDING_*`/`LLM_*` cho api/worker. Với `APP_ENV=production`, settings từ chối embedder mặc định `local` → **API/worker không khởi động được** trên staging với tree hiện tại (đã tái hiện bằng `Settings()` cục bộ) | Cao | Chặn deploy |
| F2 | Staging không chạy Celery beat → không sweeper: job mất message không được dispatch lại, attempt quá hạn không được chốt/chấm, release `after_close` không xảy ra | Cao | Chặn pilot |
| F3 | Rate limit nhận lời mời theo IP peer + trong bộ nhớ → sau BFF trở thành giới hạn toàn cục; cả lớp join cùng một token bị 429 | Cao (khả dụng) | Chặn pilot có lớp > 5 học sinh |
| F4 | Mở rộng job CI integration sang mọi `*_integration.py` | Cao (bằng chứng) | Chặn release |
| F5 | Thiếu CSP/HSTS | Trung bình | Trước khi public internet |
| F6 | `pypdf` không có trong dependencies → mọi PDF ingestion trả `unsupported` | Trung bình (chức năng) | Trước pilot nếu giáo viên dùng PDF |
| F7 | Worker-only definer (`job_actor`, `overdue_job_ids`, `expire_attempts`, `apply_due_releases`) callable bởi API (cùng role) | Trung bình | Sau pilot: tách role worker |
| F8 | Audit chỉ là log xoay vòng; không có bảng audit/log tập trung | Trung bình | Trước production |
