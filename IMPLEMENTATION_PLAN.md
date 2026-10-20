# Eduvia — Kế hoạch triển khai sản phẩm và kỹ thuật

> Ngày: 2026-10-20. Trạng thái: kế hoạch đề xuất, không phải báo cáo tính năng đã hoàn thành. Chỉ scaffold được mô tả trong [DEVELOPMENT.md](DEVELOPMENT.md) đã có code; các mốc bên dưới chưa được coi là đạt chỉ vì có tài liệu.

## 1. Mục tiêu và bản đồ tài liệu

Eduvia phát triển theo ba trụ cột: **teacher-led** (giáo viên tạo nội dung, giao bài, theo dõi lớp), **student-led** (học sinh chủ động học theo chương trình, luyện điểm cần củng cố và thi thử đúng cấu trúc), và **school-led** (nhà trường quản lý giáo viên, tổ chuyên môn, phân công và quy trình học vụ). Các trải nghiệm dùng chung nền tảng chương trình/nội dung/assessment, không dùng chung quyền đọc dữ liệu cá nhân mặc định. Nhánh school được bổ sung ngày 2026-10-21; không mở rộng ngầm pilot M0–M7.

- [README.md](README.md): định hướng và phạm vi sản phẩm.
- [ARCHITECTURE.md](ARCHITECTURE.md): ranh giới hệ thống, security, vận hành.
- [DATABASE.md](DATABASE.md): schema core; DDL minh họa không phải migration hoàn chỉnh.
- [EXAM_BLUEPRINTS.md](EXAM_BLUEPRINTS.md): cấu trúc đề, ma trận, generation và validation.
- [STUDENT_LEARNING.md](STUDENT_LEARNING.md): sản phẩm tự học, learner model và student-learning service.
- [DEVELOPMENT.md](DEVELOPMENT.md): setup và trạng thái triển khai thực tế.
- [SCHOOL_MANAGEMENT.md](SCHOOL_MANAGEMENT.md): school-led teacher management và nhánh H0–H4.

### Nhánh nhà trường H0–H4 (bổ sung)

H0: school ownership, permission bundles/scopes và RLS (sau M1/M2). H1: mời/quản lý giáo viên, tổ chuyên môn và seat checks. H2: năm học/học kỳ, phân công lớp/môn, dashboard giáo viên và bàn giao (cần M5/M6). H3: duyệt học liệu/blueprint theo exact revision, báo cáo được phân quyền và budget trường (cần M4/M6). H4: pilot trường sau M7 và H3, có security/recovery/privacy gates.

Nhánh này độc lập với L0–L4 sau khi đạt core dependencies. School management ban đầu ở core, không thêm microservice hoặc kho identity/grade thứ hai. Quyền quản lý giáo viên không tự cấp quyền xem tài liệu cá nhân, answer keys hoặc self-study. Không gồm payroll/chấm công/tự xếp hạng giáo viên. Chi tiết workflow, schema, API đề xuất và acceptance tests nằm trong tài liệu school; estimate riêng sau khi chốt trường pilot.

Quy tắc đọc: kế hoạch này xác định thứ tự giao hàng; tài liệu chuyên đề xác định hành vi chi tiết. Phạm vi mở rộng không tự động mở rộng MVP giáo viên. Khi đổi invariant, cập nhật tài liệu chuyên đề và các tham chiếu liên quan trong cùng PR.

## 2. Hiện trạng và nguyên tắc

Đã có Next.js shell, FastAPI health, PostgreSQL/Redis connections, Alembic bootstrap, Celery entry, S3 client factory, OpenAPI type generation, scripts và CI configuration. Chưa có auth, bảng domain/RLS, upload API, RAG, generation, enrollment, quiz, OMR hay billing. CI configuration không chứng minh một run đã pass; cần xác minh baseline trong M0.

1. Làm vertical slice: migration + policy + service + contract + UI + tests; không dựng hàng loạt CRUD rỗng.
2. Core ban đầu là modular monolith. Student-learning được thiết kế thành bounded context có thể deploy riêng; không tách mọi module thành microservice ngay.
3. Database là nguồn sự thật cho transaction của từng service; queue, cache và output AI không thay thế database.
4. Privacy, tenant isolation, quotas và recovery bắt đầu trước pilot.
5. Ưu tiên dữ liệu có bản quyền/được phép, ngân hàng câu hỏi đã duyệt và phép chấm deterministic.
6. Nội dung thủ công, bài đã giao và submission không phụ thuộc provider AI đang hoạt động.
7. Bản đồ kỹ năng, ma trận đề và rubric phải được duyệt chuyên môn; AI chỉ hỗ trợ đề xuất.

## 3. Phạm vi giao hàng

### 3.1 Pilot giáo viên

10–20 giáo viên; một cấp học, một hoặc hai môn. Vòng hoàn chỉnh: nguồn hợp lệ → AI draft có nguồn → chỉnh sửa/duyệt → publish tài liệu và quiz single-choice → học sinh nộp → deterministic grading → kết quả giáo viên và release cho học sinh.

Có: identity, personal teacher workspaces, RLS, private knowledge, source-aware generation, lesson plans/study guides, question bank, blueprint single-choice, revision history, Word/PDF, classes/invitations, deadlines, quota/audit và recovery.

Chưa có: tự học độc lập, OMR, essay auto-grading, AI tutor, school admin, live cross-workspace sharing, offline quiz, mobile native, thanh toán tự động. Có thể mô hình hóa phần mở rộng nhưng không tuyên bố hỗ trợ khi UI/API/chấm điểm chưa có.

### 3.2 Student self-study MVP sau pilot core

Một môn, một khối và chương trình được chọn. Học sinh không phải tham gia lớp giáo viên mới được sử dụng. Có onboarding, mục tiêu, tiến độ trên lớp do người học xác nhận, diagnostic, hồ sơ kỹ năng có độ tin cậy, kế hoạch tuần theo rules, bài luyện đã duyệt, checkpoint và tiến bộ cá nhân.

### 3.3 Mock-exam release

Blueprint đã kiểm chứng theo kỳ thi/năm/phạm vi; đề đúng cấu trúc, thời gian và scoring policy; phân tích theo kỹ năng/phần thi, cập nhật ôn tập. Không đổi cấu trúc thi thử để ưu tiên điểm yếu. Các dạng câu ngoài single-choice là milestone riêng và là điều kiện bắt buộc nếu cấu trúc kỳ thi yêu cầu.

## 4. Roadmap core M0–M7

| Mốc | Deliverable / backlog | Exit gate |
|---|---|---|
| M0 — Quyết định và baseline | Xác minh tests/build/migrations/Compose trên DB thật; chốt provider auth, pilot curriculum, ngân sách; ADR về session, service boundary và deployment | Setup tái lập được; blockers được ghi; không có secrets trong repo; quyết định có owner |
| M1 — Identity và isolation | OIDC/provider sessions; login/logout; idempotent user + personal workspace provisioning; membership; migrator/runtime roles; FORCE RLS; composite FK; transaction-local context; onboarding UI | Hai tenant cách ly; missing context deny; pool reuse an toàn; concurrent onboarding không nhân đôi workspace; session/CSRF/revocation tests pass |
| M2 — Jobs, cost và storage | Durable jobs/outbox/dispatcher; leases fencing, sweeper, retry/cancel; usage ledger/reservations; storage live+held bytes; audit; private bucket; upload validation và authorized download | Broker/worker failure khôi phục được; quota races không vượt reservation rule; duplicate execution accounting phân biệt đúng; file lỗi/quá hạn không publish |
| M3 — Knowledge/RAG | Curriculum metadata; rights attestation; immutable document versions; sandbox parsing PDF text/DOCX/TXT; chunk/embedding version; hybrid authorized retrieval; citations; deletion | Failed version không thay active version; cross-tenant/license tests pass; bộ eval có nguồn và hỗ trợ thiếu-context; không bật shared corpus chưa có quyền |
| M4 — Authoring/blueprints | Manual editor trước AI; lesson/study guide revisions; question bank + objective mapping; versioned single-choice blueprint; constrained generation; teacher review; frozen exams; audience-specific Word/PDF | Tạo/sửa/duyệt/xuất được; blueprint mismatch bị từ chối; không lộ key; AI outage vẫn soạn tay; citations kiểm tra được |
| M5 — Teaching portal | Classes, teachers, invitation expiry/rate limits, enrollment; student login; assignments pin revision/exam; responsive mobile UI | Chỉ enrolled student thấy assigned content; invite không là read credential; withdrawal chặn thao tác mới; retained history tuân policy |
| M6 — Assessment/results | Attempts/limits/deadlines; autosave revision; locked idempotent submit; expiry sweeper; grading snapshots; separate score/solution release; override revisions; results aggregates | Race/start/submit/replay tests pass; điểm khớp fixtures; không nhận late answers; không lộ solution qua SSR/API/export; denominator và pending grades hiển thị rõ |
| M7 — Pilot readiness | End-to-end teacher/student journeys; load/security tests; RAG evaluation; monitoring/runbooks; consent/retention/deletion; DB/object restore; hướng dẫn pilot | Không còn lỗi chặn isolation, mất submission hoặc sai điểm; restore drill đạt mục tiêu đã thống nhất; có owner vận hành và thu feedback |

Đồ thị chính: M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7. Sau M1 có thể làm class CRUD/invites song song M2–M3; sau khi có manual authoring có thể triển khai assessment mà không chờ tối ưu RAG. Không tích hợp learner planner trước khi assessment evidence đáng tin.

**Demo giá trị đầu tiên tại M4:** upload → sinh giáo án có nguồn → sửa → xuất. **Pilot end-to-end tại M7**, không gọi một demo generator là LMS hoàn chỉnh.

## 5. Roadmap mở rộng L0–L4

| Mốc | Phạm vi | Phụ thuộc và nghiệm thu |
|---|---|---|
| L0 — Shared learning foundations | Skill taxonomy/prerequisites được chuyên môn duyệt; objective↔skill mappings; misconceptions; blueprint provenance/version; nội dung licensed cho self-study | Sau M3–M4; bộ môn kiểm định mapping, không tự xem teacher-private corpus là shared library |
| L1 — Service contract và learner identity | Personal learner ownership; scopes/consent; service API/events; core assessment extension cho standalone practice/mock; inbox/outbox; learner-specific quotas; isolation tests | M1/M2/M6; không ép tạo class/teacher workspace giả; không direct DB joins; submission/scoring vẫn có một authority |
| L2 — Self-study MVP | Ba mục tiêu sản phẩm nhưng pilot giới hạn một use case; diagnostic cố định; rule-based mastery với confidence; weekly plan; practice từ pool đã duyệt; today/progress UI | L0–L1; câu mới để kiểm tra lại; giải thích vì sao chọn task; không kết luận từ một quiz; giáo viên không tự động thấy self-study data |
| L3 — Ôn thi theo cấu trúc | Catalog blueprint kiểm chứng; đủ supported item types; timed mock; phân tích từng phần; plan điều chỉnh theo deadline và trọng số | L2 + content coverage; blueprint shortage fail rõ; mock không adaptive cấu trúc; mọi scoring policy có fixtures/rubric và review theo loại |
| L4 — Adaptive nâng cao | Adaptive diagnostic, empirical difficulty calibration, knowledge tracing, spaced-review tuning, tutor có guardrails | Chỉ sau khi có dữ liệu chất lượng, chuyên môn đánh giá và baseline so sánh; không lấy lịch sử học ít ỏi để hứa điểm thi |

Student-learning có thể deploy riêng ngay tại L1 nếu đã đạt extraction gate ở mục 7; nếu team nhỏ, làm module cô lập trước rồi tách. OMR và commercial billing là các nhánh sau M7, không phụ thuộc L2 bắt buộc; ưu tiên dựa trên nhu cầu pilot, nguồn lực và unit economics. Không chạy đồng thời mọi nhánh chỉ vì schema đã dự kiến.

## 6. Sprint khởi động đề xuất

| Thứ tự | Công việc | Artifact/kiểm tra |
|---|---|---|
| 1 | Baseline môi trường | Chạy locked dependencies, lint/tests/build, PostgreSQL migration/readiness và Compose; ghi kết quả thực tế |
| 2 | Chốt identity/session | ADR provider, callback/logout, cookie/CSRF, expiry/rotation, frontend-to-API; không header auth bypass |
| 3 | Migration identity/tenancy | users/workspaces/members; unique personal owner; runtime roles/grants/RLS; audit tối thiểu |
| 4 | Authenticated services | Verify issuer/subject; user bootstrap; create personal workspace idempotent; current user/workspaces; verified context |
| 5 | UI thật | Login/logout, protected pages, onboarding/settings, expired-session và forbidden states |
| 6 | Integration gate | Runtime-role tests hai workspace, revocation, missing context, pooled connections và concurrent onboarding |

DoD sprint: giáo viên đăng nhập và có workspace thật với isolation đã test; chưa mở tenant document/student routes nếu boundary chưa đạt. Không coi frontend route guard là authorization.

## 7. Chiến lược student-learning microservice

### 7.1 Ranh giới mục tiêu

- **Core Education API:** identity mapping, teacher workspaces/classes, curriculum/catalog, rights, question bank, blueprint, publication, authoritative attempt/submission/scoring và teacher official grades. Standalone self-study assessment cần bổ sung ownership model riêng trước khi mở API; schema assignment-centric hiện tại chưa hỗ trợ.
- **Student Learning API:** personal learner profiles/preferences, goals, availability, plan versions/tasks, diagnostics orchestration, authorized evidence receipts, mastery projections, recommendations và progress UI data.
- **Frontend/BFF:** có thể giữ một Next.js app với route teacher/student; không tạo authority thứ hai và không giữ key/provider secrets phía browser.

Service mới có database, credentials, migrations, workers và deployment riêng khi tách. Có thể dùng chung PostgreSQL host ở pilot nhưng không dùng chung table ownership/grants. Không FK xuyên service, không query DB core trực tiếp. Curriculum/exam IDs bên learner là external versioned references, không phải quyền truy cập.

### 7.2 Hợp đồng và consistency

Commands cần quyết định tức thời (start/save/submit, authorization, source license, deletion revoke) gọi API owner. Event phục vụ projection, không thay thế permission check. Mỗi service dùng local transaction + outbox; consumer có inbox dedupe, aggregate version, retry/DLQ, replay/reconcile. Không dual-write hai database hoặc hứa exactly-once.

Core scoring là nguồn sự thật. Student service không giữ answer keys hoặc tự chấm lại official grade. Chỉ nhận feedback/evidence được phép theo audience/release; review results không phát sang event bus chung dưới dạng keys/raw answers. Timeout sau submit phải truy vấn theo idempotency key, không báo thành công nếu chưa durable.

### 7.3 Extraction gate

Chỉ tách khi: owner/team và vận hành rõ; learner/core contracts ổn định; independent learner ownership được test; service auth/revocation fail-closed; contract versioning và integration tests; outbox/inbox replay; consent/delete propagation; tracing/alerts; backup/restore cho cả hai; cost/quota owner không mơ hồ. Động lực: release cadence, workload hoặc trách nhiệm team độc lập, không chỉ số lượng endpoint.

Nếu module-first: ngăn import repository/model nội bộ của core, gọi qua application ports. Khi tách: tạo target DB → snapshot/backfill versioned → replay outbox → kiểm tra counts/hashes/permissions → brief write freeze và drain nếu cần → chuyển single writer bằng feature flag → theo dõi. Không dual-write tùy ý. Rollback phải reconcile writes mới trước khi trả ownership; giữ migration mapping và không xóa source ngay.

## 8. Test strategy và Definition of Done

Mỗi slice gồm migrations/constraints/policies, service authorization, OpenAPI + generated types, UI loading/empty/error, unit/integration tests, audit/log redaction, tài liệu và hướng rollback/repair. PostgreSQL thật cho RLS, locking và constraints; SQLite/in-memory không thay thế các gate này.

| Nhóm | Release checks |
|---|---|
| Isolation | Cross-tenant ID/FK, own-record restrictions, missing context, owner/BYPASSRLS, suspended membership, SSR cache |
| Content/rights | Expired license, withdrawn version, source evidence, parser limits, teacher/student exports, no silent unsupported item types |
| Jobs/cost | Duplicate delivery, killed worker/stale lease, Redis loss, expired reservation, uncertain provider billing, concurrent caps |
| Assessment | Concurrent start/autosave/submit, clock after lock, retry, deadline, exam immutability, release vs retakes, overrides |
| Student learning | Learner A/B isolation, no teacher default access, sparse evidence, hints/repeats weighting, planner prerequisite cycles, workload feasibility |
| Services | Duplicate/out-of-order/missing events, snapshot replay, revoked grants with stale projection, API timeout, correction/retraction, deletion convergence |
| Recovery | DB + objects + outbox consistency, independent service restore and reconciliation, deletion tombstones replay, no erased PII resurrection |

AI quality evaluation cần bộ mẫu tiếng Việt do chuyên môn duyệt: alignment, factual/citation correctness, ambiguity, rubric consistency và mức giáo viên phải sửa. Ngưỡng chấp nhận được chốt trước pilot, không tự đặt phần trăm chất lượng chưa đo.

Observability: request/job/trace IDs, queue age, submission errors, stale projections, citation failures, cost per output/learner, teacher corrections. Không dùng learner IDs làm metric labels công khai; logs có access controls và retention.

## 9. Các quyết định cần chốt

| Thời điểm | Quyết định | Vai trò chịu trách nhiệm đề xuất |
|---|---|---|
| Trước M1 | Auth provider, session topology, team/capacity | Tech lead + product |
| Trước M3 | Cấp/lớp/môn/bộ sách, source rights/derivative retention, embedding model/dimension, AI budget | Product + chuyên môn + legal/privacy + tech |
| Trước M4 | Template giáo án/exports, blueprint schema và quy trình chuyên môn duyệt | Chuyên môn + product |
| Trước M5/M7 | Student onboarding/consent, hosting region, provider data handling, retention, RPO/RTO đã chứng minh | Privacy/legal + operations |
| Trước L1 | Learner ownership, standalone assessment schema, service auth, event broker, deletion coordination, learner quotas | Tech lead + security + product |
| Trước L3 | Kỳ thi/năm/địa phương, nguồn cấu trúc chính thức, đủ item types, examiner/rubric process | Chuyên môn + product |
| Sau pilot | OMR priority, billing provider, pricing và quotas dựa trên chi phí thật | Product + operations |

Nếu chưa có quyền shared textbooks, dùng private uploads hợp lệ cho teacher pilot và pool nội dung tự biên soạn/được phép cho self-study. Không nhập kho riêng giáo viên vào service học sinh mặc định. Phụ huynh không tự động có quyền: consent và guardian access là các workflow riêng cần thiết kế theo độ tuổi và pháp lý áp dụng.

## 10. Ước lượng và thành công

Ước lượng định hướng cho **M0–M7**: 12–18 tuần với hai dev full-time có kinh nghiệm và QA/product/chuyên môn hỗ trợ; một dev khoảng 5–8 tháng. Không phải deadline hoặc báo giá; chưa gồm L0–L4, OMR, billing production hay thời gian cấp phép nội dung. Hiệu chỉnh sau M1; estimate nhánh student sau khi chốt curriculum, assessment types, corpus và extraction gate.

Đo pilot giáo viên: hoàn thành vòng dạy–học, thời gian chuẩn bị tiết kiệm, mức sửa AI, độ đúng chấm điểm, retention và cost/output. Đo student: hoàn thành task, improvement trên câu chưa gặp theo cùng kỹ năng, retention, tải học có phù hợp, tỷ lệ kết luận thiếu bằng chứng, cost/active learner. Không dùng số câu sinh ra hay điểm đề lặp làm bằng chứng duy nhất về tiến bộ.

Không triển khai code, provision service hay chạy migration chỉ bằng việc phê duyệt tài liệu này. Bước thực thi tiếp theo là M0–M1; mọi mốc còn lại cần PR và acceptance evidence riêng.
