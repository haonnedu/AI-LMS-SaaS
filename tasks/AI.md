# Backlog AI tác vụ và MCP — A0–A1

> Cập nhật: 2026-10-22 (thu gọn cùng ngày theo review). Kế hoạch chưa triển khai; mọi task khởi tạo `todo`, Owner `—` (chưa phân công). Tài liệu này không phải bằng chứng tính năng đã có. A2–A4 mới có phạm vi trong [kế hoạch triển khai mục 8.4](../IMPLEMENTATION_PLAN.md); task cho các mốc đó chỉ tạo sau khi A1 có evidence và baseline pilot M7 được đo.

Nguồn: [kế hoạch triển khai — mục 3.4, 3.5, 8](../IMPLEMENTATION_PLAN.md), [ARCHITECTURE — mục 7, 10, 12](../ARCHITECTURE.md), [DATABASE — mục 9](../DATABASE.md), [MCP dev-only](../tools/eduvia-mcp/README.md), [Postgres MCP dev](../tools/MCP_INTEGRATION.md). Quy ước trạng thái, cách nhận việc và **gate M4** xem [backlog tổng](BACKLOG.md); dependency là điều kiện có bằng chứng nghiệm thu, không phải lịch.

Ranh giới nhánh A: tool registry chạy **cùng process** trong core API, mỗi lượt trợ lý là một `background_job` kind `assistant_run` để dùng lại reservation, retry và resume của M2; không có transport MCP, token riêng hay service account cho agent trước A3. Tool là adapter mỏng trên application services đã có, chạy dưới quyền của actor thật với transaction-local context của M1; tool result không chứa định danh học sinh. Mọi output AI là draft/proposal; publish, giao bài, release điểm, mời học sinh luôn qua xác nhận của người và chính sách release giữ mặc định `manual`. Không tạo tool cho tính năng chưa có service thật. Nhánh A **không phải điều kiện của pilot M7**.

Thước đo chính: tỷ lệ draft được duyệt không sửa lớn, tỷ lệ mở citation trước khi duyệt, thời gian tới bản nháp, số câu hỏi làm rõ. Không dùng số click, số tool hoặc số lượt gọi model làm bằng chứng.

## A0 — Dev tooling

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| AIDEV-01 | todo | — | — | Sửa `tools/MCP_INTEGRATION.md`: bỏ connection string superuser và nội dung hội thoại, mô tả role Postgres chỉ đọc (SELECT trên schema ứng dụng, không ghi, không đọc bảng audit/credential), xác minh package MCP Postgres còn được bảo trì hoặc chọn thay thế; file cấu hình mẫu không chứa credential thật và không trỏ staging/prod; secret scan pass. |
| AIDEV-02 | todo | — | AIDEV-01 | Hướng dẫn dùng hai MCP dev-only (`tools/eduvia-mcp`, Postgres dev) cho cả hai máy phát triển; xác nhận `eduvia-mcp` không đọc `.env`/secrets và track `ai` hiển thị đúng trong `get_backlog_summary`; evidence là log chạy thật trên cả hai máy. |

## A1 — Authoring assistant

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| AI-01 | todo | — | M4, ACL-01 | ADR AI-01: mở rộng provider adapter (tool-calling, structured output, streaming), SDK/model pin và cách chuyển tool schema sang provider; mô hình `assistant_run` job; pseudonymize tool result; phân lớp tool read/propose/gated/never; budget per job; so sánh với phương án form điền sẵn không agent cho từng workflow; threat cases confused deputy, prompt injection, cross-workspace read. |
| AI-02 | todo | — | AI-01, AUTHR-02 | Chốt 2–3 workflow pilot và eval set tiếng Việt do chuyên môn duyệt; golden traces (tool đúng, thứ tự hợp lý, không hỏi thừa) dạng fixture chạy offline trong CI; ngưỡng chấp nhận cho tỷ lệ sửa, tỷ lệ mở citation, số lần hỏi lại, time-to-draft; quy tắc chạy lại eval khi đổi model/provider. |
| AI-03 | todo | — | AI-01, JOB-05, COST-02, AUDIT-01 | Job kind `assistant_run` và bảng `assistant_tool_calls` (job, tool, lớp, request hash, trạng thái, size, cost ref) với RLS/composite FK; reservation per job, cap cứng per workspace/tháng, rate limit per user; worker reauthorize actor trước mỗi tool call; retention, không lưu raw tool output ngoài allowlist. |
| AI-04 | todo | — | AI-01 | Tool registry in-process: mỗi tool khai báo lớp, schema pydantic theo định dạng MCP, audience DTO và cờ pseudonymize; registry từ chối tool thiếu metadata; snapshot JSON Schema tool/resource/prompt vào `contracts/` và CI diff chặn breaking change. |
| AI-05 | todo | — | AI-03, AI-04 | Read tools library/content: `get_workspace_context`, `list_documents`, `get_document_outline`, `search_library` (bọc authorized retrieval M3, citations, license revoke chặn ngay), `list_content_items`, `get_content_revision`; pagination, size limit, DTO allowlist; tests không ghi DB, cross-tenant và missing-context deny bằng runtime role. |
| AI-06 | todo | — | AI-05, AUTHR-03 | Propose tools `draft_lesson_plan`, `draft_study_guide` gọi service AUTHR-03: idempotency key theo job, citations bắt buộc khi có nguồn, ghi `draft`/`in_review`; không publish; injection corpus từ tài liệu không đổi policy. |
| AI-07 | todo | — | AI-05, BP-03 | Propose tool `draft_quiz_from_blueprint` gọi BP-03: shortage báo rõ slot thiếu, không âm thầm đổi matrix; output chỉ teacher audience; answer key không rời service qua tool result. |
| AI-08 | todo | — | AI-04, AI-02 | Resources (hồ sơ giảng dạy, curriculum/bộ sách đã chọn, template, library snapshot) và prompts cho workflow pilot với tham số mặc định chỉ cho nội dung soạn thảo; test resource không lộ dữ liệu ngoài quyền và không chứa định danh học sinh. |
| AI-09 | todo | — | AI-06, AI-07, AI-08 | Orchestrator qua provider adapter chạy trong `assistant_run`: context-first, trần số câu hỏi làm rõ, structured output cho proposal, resume job sau đóng tab, retry/timeout không nhân đôi draft; log redaction; integration test với provider mock và một smoke staging có evidence. |
| AI-10 | todo | — | AI-09 | Assistant panel trong app: nhập yêu cầu, tiến trình job, preview/diff draft với citations mở được tại chỗ, approve mở đúng revision trong editor; loading/empty/error/budget states; accessibility; AI outage hoặc hết budget ẩn panel nhưng editor thủ công đầy đủ. |
| AI-11 | todo | — | AI-10 | Metrics: tỷ lệ draft duyệt không sửa lớn, tỷ lệ mở citation, time-to-draft, số câu hỏi làm rõ, tool error rate, cost per workflow đối chiếu giá gói; không learner/student IDs trong labels; dashboard nội bộ và cách đo baseline thủ công ở pilot. |
| AI-12 | todo | — | AI-11 | A1 QA và gate: ma trận tool × vai trò × audience, cross-tenant, missing context, job sau khi membership bị thu hồi, schema snapshot, size limit, budget cap, không lộ định danh học sinh trong tool result/prompt log; draft không tự publish; injection corpus; outage; eval và golden traces đạt ngưỡng AI-02; evidence trên PostgreSQL thật. |

## Gate và bằng chứng

| Gate | Điều kiện nghiệm thu |
|---|---|
| A0 | AIDEV-01, AIDEV-02 đạt; không có credential trong cấu hình; tooling không trỏ ngoài DB dev |
| A1 | AI-01–AI-12 đạt; cross-tenant/missing-context deny bằng runtime role; schema snapshot trong `contracts/`; tool result không chứa định danh học sinh; eval và golden traces đạt ngưỡng; AI outage không chặn soạn tay |
| A2, A3, A4 | Chưa có task; phạm vi và exit gate ở kế hoạch triển khai mục 8.4. A2 tạo task sau khi A1 có evidence và baseline pilot M7 được đo; A3 cần client ngoài thật; A4 chỉ sau gate L4 |

- Evidence mỗi task ghi trong PR hoặc execution record theo mẫu ở [backlog tổng](BACKLOG.md): task ID, commit/PR, lệnh/bộ test và kết quả, reviewer, quyết định/blocker.
- Không mark done vì đã có tool schema hoặc demo chạy một lần; A1 cần test authorization trên PostgreSQL thật và eval do chuyên môn duyệt.
- Hiện chưa có task nào được nhận hoặc nghiệm thu.
