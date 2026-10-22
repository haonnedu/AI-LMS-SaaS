# Eduvia — Kế hoạch triển khai sản phẩm và kỹ thuật

> Ngày: 2026-10-20, cập nhật 2026-10-22 (bổ sung nhánh AI/MCP, mục 8). Trạng thái: kế hoạch đề xuất, không phải báo cáo tính năng đã hoàn thành. Chỉ scaffold được mô tả trong [DEVELOPMENT.md](DEVELOPMENT.md) đã có code; các mốc bên dưới chưa được coi là đạt chỉ vì có tài liệu.

## 1. Mục tiêu và bản đồ tài liệu

Eduvia phát triển theo ba trụ cột: **teacher-led** (giáo viên tạo nội dung, giao bài, theo dõi lớp), **student-led** (học sinh chủ động học theo chương trình, luyện điểm cần củng cố và thi thử đúng cấu trúc), và **school-led** (nhà trường quản lý giáo viên, tổ chuyên môn, phân công và quy trình học vụ). Các trải nghiệm dùng chung nền tảng chương trình/nội dung/assessment, không dùng chung quyền đọc dữ liệu cá nhân mặc định. Nhánh school được bổ sung ngày 2026-10-21; nhánh AI/MCP (A0–A4) bổ sung ngày 2026-10-22; cả hai không mở rộng ngầm pilot M0–M7.

- [README.md](README.md): định hướng và phạm vi sản phẩm.
- [ARCHITECTURE.md](ARCHITECTURE.md): ranh giới hệ thống, security, vận hành.
- [DATABASE.md](DATABASE.md): schema core; DDL minh họa không phải migration hoàn chỉnh.
- [EXAM_BLUEPRINTS.md](EXAM_BLUEPRINTS.md): cấu trúc đề, ma trận, generation và validation.
- [STUDENT_LEARNING.md](STUDENT_LEARNING.md): sản phẩm tự học, learner model và student-learning service.
- [DEVELOPMENT.md](DEVELOPMENT.md): setup và trạng thái triển khai thực tế.
- [SCHOOL_MANAGEMENT.md](SCHOOL_MANAGEMENT.md): school-led teacher management và nhánh H0–H4.
- [tools/eduvia-mcp/README.md](tools/eduvia-mcp/README.md) và [tools/MCP_INTEGRATION.md](tools/MCP_INTEGRATION.md): MCP dev-only (source, backlog, DB dev). Tool registry và MCP cấp ứng dụng cho tính năng AI là nhánh A0–A4 ở mục 8; lean cut và GTM/pháp lý ở mục 3.4–3.5.

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

### 3.4 Lean cut trước pilot (bổ sung 2026-10-22)

Với hai dev và pilot 10–20 giáo viên, các cơ chế dưới đây giữ nguyên invariant an toàn nhưng làm ở dạng gọn trước M7; dạng đầy đủ chỉ làm khi pilot chứng minh cần. Tracker CORE điều chỉnh acceptance tương ứng; không coi dạng gọn là nợ phải trả trước pilot.

| Cơ chế | Dạng gọn trước pilot | Dạng đầy đủ (sau pilot, khi có bằng chứng) |
|---|---|---|
| Jobs (ARCHITECTURE mục 10) | `background_jobs` là nguồn sự thật, Celery `acks_late`, idempotent stage writes, một sweeper cho job quá hạn | Lease generation/fencing, outbox republish, dead-letter review |
| Usage/cost (DATABASE mục 9) | Reservation đơn giản per job, cap cứng per workspace/tháng, `usage_events` append-only; provider cost ghi thực tế | Settle/uncertain reconcile, nhiều bucket, giá khách hàng minor units |
| Storage (ARCHITECTURE mục 5) | Upload qua API với giới hạn kích thước/MIME, một bucket private, signed download ngắn hạn | Signed upload URL, quarantine, live+held bytes |
| Student-learning service (mục 7) | Đóng băng tài liệu; không viết thêm thiết kế cho tới sau M7 | Extraction theo gate mục 7.3 |
| School H0–H4 | Đóng băng như trên; chỉ giữ ownership model trong schema | Theo SCHOOL_MANAGEMENT khi có trường pilot |
| AI/MCP (mục 8) | Tool registry in-process, job `assistant_run`, không transport MCP, không token riêng | Streamable HTTP + OAuth ở A3 |

Không cắt: RLS và runtime role, composite FK, idempotent submit, server-only answer keys, tách score/solution release, audit cho mutation nhạy cảm, backup/restore drill.

### 3.5 Go-to-market, pháp lý và vận hành pilot (bổ sung 2026-10-22)

Các mục này chưa có trong tài liệu kỹ thuật nhưng chặn pilot nếu thiếu; mỗi mục cần owner có tên và quyết định ghi trong `tasks/decisions/` trước mốc tương ứng (bảng ở mục 10).

- **Tuyển pilot:** cách tiếp cận 10–20 giáo viên (một trường hoặc nhóm chuyên môn), tiêu chí chọn, cam kết thời gian, kênh hỗ trợ (Zalo nhóm hoặc tương đương) và lịch thu feedback hai tuần/lần. Owner nghiệp vụ được nêu tên trước M5.
- **Cấu trúc đề thực tế:** kiểm chứng với giáo viên pilot cấu trúc kiểm tra định kỳ và thi tốt nghiệp hiện hành (nhiều lựa chọn, đúng/sai nhiều ý có điểm từng phần, trả lời ngắn). Kết quả quyết định phạm vi M4/M6: bổ sung dạng câu hoặc thu hẹp pilot về kiểm tra thường xuyên. Quyết định trước M4; không giả định single-choice đủ.
- **Bản quyền nội dung:** kế hoạch làm việc với nhà xuất bản/bộ sách theo chương trình 2018 hoặc chốt pilot chỉ dùng tài liệu giáo viên tự biên soạn và upload hợp lệ. Quyết định trước M3 vì RAG phụ thuộc trực tiếp.
- **Pháp lý dữ liệu cá nhân (cần tư vấn pháp lý xác nhận):** đối chiếu Nghị định 13/2023 và luật bảo vệ dữ liệu cá nhân hiện hành về: chuyển dữ liệu ra nước ngoài khi gọi LLM/embedding provider (hồ sơ đánh giá tác động, hoặc chọn region/provider phù hợp), đồng ý của cha mẹ cho học sinh dưới tuổi quy định, nơi lưu trữ dữ liệu, quyền xóa. Quyết định trước M3 cho dữ liệu giáo viên/tài liệu và trước M5 cho dữ liệu học sinh. Không gửi định danh học sinh cho provider ở bất kỳ mốc nào (ARCHITECTURE mục 12, mục 8.2).
- **Unit economics AI:** đo cost per workflow (soạn giáo án, sinh đề, trợ lý) ở A1 và đối chiếu giá gói trong README mục 9 trước khi chốt pricing; không hứa gói giá chưa có số đo.
- **Thanh toán và hóa đơn:** VNPay/MoMo hoặc tương đương và hóa đơn điện tử là nhánh billing sau M7; pilot dùng miễn phí hoặc thanh toán thủ công có ghi nhận.

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

Đồ thị chính: M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7. Sau M1 có thể làm class CRUD/invites song song M2–M3; sau khi có manual authoring có thể triển khai assessment mà không chờ tối ưu RAG. Không tích hợp learner planner trước khi assessment evidence đáng tin. Nhánh AI/MCP (mục 8) bắt đầu từ A1 sau M4 và chỉ bọc service đã có; không thay đổi thứ tự M-gates.

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

## 8. Nền tảng AI tác vụ và MCP (bổ sung 2026-10-22, thu gọn cùng ngày)

### 8.1 Mục tiêu và ranh giới

Mọi tính năng AI đã hoặc sẽ có — AI draft giáo án/đề (M4), trợ lý cá nhân hóa cho giáo viên (README 3.4), gợi ý ôn tập cho học sinh (L2–L4), báo cáo cho tổ chuyên môn (H3) — đều cần cùng một việc: đọc đúng dữ liệu người dùng được phép thấy và tạo ra thay đổi có kiểm soát. Thay vì mỗi tính năng tự nối prompt với service, Eduvia chuẩn hóa lớp này thành một **tool registry** đặt trên application services hiện có, dùng chung authorization, RLS context, quota, audit và idempotency của core. Schema tool/resource/prompt tuân theo [Model Context Protocol](https://modelcontextprotocol.io) ngay từ đầu để sau này expose cho client ngoài mà không viết lại, nhưng **transport MCP (Streamable HTTP, token riêng) chỉ xuất hiện ở A3** khi có client ngoài thật; trước đó orchestrator và tools chạy cùng process trong core API.

Mục tiêu sản phẩm của nhánh này là **giảm thao tác của người dùng**: người dùng nêu ý định một lần (ví dụ "soạn bài tuần sau cho lớp 10A1 theo tiến độ hiện tại"), AI tự thu thập ngữ cảnh qua tools, tạo bản nháp hoặc đề xuất có nguồn, người dùng chỉ còn duyệt. Trước khi làm agent cho một workflow, phải so với phương án không cần agent (nút "Soạn tuần tới" với form điền sẵn từ profile); chỉ làm agent khi phương án đơn giản không đạt. Thước đo là chất lượng duyệt (tỷ lệ sửa, tỷ lệ mở citation) và thời gian tới bản nháp, không phải số click và không phải số tool.

Phân biệt rõ hai thứ cùng tên MCP trong repo:

| | `tools/eduvia-mcp` (đã có) | Tool registry và MCP cấp ứng dụng (nhánh A) |
|---|---|---|
| Người dùng | Developer, agent lập trình | Giáo viên, học sinh, nhà trường thông qua trợ lý trong app; client ngoài từ A3 |
| Dữ liệu | Source code, tài liệu, backlog | Workspace, học liệu, câu hỏi, lớp, bài giao, kết quả |
| Quyền | Chỉ đọc checkout local, không secrets | Quyền của đúng actor đang đăng nhập, fail-closed |
| Hạ tầng | Không cần DB/API | Chạy trong core API, dùng DB thật và services thật |

Hai server không trộn vào nhau. `tools/MCP_INTEGRATION.md` (Postgres MCP cho dev) thuộc nhóm thứ nhất, phải dùng role chỉ đọc trên DB dev, không bao giờ trỏ vào staging/production.

Nguyên tắc kế thừa từ mục 2 và ARCHITECTURE mục 6–8, 12: tool là adapter mỏng trên service, không truy vấn DB trực tiếp; output AI là advisory; publish, giao bài, release điểm, mời học sinh và mọi thao tác khó đảo ngược luôn qua xác nhận của người; chính sách release điểm giữ mặc định `manual` của ARCHITECTURE mục 8, trợ lý không đổi; không gắn nhãn năng lực học sinh từ một quiz; AI outage không được làm mất luồng thủ công.

### 8.2 Kiến trúc

- **Vị trí:** module `ai_tools` trong core modular monolith (FastAPI), gồm tool registry, orchestrator và policy. Không có process hay endpoint riêng cho tới A3. Khi student-learning tách theo mục 7, service đó có registry riêng với learner scope; không có một registry "siêu quyền" đi xuyên hai boundary.
- **Mỗi lượt chạy trợ lý là một `background_job` kind `assistant_run`** (ARCHITECTURE mục 10, DATABASE mục 9): nhờ đó dùng lại reservation/settle của usage ledger (`usage_reservations` FK tới job), lease/retry/cancel, progress API và resume sau khi đóng tab. Hội thoại nhiều lượt là chuỗi job cùng `assistant_session_id`; không có cơ chế budget hay durability thứ hai.
- **Identity cho tool call:** tool chạy trong transaction-local context của M1 với đúng actor, workspace và membership của người tạo job; worker reauthorize actor-sensitive work như JOB-05 đã quy định. Không có service account toàn quyền cho agent, không có token riêng cho trợ lý trước A3. Audit ghi actor, job và tool call.
- **Provider adapter:** orchestrator gọi provider qua adapter của ARCHITECTURE mục 7, mở rộng hợp đồng adapter thêm tool-calling, structured output và streaming; SDK và model cụ thể, cách chuyển tool schema sang định dạng provider, và adaptive thinking/effort là chi tiết chốt trong ADR AI-01, không ghi trong plan. Pin phiên bản model; đổi provider hoặc model bắt buộc chạy lại eval (8.5).
- **Phân lớp tool và chính sách:**

| Lớp | Ví dụ | Chính sách |
|---|---|---|
| Read (idempotent, parallel-safe) | `get_workspace_context`, `list_documents`, `get_document_outline`, `search_library`, `list_content_items`, `get_content_revision`; từ A2 thêm `list_classes`, `list_assignments_due`, `get_results_summary` | DTO allowlist theo audience; phân trang và giới hạn kích thước; **pseudonymize**: tool result không chứa tên/định danh học sinh, chỉ alias ổn định trong một job, ghép lại tên thật ở UI (ARCHITECTURE mục 12); student-facing không bao giờ chứa keys, rubric hoặc solution chưa release |
| Propose (tạo draft/revision, không công bố) | `draft_lesson_plan`, `draft_study_guide`, `draft_quiz_from_blueprint`; từ A2 thêm `propose_assignment`, `draft_feedback_message` | Chỉ ghi `draft`/`in_review`; idempotency key theo job; citations bắt buộc khi có nguồn; validation schema như AUTHR-03/BP-02 |
| Gated action (cần người xác nhận) | `publish_revision`, `assign_to_class`, `release_scores`, `send_invitations` (từ A2) | Tool trả `pending_confirmation` kèm preview/diff; thực thi chỉ sau confirm từ UI gắn đúng request hash và có hạn; confirm từng mục, không bulk cho publish/release |
| Không bao giờ qua tool | Xóa dữ liệu, đổi ownership/billing, đọc answer keys cho học sinh, cross-workspace reads, bypass RLS, sửa official grade, đổi chính sách release | Không tồn tại tool; không phải tool bị tắt |

- **Resources và prompts:** resources cung cấp ngữ cảnh ổn định (hồ sơ giảng dạy, bộ sách và curriculum đã chọn, template giáo án, library snapshot) để người dùng không phải mô tả lại; prompts là workflow đóng gói ("soạn tuần tới", "ôn tập trước kiểm tra") với tham số mặc định lấy từ profile. Mặc định chỉ áp cho nội dung soạn thảo, không áp cho chính sách đánh giá hoặc release.
- **Cost và an toàn:** budget per job qua reservation, cap cứng per workspace/tháng, rate limit per user; tool result có giới hạn kích thước; nội dung tài liệu truy xuất luôn được đánh dấu là dữ liệu, không phải chỉ dẫn; prompt-injection corpus trong test; log redaction; không dùng learner IDs làm metric label.
- **Hợp đồng:** JSON Schema tool/resource/prompt được snapshot trong `contracts/` cùng OpenAPI; đổi schema là breaking change có review như API. Khi A3 mở transport MCP, server chỉ expose đúng registry này dưới OAuth 2.1 resource server; không có tool "chỉ dành cho client ngoài".

### 8.3 Nguyên tắc "ít thao tác"

1. **Context-first:** trợ lý gọi read tools trước khi hỏi; chỉ hỏi khi thông tin không suy ra được. Số câu hỏi làm rõ cho mỗi workflow được đo và có trần.
2. **Mặc định học từ hồ sơ:** template, độ khó, thời lượng, bộ sách lấy từ profile và lịch sử soạn thảo; người dùng chỉ sửa ngoại lệ. Chính sách release điểm, hạn nộp và số lần làm bài không có mặc định học từ lịch sử.
3. **Proposal rồi duyệt có bằng chứng:** mọi output là bản nháp có preview/diff và citations mở được ngay trong màn duyệt; không có bước copy–paste giữa trợ lý và màn hình nghiệp vụ. Duyệt hàng loạt chỉ cho các mục cùng loại ở mức draft; publish và release luôn duyệt từng mục.
4. **Gợi ý chủ động dựa trên sự kiện, không dựa trên nhãn:** server tính "việc cần làm tiếp" từ sự kiện khách quan (hạn nộp sắp tới, lớp chưa có bài tuần này, bài chưa release điểm) và hiển thị nút gọi đúng propose tool; không tự thực thi, không gắn nhãn "học sinh yếu/tụt" từ một bài.
5. **Idempotent và tiếp tục được:** mỗi lượt là job durable; retry hoặc timeout không nhân đôi draft; session tiếp tục được sau khi đóng tab; không bắt nhập lại.
6. **Lối thoát thủ công:** AI outage hoặc hết budget thì UI thủ công vẫn đầy đủ.

### 8.4 Lộ trình A0–A4

| Mốc | Phạm vi | Phụ thuộc | Exit gate |
|---|---|---|---|
| A0 — Dev tooling | Giữ `tools/eduvia-mcp` read-only; Postgres MCP cho DB dev với role chỉ đọc; sửa `tools/MCP_INTEGRATION.md` bỏ superuser | Không | Không đọc được `.env`/secrets; role không có quyền ghi; không trỏ staging/prod |
| A1 — Authoring assistant | ADR AI-01; `assistant_run` job + audit tool call; tool registry với policy theo lớp, pseudonymize và schema snapshot; read tools library/content; propose tools lesson/study guide/quiz gọi đúng AUTHR-03/BP-03; resources và 2–3 prompts; orchestrator qua provider adapter; assistant panel review/approve; eval set tiếng Việt và golden traces chạy trong CI | M4 (AUTHR-03, BP-03), COST-02, JOB-05, AUDIT-01 | Cross-tenant và missing-context deny bằng runtime role; draft không tự publish; injection corpus không đổi policy; tool result không chứa định danh học sinh; AI outage vẫn soạn tay; eval đạt ngưỡng chốt ở AI-02 |
| A2 — Class và results ops | Read tools class/assignment/results (pseudonymized); propose `propose_assignment`, `draft_feedback_message`; gated `publish_revision`, `assign_to_class`, `release_scores`, `send_invitations`; next-action từ sự kiện; đo so baseline thủ công | M6, M7 (baseline pilot), A1 | Gated action không chạy khi chưa confirm; replay không nhân đôi; không lộ solution/keys qua tool result; tỷ lệ sửa và tỷ lệ mở citation không xấu hơn A1; thời gian tới draft giảm so baseline |
| A3 — Transport MCP và school | Streamable HTTP + OAuth 2.1 resource server expose đúng registry cho client ngoài (Claude Desktop/Code, IDE, trợ lý trường); school-scoped reporting tools cho H3; revocation, rate limit per client | M7, A2, H3 | External token revocation tests; client ngoài không thấy tool nào ngoài registry; school scope không đọc teacher-private corpus |
| A4 — Learner tutor | Learner-scoped registry trong student-learning theo contracts L1; tutor có guardrails | L4, A2 | Learner isolation tests; consent; tutor không hứa điểm; không đọc teacher-private corpus |

Đồ thị: M4 → A1 (có thể chạy song song M5–M6); M7 baseline → A2; A3 và A4 là hai nhánh độc lập sau A2. Nhánh A **không phải điều kiện của pilot M7**: nếu A1 đạt gate thì pilot dùng trợ lý soạn bài, nếu không thì pilot chạy luồng thủ công và đo baseline cho A2. Không tạo tool cho tính năng chưa có service thật; trước A1 không có task implement nào ngoài A0 và ADR AI-01.

### 8.5 Test và metrics

| Nhóm | Release checks |
|---|---|
| Authorization | Ma trận tool × vai trò × audience; cross-tenant ID; suspended membership; missing context; job chạy sau khi membership bị thu hồi |
| Hợp đồng | Snapshot schema tool/resource/prompt; breaking change bị CI chặn; tool result trong giới hạn kích thước |
| Hành vi | Gated action không confirm; confirm sai request hash; idempotency replay; retry sau timeout; resume job |
| An toàn | Injection corpus từ tài liệu và tên lớp; không lộ keys/rubric/solution; không lộ định danh học sinh trong tool result/prompt log; log redaction; budget cap và rate limit |
| Chất lượng | Eval set tiếng Việt do chuyên môn duyệt và golden traces (tool đúng, thứ tự hợp lý, không hỏi thừa) chạy offline trong CI bằng fixture; pin model; đổi model/provider phải chạy lại và đạt lại ngưỡng |

Metrics vận hành: tỷ lệ draft được duyệt không sửa lớn, tỷ lệ citation được mở trước khi duyệt, thời gian từ yêu cầu đến draft, số câu hỏi làm rõ per workflow, tỷ lệ gợi ý chủ động được chấp nhận, tool error rate, cost per workflow so với giá gói. Baseline thủ công đo trong pilot M7 trước khi so sánh; không dùng số click làm gate.

## 9. Test strategy và Definition of Done

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

## 10. Các quyết định cần chốt

| Thời điểm | Quyết định | Vai trò chịu trách nhiệm đề xuất |
|---|---|---|
| Trước M1 | Auth provider, session topology, team/capacity | Tech lead + product |
| Trước M3 | Cấp/lớp/môn/bộ sách, source rights/derivative retention, embedding model/dimension, AI budget | Product + chuyên môn + legal/privacy + tech |
| Trước M3 | Pháp lý dữ liệu cá nhân (mục 3.5): chuyển dữ liệu ra nước ngoài khi gọi provider, region/provider, lưu trữ, quyền xóa; kế hoạch bản quyền nội dung | Legal/privacy + product + tech lead |
| Trước M4 | Template giáo án/exports, blueprint schema và quy trình chuyên môn duyệt; cấu trúc đề thực tế đã kiểm chứng với giáo viên pilot (mục 3.5) | Chuyên môn + product |
| Trước M5/M7 | Student onboarding/consent (gồm đồng ý của cha mẹ), hosting region, provider data handling, retention, RPO/RTO đã chứng minh; owner nghiệp vụ pilot và kênh hỗ trợ (mục 3.5) | Privacy/legal + operations + product |
| Trước A1 | ADR AI-01: mở rộng provider adapter (tool-calling/streaming), SDK/model pin, cách chạy `assistant_run` job, pseudonymize tool result, budget mặc định per job; kết quả so sánh với phương án form điền sẵn không agent | Tech lead + security + product |
| Trước A1 (AI-02) | Danh sách workflow/prompt pilot, eval set, golden traces và ngưỡng chấp nhận (tỷ lệ sửa, tỷ lệ mở citation, số lần hỏi lại, time-to-draft) | Product + chuyên môn + tech |
| Trước A2 | Chính sách confirm cho từng gated action, baseline thủ công đo ở pilot, phạm vi next-action từ sự kiện | Product + chuyên môn + tech |
| Trước L1 | Learner ownership, standalone assessment schema, service auth, event broker, deletion coordination, learner quotas | Tech lead + security + product |
| Trước L3 | Kỳ thi/năm/địa phương, nguồn cấu trúc chính thức, đủ item types, examiner/rubric process | Chuyên môn + product |
| Trước A3 | Chính sách mở MCP cho client ngoài, OAuth provider/resource server, phạm vi school reporting tools | Privacy/legal + security + product |
| Trước A4 | Consent và guardrails cho learner tutor; chỉ sau gate L4 | Privacy/legal + chuyên môn + product |
| Sau pilot | OMR priority, billing provider, pricing và quotas dựa trên chi phí thật | Product + operations |

Nếu chưa có quyền shared textbooks, dùng private uploads hợp lệ cho teacher pilot và pool nội dung tự biên soạn/được phép cho self-study. Không nhập kho riêng giáo viên vào service học sinh mặc định. Phụ huynh không tự động có quyền: consent và guardian access là các workflow riêng cần thiết kế theo độ tuổi và pháp lý áp dụng.

## 11. Ước lượng và thành công

Ước lượng định hướng cho **M0–M7**: 12–18 tuần với hai dev full-time có kinh nghiệm và QA/product/chuyên môn hỗ trợ; một dev khoảng 5–8 tháng. Không phải deadline hoặc báo giá; chưa gồm L0–L4, A0–A4, OMR, billing production hay thời gian cấp phép nội dung. A1 (sau khi M4 có service thật) chưa có ước lượng; chốt sau ADR AI-01 và sau khi đo tốc độ thực tế ở M1–M2. Lean cut ở mục 3.4 là điều kiện để giữ khoảng 12–18 tuần cho M0–M7 với hai dev. Hiệu chỉnh sau M1; estimate nhánh student sau khi chốt curriculum, assessment types, corpus và extraction gate.

Đo pilot giáo viên: hoàn thành vòng dạy–học, thời gian chuẩn bị tiết kiệm, mức sửa AI, độ đúng chấm điểm, retention và cost/output. Đo student: hoàn thành task, improvement trên câu chưa gặp theo cùng kỹ năng, retention, tải học có phù hợp, tỷ lệ kết luận thiếu bằng chứng, cost/active learner. Không dùng số câu sinh ra hay điểm đề lặp làm bằng chứng duy nhất về tiến bộ.

Không triển khai code, provision service hay chạy migration chỉ bằng việc phê duyệt tài liệu này. Bước thực thi tiếp theo là M0–M1; mọi mốc còn lại, kể cả A0–A4, cần PR và acceptance evidence riêng.
