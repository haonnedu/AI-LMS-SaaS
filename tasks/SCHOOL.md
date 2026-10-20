# Backlog nhà trường — H0–H4

> Kế hoạch chưa triển khai; mọi task khởi tạo `todo`, Owner `—` (chưa phân công). Không coi tài liệu là bằng chứng hoàn thành.

Nguồn: [School management](../SCHOOL_MANAGEMENT.md), [kế hoạch triển khai](../IMPLEMENTATION_PLAN.md). Quy ước trạng thái, cách nhận việc và **gates M1, M2, M4, M5, M6, M7** xem [backlog tổng](BACKLOG.md). Gate chỉ được coi đạt khi có bằng chứng nghiệm thu; không phải chỉ khi một task đã viết code. Nhánh H độc lập nhánh [student](STUDENT.md), không bắt buộc làm xong L mới bắt đầu H.

School management bắt đầu trong core, không thêm identity/grade authority hoặc microservice bắt buộc. Mỗi slice cần contract/API có authorization, UI states phù hợp, migration/RLS khi có dữ liệu mới, tests và bằng chứng review. Chưa gồm payroll, chấm công, tối ưu thời khóa biểu hoặc AI xếp hạng giáo viên.

## H0 — School ownership và nền phân quyền

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| H0-01 | todo | — | M1; M2 | Chốt ADR onboarding trường, xác minh người đại diện, owner transfer và permission matrix admin/academic manager/tổ trưởng/teacher/billing; có bảng allow/deny theo workspace/department/class/subject, không suy ra quyền điểm/answer key từ quản lý staff. |
| H0-02 | todo | — | H0-01 | Viết migration typed scoped grants và school metadata trên membership hiện có; composite tenant FK, runtime-role RLS, expiry/revocation và constraints được kiểm tra bằng PostgreSQL thật; không tạo kho identity thứ hai. |
| H0-03 | todo | — | H0-02 | Implement API tạo school workspace/chuyển owner với idempotency, audit và concurrency protection; test không thể đình chỉ/xóa last active owner hoặc tự cấp grant cao hơn authority. |
| H0-04 | todo | — | H0-03 | Làm UI school onboarding, workspace switcher và trang quản lý quyền tối thiểu; hiện rõ cá nhân/trường, loading/error/forbidden; backend vẫn từ chối request giả workspace hoặc scope. |
| H0-05 | todo | — | H0-04 | Viết integration tests school A/B, multi-school teacher, hết hạn grant và cache invalidation; admin không đọc personal library hoặc private learner data, department membership không tự mở mọi lớp/điểm; kiểm tra API và RLS cùng fail-closed. |

## H1 — Mời và quản lý đội ngũ

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| H1-01 | todo | — | H0-05 | Migration staff profiles, departments và department memberships; profile unique theo workspace/user, mã staff unique trong trường khi có, archive giữ history; chỉ lưu dữ liệu tối thiểu, không thêm CCCD/ngân hàng. |
| H1-02 | todo | — | H1-01 | API invite/accept/revoke/resend dùng invitation hiện có, token hash/expiry/single use và outbox email; test wrong identity, replay, concurrent accept và seat reservation không tạo membership/seat trùng. |
| H1-03 | todo | — | H1-02 | API danh sách staff phân trang, chỉnh profile, phân tổ và UI roster/invite/tổ chuyên môn; kiểm tra scope server-side, hiển thị pending/expired/active và lỗi theo hành động; không auto-join theo email domain. |
| H1-04 | todo | — | H1-03 | Implement suspend/reactivate/depart membership tại trường và UI xác nhận hậu quả; revoke grants/jobs actor-dependent, audit lý do; không đình chỉ user toàn cục, không ảnh hưởng trường khác hoặc personal workspace. |
| H1-05 | todo | — | H1-04 | Kiểm thử end-to-end invite → accept → phân tổ → suspend → rejoin; assert personal content không chuyển ownership, revoked token không hoạt động và DTO roster không lộ dữ liệu không cần thiết. |

## H2 — Phân công và bàn giao

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| H2-01 | todo | — | H1-05; M5; M6 | Chốt assignment ADR và migration years/terms/teaching_assignments; một nguồn ghi duy nhất cho class–subject–teacher–term, class_teachers nếu giữ chỉ là projection/compatibility transactionally; tests cùng tenant, khoảng ngày và trùng phân công. |
| H2-02 | todo | — | H2-01 | API tạo/sửa/kết thúc assignment có expected revision, active membership và scope; test race, expired assignment và teacher chính/phối hợp; không tuyên bố phát hiện trùng tiết nếu chưa có timetable. |
| H2-03 | todo | — | H2-02 | UI năm học/học kỳ, bảng phân công và teacher dashboard theo lớp/môn được giao; có empty/conflict/forbidden states, đổi teacher không đổi class ID hoặc lịch sử bài/điểm. |
| H2-04 | todo | — | H2-03 | Migration/API handover checklist cho lớp, drafts, reviews, bài chưa chấm và jobs; recipient phải active đúng scope, audit before/after và retry idempotent; giữ tác giả, submissions và result history. |
| H2-05 | todo | — | H2-04 | UI bàn giao có pending items và xác nhận; tests revoke giữa export/worker, quyền lịch sử theo policy riêng, không bật quyền mặc định vô hạn; durable scoring đã nhận tiếp tục bằng system capability hẹp, không bỏ bài do teacher nghỉ. |

## H3 — Duyệt học vụ, báo cáo và ngân sách

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| H3-01 | todo | — | H2-05; M4; M6 | Migration work requirements, review requests/decisions với typed target FK và pinned content/exam/blueprint revision; tests cùng workspace và append-only decision history, edit bản mới không kế thừa approval cũ. |
| H3-02 | todo | — | H3-01 | API nộp/yêu cầu sửa/duyệt/publish với reviewer grants và separation-of-duties theo policy; approve không bypass rights/blueprint validation, teacher quản lý staff không tự đọc key/sửa grade; test revoked reviewer và stale revision. |
| H3-03 | todo | — | H3-02 | UI giao yêu cầu, hàng đợi duyệt và diff/status theo revision; kiểm tra loading/error/stale conflict và key/rubric chỉ hiện cho reviewer có grant; copy personal content chỉ qua typed explicit rights-checked workflow hoặc giữ tính năng tắt. |
| H3-04 | todo | — | H3-03 | API và UI reports theo tổ/lớp/môn với denominator enrolled/submitted/graded/pending; drill-down/export cần grant riêng, nhóm nhỏ theo privacy policy, không lấy private self-study hay tự xếp hạng giáo viên từ điểm trung bình. |
| H3-05 | todo | — | H3-04; M2 | Tích hợp budget trường/phân bổ con với usage ledger hiện có, migration khi cần; API/UI hiển thị giới hạn và usage đúng workspace, concurrent reserve không vượt parent ceiling; personal usage không tự charge trường, có reconciliation tests. |

## H4 — Pilot trường và readiness

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| H4-01 | todo | — | H3-05; M7 | Chốt trường pilot, retention, scope báo cáo/answer keys và onboarding checklist với người phụ trách trường; ghi acceptance criteria và exclusions, không tuyên bố compliance chỉ từ tài liệu. |
| H4-02 | todo | — | H4-01 | Chạy E2E owner → invite → phân công → review → giao/chấm → handover bằng nhiều role; lưu bằng chứng từng quyền allow/deny và kết quả không mất lịch sử khi staff rời. |
| H4-03 | todo | — | H4-02 | Diễn tập outbox replay, membership revoke, backup/restore và jobs đang chạy; late events/restore không khôi phục quyền đã thu hồi, artifacts nhạy cảm được bảo vệ và logs không chứa keys/raw answers. |
| H4-04 | todo | — | H4-03 | Load test roster/assignment/reports theo pilot envelope, kiểm tra audit, alert và redaction; có ngưỡng được chốt cùng báo cáo thực đo, runbook phục hồi và rollback migration/release. |
| H4-05 | todo | — | H4-04 | Review pilot với team/trường, ghi issue còn mở, quyết định go/no-go dựa trên privacy/security/recovery tests; chỉ mở rollout khi blockers được xử lý, không đánh dấu H4 đạt vì đã demo UI. |

**Tổng: 25 task; H0-01–H0-05, H1-01–H1-05, H2-01–H2-05, H3-01–H3-05, H4-01–H4-05.**
