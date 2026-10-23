# 0012 — Quyền riêng tư, đồng ý của người giám hộ và lưu giữ dữ liệu (PILOT-05)

> Ngày: 2026-10-23. Trạng thái: **Đề xuất kỹ thuật, chưa được duyệt.** Owner nghiệp vụ/pháp lý: —.
> Phạm vi: dữ liệu do schema `edu` (migrations 0001–0014), Redis phiên, object storage, log và Auth0 nắm giữ ở thời điểm viết.

## 0. Tuyên bố bắt buộc

- **Tài liệu này không khẳng định Eduvia tuân thủ bất kỳ quy định nào.** Nó là bản kiểm kê kỹ thuật và đề xuất để người có chuyên môn pháp lý xem xét.
- **Bắt buộc có review pháp lý** đối chiếu Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân, luật bảo vệ dữ liệu cá nhân hiện hành và hướng dẫn liên quan (đặc biệt: dữ liệu trẻ em, đồng ý của cha mẹ/người giám hộ, chuyển dữ liệu ra nước ngoài khi gọi LLM/embedding provider, hồ sơ đánh giá tác động, nơi lưu trữ, quyền xóa). Không đưa dữ liệu học sinh thật vào hệ thống trước khi có kết luận đó (IMPLEMENTATION_PLAN mục 3.5, mục 10 "Trước M5/M7").
- Mọi thời hạn lưu giữ dưới đây là **đề xuất chờ duyệt**, không phải chính sách đang áp dụng. Hiện tại hệ thống **không tự xóa** bất kỳ dữ liệu học sinh nào.

## 1. Nguyên tắc

1. Tối thiểu hóa: thiết kế không cần ngày sinh, liên hệ phụ huynh hay số định danh nhà nước (ARCHITECTURE mục 12). Không thêm các trường này nếu chưa có quyết định pháp lý.
2. Không gửi định danh học sinh cho provider ở bất kỳ mốc nào (mục 5).
3. Xóa là một workflow: thu hồi truy cập ngay, xóa dữ liệu dẫn xuất/đối tượng bất đồng bộ, pseudonymize khi phải giữ bản ghi, ghi nhận hoàn tất, và **tái áp dụng tombstone sau restore** (PILOT-06).
4. Bản ghi điểm đã chấp nhận (submission, grading result, grade) là append-only theo thiết kế; xóa chúng là quyết định nghiệp vụ/pháp lý, không phải thao tác kỹ thuật thường ngày.

## 2. Kiểm kê dữ liệu theo bảng

Ký hiệu: **PII-HS** = dữ liệu cá nhân học sinh; **PII-GV** = dữ liệu cá nhân giáo viên/người dùng; "Đường xóa" = cơ chế đang tồn tại trong code; "Thiếu" = chưa có.
Bảng này được `backend/tests/test_privacy_inventory.py` đối chiếu với migrations: mọi bảng có cột `email`, `*user_id` hoặc `*student_id` phải có một dòng ở đây và dòng đó phải nêu tên từng cột như vậy.

| Bảng | Cột cá nhân / liên kết người | Loại | Lưu giữ đề xuất (chờ duyệt) | Đường xóa hiện có | Thiếu |
|---|---|---|---|---|---|
| `edu.users` | `email`, `display_name`, `provider_issuer`, `provider_sub` | PII-GV và PII-HS (học sinh cũng là user) | Đến khi tài khoản bị xóa + 30 ngày | Không. Chỉ có `is_active=false` (không qua API). `edu.bootstrap_identity` ghi đè `email`/`display_name` ở mỗi lần đăng nhập | Function SECURITY DEFINER `edu.erase_user` (pseudonymize email/display_name, giữ id), job xóa user Auth0 qua Management API |
| `edu.user_identities` | `user_id`, `issuer`, `subject` | PII-GV và PII-HS (liên kết đăng nhập, migration 0005 của Duc) | Theo vòng đời tài khoản | Không | Xóa alias khi erase user |
| `edu.identity_transfers` | `user_id`, `target_issuer`, `target_subject`, `proof_id` | PII-GV (audit chuyển identity, migration 0006) | 1 năm cho audit | Không | Purge sau hạn |
| `edu.workspaces` | `personal_owner_user_id`, `name` | PII-GV (liên kết) | Theo vòng đời workspace | Không (chỉ `is_active`) | Workflow đóng workspace + xóa dữ liệu tenant |
| `edu.workspace_members` | `user_id`, `role`, `status` | PII-GV (liên kết) | Theo membership; giữ bản ghi thu hồi cho audit | Không có DELETE qua API | — |
| `edu.classes` | `created_by_user_id`, `name` | PII-GV (liên kết) | Năm học + 1 năm | Lưu trữ (`archived`), không xóa | Purge lớp đã lưu trữ quá hạn |
| `edu.class_teachers` | `user_id` | PII-GV (liên kết) | Theo lớp | DELETE co-teacher qua API | — |
| `edu.students` | `user_id`, `display_name`, `external_code`, `status` | **PII-HS** | Năm học + 1 năm, hoặc đến khi có yêu cầu xóa | Không. `display_name` được sao từ `users.display_name` lúc join (`edu.accept_class_invitation`); không đồng bộ khi user đổi tên | Function `edu.erase_student(student_id)` (pseudonymize `display_name`→"Học sinh đã xóa", `external_code`→NULL, `user_id`→NULL) + job |
| `edu.class_invitations` | `created_by_user_id`, `token_hash` (chỉ digest) | PII-GV (liên kết) | 30 ngày sau hết hạn | Không (thu hồi qua `revoked_at`) | Purge lời mời hết hạn |
| `edu.enrollments` | `student_id`, `joined_at`, `withdrawn_at` | **PII-HS** (liên kết) | Theo `students` | Rút học sinh (`withdrawn`), không xóa | Thuộc `edu.erase_student` |
| `edu.background_jobs` | `requested_by_user_id`, `input` (jsonb), `result` | PII-GV (liên kết); `input` của `attempt.grade` chứa `attemptId` | 90 ngày sau khi kết thúc | Không | Purge job đã kết thúc theo tuổi |
| `edu.usage_events` | — (workspace, đơn vị, chi phí) | Không cá nhân | Theo kế toán (đề xuất 2 năm) | Append-only, không xóa (đúng thiết kế) | — |
| `edu.documents` | `owner_user_id`, `file_name`, `object_key` | PII-GV; **nội dung tệp có thể chứa PII-HS** nếu giáo viên tải lên | Đến khi giáo viên xóa | Có: soft delete → job `document.delete` → `edu.purge_document_chunks` xóa chunks/vector, đánh dấu version `withdrawn`, xóa object | Cảnh báo UI "không tải lên tài liệu chứa dữ liệu học sinh"; purge hàng `documents` đã xóa (metadata còn lại) |
| `edu.document_versions` / `edu.document_chunks` / `edu.embedding_runs` | — (nội dung trích từ tài liệu) | Có thể chứa PII nếu tài liệu chứa | Theo tài liệu | Có (qua `edu.purge_document_chunks`) | — |
| `edu.content_items` | `created_by_user_id` | PII-GV (liên kết) | Đến khi giáo viên lưu trữ/xóa | Lưu trữ, không xóa | Workflow xóa nội dung |
| `edu.content_revisions` | `created_by_user_id`, `reviewed_by_user_id`, `body` | PII-GV (liên kết) | Như trên | Không | — |
| `edu.review_requests` | `requested_by_user_id`, `assigned_to_user_id`, `decided_by_user_id`, `comment` | PII-GV | Như trên | Không | — |
| `edu.questions` | `created_by_user_id` | PII-GV (liên kết) | Theo ngân hàng câu hỏi | `retired`, không xóa | — |
| `edu.question_revisions` | `created_by_user_id` | PII-GV (liên kết) | Như trên | Append-only | — |
| `edu.question_keys` | `set_by_user_id` | PII-GV (liên kết), bí mật nội dung | Như trên | Append-only, runtime không SELECT | — |
| `edu.blueprints` | `created_by_user_id` | PII-GV (liên kết) | Như trên | Lưu trữ | — |
| `edu.blueprint_versions` | `created_by_user_id`, `published_by_user_id` | PII-GV (liên kết) | Như trên | Bất biến sau publish | — |
| `edu.generation_jobs` | `requested_by_user_id`, `input`, `output`, `provider_request_id` | PII-GV (liên kết); `input` là tham số giáo viên nhập | 1 năm | Không | Purge `input`/`output` theo tuổi |
| `edu.exams` | `created_by_user_id` | PII-GV (liên kết) | Theo đề | Lưu trữ | — |
| `edu.exam_versions` | `published_by_user_id` | PII-GV (liên kết) | Bất biến sau publish (đề đã giao cần tái lập điểm) | Không | — |
| `edu.export_jobs` | `object_key` (tệp xuất trong bucket) | Không trực tiếp; tệp xuất đề không chứa học sinh | 30 ngày cho tệp | Không | Lifecycle rule xóa object `ws/*/export/*` |
| `edu.assignments` | `created_by_user_id` | PII-GV (liên kết) | Năm học + 1 năm | Lưu trữ | — |
| `edu.quiz_attempts` | `student_id`, thời điểm làm/nộp, `submitted_snapshot_sha256` | **PII-HS** (kết quả học tập) | Năm học + 1 năm (chờ duyệt) | Không có DELETE grant | Thuộc `edu.erase_student`; quyết định giữ điểm ẩn danh hay xóa hẳn |
| `edu.student_answers` | (qua `attempt_id`) `response` | **PII-HS** | Như `quiz_attempts` | Không có DELETE grant | Như trên |
| `edu.grading_results` / `edu.grading_result_items` | `created_by_user_id` (chấm tay), điểm từng câu | **PII-HS** (qua attempt) | Như trên | Append-only (đúng thiết kế) | Như trên |
| `edu.grades` | `approved_by_user_id`, `score`, `reason` | **PII-HS** | Như trên | Append-only trừ `is_current`/`released_at` | Như trên |

Ngoài database:

| Nơi lưu | Dữ liệu | Lưu giữ hiện tại | Ghi chú |
|---|---|---|---|
| Auth0 tenant | Email, mật khẩu (hash do Auth0 giữ), lịch sử đăng nhập | Theo cấu hình tenant | Chưa có job xóa user Auth0. Cấu hình region tenant cần review (chuyển dữ liệu ra nước ngoài) |
| Redis phiên (`sessions`) | Phiên mã hóa AES-256-GCM: token, email, `email_verified` | TTL tuyệt đối 24 h, không hoạt động 2 h (`frontend/src/lib/server/auth.ts`) | Không persistence volume |
| Redis broker | Message chỉ chứa job id | AOF | Không PII |
| Object storage | Tài liệu tải lên, tệp xuất | Đến khi xóa (tài liệu) / không hạn (tệp xuất) | Thiếu lifecycle cho exports; backup object chưa có |
| Log JSON (stdout, Docker) | request id, workspace id, mã lỗi; audit redact token/email/url/key (`backend/app/core/audit.py`) | Docker rotate 3 × 10 MiB / service | Không có log tập trung; cần quyết định retention khi có |
| Backup PostgreSQL | Toàn bộ dữ liệu | **Chưa có backup tự động** | Xem `deploy/restore-drill.sh`; backup phải hết hạn theo chính sách và tombstone phải được tái áp dụng sau restore |

## 3. Luồng đồng ý cho học sinh chưa thành niên (đề xuất)

Hiện tại học sinh tham gia lớp chỉ bằng: tài khoản Auth0 đã xác minh email + mã mời (`POST /v1/invitations/{token}/accept` → `edu.accept_class_invitation`). **Không có bước đồng ý nào.** Trước khi học sinh thật tham gia, sản phẩm cần:

1. **Xác định độ tuổi áp dụng** (do pháp lý chốt). Hệ thống không thu ngày sinh; phương án đề xuất là lớp được giáo viên/nhà trường gắn cờ "học sinh dưới tuổi quy định" thay vì hỏi tuổi từng học sinh.
2. **Ghi nhận đồng ý trước khi join có hiệu lực**: với lớp có cờ trên, enrollment chỉ chuyển `active` khi có bản ghi đồng ý hợp lệ; trước đó học sinh không thấy bài giao và không tạo được attempt.
3. **Ai thu đồng ý**: phương án pilot gọn nhất là nhà trường/giáo viên thu đồng ý giấy hoặc qua kênh của trường và **xác nhận trong hệ thống** (attestation có người chịu trách nhiệm, thời điểm, phiên bản văn bản thông báo). Luồng phụ huynh tự đăng nhập/ký số là workflow riêng, chưa thiết kế (IMPLEMENTATION_PLAN mục 10: phụ huynh không tự động có quyền).
4. **Thông báo**: văn bản thông báo xử lý dữ liệu có phiên bản; thay đổi phiên bản yêu cầu xác nhận lại.
5. **Rút lại đồng ý**: rút lại → enrollment `withdrawn` ngay, rồi chạy workflow xóa/pseudonymize theo mục 4.

Schema đề xuất cho một migration tương lai (**không tạo trong lần này**):

```sql
-- PROPOSAL ONLY. Tenant table, FORCE RLS, composite FKs, append-only (revocation is a new row).
CREATE TABLE edu.student_consents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  student_id uuid NOT NULL,
  class_id uuid,                                   -- NULL = workspace-wide
  kind text NOT NULL CHECK (kind IN ('guardian_consent','student_assent')),
  status text NOT NULL CHECK (status IN ('granted','revoked')),
  method text NOT NULL CHECK (method IN ('school_attestation','paper_on_file','guardian_portal')),
  notice_version text NOT NULL CHECK (length(notice_version) BETWEEN 1 AND 32),
  recorded_by_user_id uuid NOT NULL REFERENCES edu.users(id),
  evidence_ref text CHECK (evidence_ref IS NULL OR length(evidence_ref) <= 200), -- no scans/PII
  effective_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_student_consents_workspace_id UNIQUE (workspace_id, id),
  CONSTRAINT fk_student_consents_student FOREIGN KEY (workspace_id, student_id)
    REFERENCES edu.students(workspace_id, id),
  CONSTRAINT fk_student_consents_class FOREIGN KEY (workspace_id, class_id)
    REFERENCES edu.classes(workspace_id, id)
);
-- Runtime: SELECT, INSERT only (no UPDATE/DELETE). Current state = latest row per
-- (student_id, class_id, kind). edu.accept_class_invitation / edu.student_start_attempt must
-- check it for classes flagged as requiring consent.
```

Không lưu tên/số điện thoại phụ huynh hay ảnh chụp giấy đồng ý trong bảng này; `evidence_ref` chỉ là mã tham chiếu hồ sơ do trường giữ.

## 4. Xóa và xuất dữ liệu

### 4.1 Hiện có
- Tài liệu giáo viên: xóa mềm + purge chunks/vector/object (`DELETE /v1/workspaces/{id}/documents/{documentId}` → job `document.delete` → `edu.purge_document_chunks`), idempotent khi replay.
- Rút học sinh khỏi lớp: `POST .../enrollments/{id}/withdraw` (thu hồi truy cập, **không** xóa dữ liệu).
- Thu hồi lời mời, lưu trữ lớp/đề/bài giao.

### 4.2 Thiếu (phải có trước khi nhận dữ liệu học sinh thật)
1. `edu.erase_student(p_student_id)` — SECURITY DEFINER, owner `eduvia_identity_owner`, kiểm tra workspace context + vai trò owner/admin; pseudonymize `students`, đặt enrollment `withdrawn`; quyết định (pháp lý) giữ điểm ẩn danh cho thống kê lớp hay xóa `student_answers`/`grading_*`/`grades`/`quiz_attempts`. Do các bảng điểm là append-only theo trigger, xóa cứng cần một function riêng bỏ qua guard một cách có kiểm soát và có audit.
2. `edu.erase_user()` — tự phục vụ: pseudonymize `users.email`/`display_name`, xóa user Auth0, thu hồi phiên Redis.
3. Bảng tombstone (`edu.erasure_requests`: id, loại, đối tượng, thời điểm yêu cầu/hoàn tất) để **tái áp dụng sau restore** (PILOT-06) — không có bảng này thì restore có thể làm sống lại dữ liệu đã xóa.
4. Purge theo tuổi (job định kỳ) cho `background_jobs`, `generation_jobs.input/output`, lời mời hết hạn, object `ws/*/export/*`.
5. Audit cho mọi thao tác xóa (hiện audit chỉ là log JSON, không có bảng).

### 4.3 Xuất dữ liệu
- Giáo viên: có xuất CSV ngân hàng câu hỏi (`questions/export`), xuất đề DOCX/PDF (`exports`), xuất điểm lớp `assignments/{id}/results/export.csv` (chứa `displayName` học sinh — tệp này là dữ liệu cá nhân học sinh khi rời hệ thống; UI phải cảnh báo).
- Học sinh: chỉ xem được kết quả từng attempt (`/v1/student/attempts/{id}/results`). **Thiếu** endpoint xuất toàn bộ dữ liệu của chính học sinh (bài giao, attempt, câu trả lời, điểm đã công bố) — đề xuất `GET /v1/student/export` dựa trên các function `edu.student_*` hiện có, chỉ trả điểm đã release.
- Thiếu xuất toàn bộ workspace cho giáo viên khi rời dịch vụ.

## 5. Dữ liệu gửi cho provider (LLM/embedding)

| Luồng | Gửi gì | Không gửi | Code |
|---|---|---|---|
| Embedding (`document.embed`) | Văn bản chunk của tài liệu giáo viên | Tên tệp, id người dùng, id học sinh | `backend/app/services/embeddings.py`, `backend/app/services/indexing.py` |
| Truy vấn retrieval | Câu truy vấn giáo viên nhập | Như trên | `backend/app/services/retrieval.py` |
| Sinh nháp (`content.generate`, `questions.generate`) | System prompt cố định theo mục đích; tham số giáo viên trong `<request>`; ≤ 8 chunk trong `<source id="[n]">` | Tên tệp, dữ liệu học sinh, email; prompt/nguồn/output không ghi log | `backend/app/services/generation.py` (docstring mục 2) |
| Chấm điểm | **Không gọi provider** — chấm single-choice tất định trong DB/worker | — | `backend/app/services/scoring.py` |

Quy tắc pseudonymization (bắt buộc, kể cả khi sau này thêm trợ lý AI hoặc chấm tự luận):
1. **Không bao giờ** gửi `students.*`, `users.email`, `users.display_name`, `external_code`, id học sinh/attempt, câu trả lời gắn với học sinh cho provider.
2. Nếu một tính năng tương lai cần nội dung bài làm (ví dụ nhận xét tự luận), chỉ gửi văn bản bài làm sau khi loại tên, thay định danh bằng nhãn tạm (`HS-1`) chỉ sống trong một request, và chỉ khi pháp lý đã duyệt việc chuyển dữ liệu ra nước ngoài.
3. Giáo viên phải được nhắc không tải lên tài liệu chứa dữ liệu học sinh (chưa có trong UI). Hệ thống không quét PII trong tài liệu.
4. Cấu hình provider: tắt lưu giữ/huấn luyện trên dữ liệu gửi đi (zero-retention nếu có), chọn region; ghi hợp đồng xử lý dữ liệu. Chưa thực hiện — embedding mặc định ở dev/test là bộ băm cục bộ (`local-hash-v1`, không gọi mạng); production bắt buộc cấu hình provider thật (`backend/app/core/config.py`).

## 6. Việc cần làm trước pilot có học sinh thật

| # | Việc | Loại | Owner |
|---|---|---|---|
| 1 | Review pháp lý theo Nghị định 13/2023: độ tuổi, hình thức đồng ý, chuyển dữ liệu ra nước ngoài (Auth0, LLM, embedding), nơi lưu trữ | Pháp lý | — |
| 2 | Chốt thời hạn lưu giữ mục 2 | Pháp lý + product | — |
| 3 | Migration `student_consents` + kiểm tra trong `accept_class_invitation`/`student_start_attempt` | Kỹ thuật | — |
| 4 | `edu.erase_student`, `edu.erase_user`, bảng tombstone, job purge theo tuổi | Kỹ thuật | — |
| 5 | Endpoint xuất dữ liệu học sinh; cảnh báo khi giáo viên xuất CSV điểm | Kỹ thuật + UI | — |
| 6 | Văn bản thông báo quyền riêng tư (có phiên bản) cho giáo viên, học sinh, phụ huynh | Pháp lý + product | — |
| 7 | Cấu hình provider (zero-retention/region) và hợp đồng xử lý dữ liệu | Vận hành + pháp lý | — |
| 8 | Lifecycle object storage cho exports, backup có hạn | Vận hành | — |
