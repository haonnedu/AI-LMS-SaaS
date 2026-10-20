# Eduvia — Nhà trường quản lý giáo viên

> Ngày: 2026-10-21. Trạng thái: thiết kế đề xuất, chưa implement. Nhánh mở rộng sau pilot giáo viên; không phải HR/payroll hoặc chứng nhận đáp ứng pháp lý.

## 1. Mục tiêu và phạm vi

Bổ sung trụ cột **school-led** bên cạnh teacher-led và student-led: nhà trường tổ chức đội ngũ, phân công giảng dạy, chuẩn hóa nội dung/đề kiểm tra và theo dõi công việc học vụ trong workspace của trường.

Đọc cùng [kế hoạch triển khai](IMPLEMENTATION_PLAN.md), [kiến trúc](ARCHITECTURE.md), [database](DATABASE.md), [cấu trúc đề](EXAM_BLUEPRINTS.md) và [student-learning](STUDENT_LEARNING.md).

Vòng sử dụng: tạo school workspace → mời giáo viên → xếp tổ chuyên môn → phân công lớp/môn/học kỳ → giáo viên soạn và nộp học liệu → review/publish → giao bài/chấm điểm → nhà trường xem báo cáo đúng quyền → bàn giao khi thay nhân sự.

**School MVP:** danh sách giáo viên, invitation/membership, tổ chuyên môn, năm học/học kỳ, phân công giảng dạy, quyền theo phạm vi, dashboard công việc, audit và offboarding. Workflow duyệt học liệu/đề và quota được bổ sung từng milestone.

**Ngoài scope đầu:** lương, hợp đồng lao động đầy đủ, chấm công sinh trắc học, đánh giá kỷ luật tự động, xếp thời khóa biểu tối ưu, quản lý nhiều cơ sở phức tạp, hồ sơ sức khỏe, phụ huynh và tích hợp SIS/HR diện rộng. Không tự xếp hạng chất lượng giáo viên bằng AI hoặc điểm trung bình lớp.

## 2. Ownership và nguyên tắc quyền

- Một trường tương ứng một workspace loại school ở giai đoạn đầu; có thể có nhiều tổ chuyên môn. Multi-campus là extension riêng.
- User là danh tính toàn cục; school staff profile và membership là bản ghi thuộc trường. Một giáo viên có thể tham gia nhiều trường và vẫn giữ personal workspace riêng.
- Chấp nhận lời mời không chuyển nội dung cá nhân sang trường. Không tự lấy tài liệu, prompts, usage hoặc lịch sử cá nhân của giáo viên.
- Nội dung tạo trong school workspace thuộc phạm vi quản lý của trường theo thỏa thuận sử dụng; quyền truy cập kỹ thuật không tự giải quyết quyền tác giả/pháp lý.
- Chỉ copy nội dung cá nhân sang trường bằng thao tác rõ ràng, kiểm tra license và provenance; tạo ID/revision mới độc lập. Question/exam/document copying chỉ mở khi typed workflow tương ứng được implement, không dùng generic clone.
- Trường không mặc nhiên đọc personal self-study của học sinh, kể cả trường trả tiền. Dữ liệu lớp và hồ sơ tự học là hai phạm vi khác nhau.
- Platform admin không là school staff mặc định; hỗ trợ khẩn cấp cần break-glass có thời hạn, lý do và audit.

## 3. Vai trò và permission matrix

Các nhãn dưới là **permission bundles đề xuất**, không phải thêm tất cả vào role enum hiện tại ngay. Giữ membership owner/admin/teacher/student và bổ sung grants có scope khi cần; mọi role/schema migration phải được review.

| Bundle | Quyền mặc định đề xuất | Không được mặc định |
|---|---|---|
| School owner | Quản trị workspace, bổ nhiệm admin, chuyển owner, cấu hình gói/quota | Xem tài liệu cá nhân hoặc mọi answer key |
| School admin / giáo vụ | Mời/quản lý staff, tổ chức học kỳ, phân công lớp/môn, xem tình trạng vận hành | Sửa điểm, đọc toàn bộ bài học sinh hay publish đề nếu chưa có academic grant |
| Academic manager / BGH được phân quyền | Báo cáo học vụ toàn trường, duyệt nội dung theo grant, thiết lập quy trình chuyên môn | Quyền billing/owner hoặc sửa điểm không audit |
| Department head / tổ trưởng | Danh sách và công việc tổ được giao; review nội dung thuộc tổ | Quản lý tổ khác hoặc tự nâng quyền thành admin |
| Teacher | Lớp/môn được phân công; soạn, nộp duyệt, giao bài/chấm theo grant | Xem mọi lớp chỉ vì có school membership |
| Billing manager tùy chọn | Subscription, usage và budget summaries | Bài làm, hồ sơ cá nhân, answer keys |

School admin có thể đồng thời được giao academic manager, nhưng hai quyền phải explicit. Quyền quản lý nhân sự không đồng nghĩa quyền xem đáp án. Teacher grading privileges là lớp riêng, không suy ra từ quyền sửa nội dung.

Grant gồm permission, scope loại workspace/department/class/subject, khoảng hiệu lực và người cấp. Không cho tự cấp quyền cao hơn authority của mình. Membership phải active trước khi xét grant. Department membership chỉ thể hiện tổ chức; không tự mở toàn bộ điểm/lớp của thành viên.

## 4. Các workflow nghiệp vụ

### 4.1 Khởi tạo trường và owner

Xác minh người tạo có quyền đại diện theo quy trình onboarding B2B, tạo school workspace và owner membership. Email cùng domain không đủ tự gia nhập trường. Phải còn ít nhất một active owner; transfer ownership là transaction có xác nhận, audit và bảo vệ race. Không xóa/đình chỉ last owner trước khi bàn giao.

### 4.2 Mời và quản lý giáo viên

1. Admin nhập email và bundle/scope được phép; server kiểm tra seat budget.
2. Tạo invitation có token hash, expiry, single use; gửi email bằng outbox.
3. Người nhận đăng nhập, xác minh đúng email/identity và xác nhận tham gia; không auto-link chỉ từ tên.
4. Provision membership/staff profile idempotently; giữ nguyên personal workspace.
5. Phân tổ và giao scope cụ thể; invitation chưa chấp nhận không có quyền đọc.

Invite lifecycle: pending → accepted/expired/revoked. Resend tạo hoặc xoay token có kiểm soát, token cũ mất hiệu lực. Staff lifecycle: active → suspended → active hoặc departed; rời trường không xóa account toàn cục. Bulk CSV có dry-run, validation, lỗi theo dòng và tránh gửi thư trùng; làm sau luồng đơn ổn định.

Thông tin staff tối thiểu: mã nội bộ theo trường, tên hiển thị, email liên hệ, môn chuyên môn, tổ, trạng thái, ngày tham gia/rời. Không thu CCCD, tài khoản ngân hàng hoặc giấy tờ nhạy cảm khi chưa có use case và cơ sở xử lý.

### 4.3 Tổ chuyên môn và phân công giảng dạy

Admin tạo năm học/học kỳ, tổ, lớp và danh mục môn. Phân công tham chiếu giáo viên active, lớp, môn, học kỳ, vai trò chính/phối hợp và khoảng hiệu lực. Cùng giáo viên có thể dạy nhiều lớp và nhiều trường.

- Chặn liên kết khác workspace bằng composite FK và authorization.
- Kiểm tra phân công trùng và khoảng thời gian không hợp lệ; quy định một/nhiều giáo viên chính phải được cấu hình rõ.
- Nếu chưa có timetable, chỉ báo trùng phân công/khối lượng, không tuyên bố phát hiện trùng tiết.
- Không cho sửa trực tiếp hai nguồn class_teachers và teaching assignments. Chọn một assignment authority; class_teachers là projection/compatibility relation được cập nhật transactionally nếu giữ.
- Hết hạn phân công thu hồi quyền thao tác mới; quyền xem lịch sử là policy riêng, không mặc định tồn tại vô hạn.
- Thay giáo viên không đổi ID lớp, bài đã giao, tác giả hoặc lịch sử điểm.

### 4.4 Giao kế hoạch và theo dõi công việc

Giáo vụ/tổ trưởng có thể đặt yêu cầu nộp giáo án, lịch kiểm tra hoặc checkpoint theo môn/học kỳ. Dashboard hiển thị chưa giao, đang làm, đã nộp, cần sửa, đã duyệt, quá hạn; deadline theo timezone trường, lưu UTC.

Báo cáo nhằm điều phối công việc, không suy ra năng lực giáo viên từ số lượt login, số prompts hoặc số tài liệu sinh. Số tiết/khối lượng chỉ là dữ liệu đã khai báo/phân công, không tương đương chấm công.

### 4.5 Review giáo án và cấu trúc đề

Workflow đề xuất: draft → submitted → changes_requested → resubmitted → approved → published. Rejected/withdrawn cần lý do. Review request pin exact content revision hoặc exam/blueprint revision; nếu tác giả sửa, approval cũ không áp dụng cho bản mới.

- Tổ trưởng hoặc reviewer được giao duyệt trong scope; không tự duyệt nếu trường bật separation-of-duties.
- Approval chuyên môn không tự bỏ qua kiểm tra license, schema, blueprint và student-safe serialization.
- Publish cần cả grant phù hợp và validation current; không coi approved là automatic published.
- School blueprint thuộc private school scope; không tự gắn verified official label.
- Quyền xem key/rubric chỉ reviewer thực sự cần; học sinh không đọc được qua review/export API.
- Sửa đề đã giao tạo version mới; điểm/override tiếp tục qua core assessment có audit, không có chức năng admin sửa số điểm trực tiếp.

### 4.6 Báo cáo nhà trường

Dashboard có danh sách giáo viên active/pending/suspended, phân công theo tổ/lớp/môn, lớp chưa có giáo viên, tiến độ review, các bài chưa chấm, trạng thái release kết quả và usage trường.

Báo cáo học tập tổng hợp dùng mẫu số rõ (enrolled/submitted/graded/pending), không biến pending thành 0. Drill-down tới học sinh/bài làm cần grant riêng và mục đích phù hợp. Giới hạn nhóm nhỏ/khả năng tái nhận dạng theo policy được chốt trước rollout; không coi aggregate là tự động vô danh.

Không lấy điểm trung bình hai lớp khác đầu vào hoặc độ khó đề để tự động kết luận giáo viên tốt/xấu. Báo cáo mô tả phạm vi và thiếu dữ liệu, không đưa khuyến nghị kỷ luật bằng AI.

### 4.7 Quota và ngân sách

School workspace có pool AI/storage/seats; tùy chọn phân bổ budget theo tổ/giáo viên. Chốt quy tắc tổng child allocations không vượt parent budget hoặc dùng shared ceiling được diễn đạt rõ. Reserve đồng thời phải atomic dưới parent limit; failed/expired reservations được reconcile.

Usage charge theo workspace đang thao tác và execution ID, không theo email giáo viên. Hoạt động personal workspace và self-study không tự tiêu ngân sách trường. Seat lifecycle và billing proration là quyết định thương mại riêng; school MVP có thể cấp quota thủ công, không đợi payment gateway.

### 4.8 Nghỉ việc, đình chỉ và bàn giao

Thu hồi membership/grants trước, invalidate permissions, chặn job/export chưa chạy theo authority mới. Không đình chỉ user toàn nền tảng vì rời một trường. Một trường không thu hồi quyền ở trường khác hoặc personal workspace.

Bàn giao có checklist: lớp/môn còn active, tài liệu draft cần người tiếp quản, pending reviews, bài chưa chấm, jobs/export và delegation. Người nhận phải là thành viên active có scope phù hợp. Lưu người thực hiện, lý do, before/after và thời gian.

School-owned records vẫn ở trường; không rewrite tác giả lịch sử hoặc xóa bài nộp để hoàn thành offboarding. Durable scoring đã được nhận hợp lệ xử lý bằng quyền hệ thống hẹp, không bị bỏ mất chỉ vì giáo viên nghỉ. Job mới phục vụ actor bị thu hồi phải fail/reauthorize; không chạy bằng cached role cũ.

## 5. UX đề xuất

School workspace có navigation: **Tổng quan · Giáo viên · Tổ chuyên môn · Năm học/Học kỳ · Phân công · Duyệt học liệu/Đề · Báo cáo · Quota/Gói dịch vụ · Audit/Cài đặt**.

Teacher workspace switcher luôn chỉ rõ đang ở cá nhân hay trường. Teacher trong trường thấy phân công của mình, yêu cầu cần hoàn thành và trạng thái review; không dùng cùng một menu admin rồi chỉ ẩn nút bằng frontend.

Màn hình quan trọng: invite hết hạn, thiếu seat, phân công xung đột, quyền vừa bị thu hồi, revision đã thay đổi, bàn giao chưa đủ người nhận. Không báo thành công nếu transaction chưa commit.

## 6. Kiến trúc và service boundary

**Đề xuất ban đầu:** school-management là module core, dùng identity/workspaces/teaching/assessment hiện có qua application services. Không tạo teacher identity hoặc school grade authority thứ hai. Membership, grants và assignment cần transaction/policy nhất quán nên chưa cần một microservice riêng chỉ cho danh sách giáo viên.

Student-learning vẫn deploy riêng khi đạt gate. School module không SELECT learner database, không dùng school admin token để đọc mastery cá nhân. Chỉ dùng API/events với grant và consent phù hợp cho từng mục đích.

Nếu sau này tách School Administration API vì team/release cadence độc lập: giữ identity/membership authorization authority duy nhất, định nghĩa owner cho tổ/phân công và API xác minh current grants; projection sự kiện không thay authorization lúc thu hồi. Không dual-write assignments hoặc direct cross-service DB joins. Cần ADR cutover, outbox/inbox, replay, deletion và failure behavior trước tách. Không nằm trong school MVP.

## 7. Catalog dữ liệu đề xuất

Tất cả bảng school-owned có workspace_id non-null, composite tenant FK, RLS và timestamps/lock_version theo [DATABASE.md](DATABASE.md). Tên dưới là đề xuất, chưa phải migration.

| Entity | Vai trò và invariant |
|---|---|
| workspaces / workspace_members / workspace_invites | Tái sử dụng school tenancy và identity; không tạo kho password mới |
| school_staff_profiles | One profile/workspace/user; employee code unique theo trường khi có; không dùng profile status thay membership authority |
| school_departments | Tổ chuyên môn; mã unique trong workspace; archive thay xóa khi còn history |
| school_department_members | Staff–department, vai trò tổ chức và thời gian; không tự cấp quyền học vụ |
| school_academic_years / school_terms | Khoảng ngày hợp lệ; term thuộc year cùng trường; quy tắc chồng lấn rõ |
| teaching_assignments | Staff/class/subject/term, role và hiệu lực; authority cho phân công; active membership kiểm tra tại command |
| school_staff_grants | Permissions typed scopes workspace/department/class/subject; target refs có integrity checks; expiry/revocation/audit |
| school_work_requirements | Yêu cầu công việc/đề/giáo án, scope, deadline, người giao |
| school_review_requests / school_review_decisions | Pin revision và reviewer scope; append-only decisions; edited revision cần review mới |
| school_staff_handovers / school_handover_items | Checklist bàn giao, người nhận, trạng thái và provenance; không rewrite history |
| school_budget_allocations | Tùy chọn hạn mức con; dùng chung usage reservation/ledger, không ledger billing thứ hai |
| audit_events / outbox_events | Tái sử dụng domain audit và durable delivery |

Grant scope dùng typed FK/bảng liên kết thích hợp với CHECK đúng một target; không JSON arbitrary scope được tin như quyền. Review targets theo content/exam/blueprint có typed FK và same-workspace checks. RLS baseline staff hiện tại cần thu hẹp theo scope trước mở school dashboard; role teacher đơn thuần không được đọc tất cả school data.

## 8. API và events khái niệm

Chưa có endpoint dưới đây trong OpenAPI. Mọi mutation có verified actor, workspace, idempotency key/request hash hoặc expected revision, audit và operation-specific authorization.

- `POST /v1/workspaces/{w}/staff-invitations`: mời staff theo scope được phép.
- `GET /v1/workspaces/{w}/staff`: danh sách lọc/phân trang, DTO tối thiểu.
- `POST /v1/workspaces/{w}/staff/{id}/suspend`: thu hồi quyền tại trường.
- `POST /v1/workspaces/{w}/departments`: tạo tổ.
- `POST /v1/workspaces/{w}/teaching-assignments`: phân công, kiểm tra constraint/race.
- `POST /v1/workspaces/{w}/review-requests`: nộp exact revision.
- `POST /v1/workspaces/{w}/review-requests/{id}/decisions`: approve/changes requested theo policy.
- `POST /v1/workspaces/{w}/staff/{id}/handovers`: bàn giao có trạng thái.
- `GET /v1/workspaces/{w}/school-reports`: báo cáo đã scope, không generic export toàn trường.

Events ví dụ: `school.staff.membership_changed`, `school.teaching_assignment.changed`, `school.review.decided`, `school.handover.completed`. Local transaction + outbox, consumer inbox dedupe và aggregate version. Payload tối thiểu, không gửi raw student results/answer keys trên bus; event chỉ thông báo, caller vẫn phải authorize khi fetch.

## 9. Roadmap H0–H4 và nghiệm thu

Nhánh school sau các gate core, không đợi hoàn tất student self-study và không âm thầm đưa vào M0–M7.

| Mốc | Phạm vi | Phụ thuộc / exit gate |
|---|---|---|
| H0 — School permission foundation | School onboarding/owner, scope matrix, RLS tests và ADR role mapping | M1/M2; last-owner race, school A/B, personal isolation và revoked grants pass |
| H1 — Staff operations | Mời, roster, tổ, profile tối thiểu, suspend/rejoin, seat checks | H0; accept idempotent, token expiry/revoke, multi-school independence |
| H2 — Teaching assignments | Năm học/học kỳ, phân công, teacher dashboard, handover | H1 + M5/M6; single assignment authority, scope expiry, không mất bài/điểm khi thay giáo viên |
| H3 — Academic governance | Nộp/duyệt học liệu/blueprint, school reports, budget allocation | H2 + M4/M6; revision-pinned approval, no self-approve nếu policy bật, key protection, report permissions |
| H4 — School pilot | Onboarding trường nhỏ, security/load/recovery, retention/privacy review | M7 + H3; hoàn thành mời → phân công → duyệt → giao/chấm → bàn giao; quyền thu hồi có hiệu lực và audit đầy đủ |

OMR, billing automation và SIS integrations là các nhánh riêng. Không ước lượng lịch H0–H4 trước khi biết số trường/giáo viên, cơ cấu tổ và yêu cầu báo cáo.

## 10. Acceptance tests bắt buộc

- Admin trường A không đọc/sửa staff/grants/assignments của B; giáo viên nhiều trường không rò scope khi switch.
- School owner/admin không đọc personal teacher library hoặc personal learner mastery mặc định.
- Last owner transfer/suspend concurrent vẫn giữ active owner hợp lệ.
- Invite replay, revoked token, wrong identity và concurrent accept không tạo membership/seat trùng.
- Tổ trưởng không tự nâng quyền; department membership không tự mở lớp/answer keys.
- Assignment trùng/khác tenant/hết hạn bị chặn; teacher mất quyền đúng lớp, không mất quyền ở trường khác.
- Approval pin exact revision; sửa nội dung hoặc mất quyền reviewer không publish bằng approval không hợp lệ.
- Giáo vụ không sửa điểm hoặc key chỉ nhờ quyền quản lý staff; mọi grade override đi qua assessment audit.
- Suspend trong lúc worker/export chạy reauthorize trước phát artifact; signed downloads có TTL ngắn và không hứa thu hồi file đã tải.
- Handover giữ school records, tác giả và grading history; nhận pending scoring bằng system capability hẹp.
- Reports không coi chưa chấm là 0; drill-down/export có grants và hạn chế nhóm nhỏ theo policy.
- Quota parent/child races, cache invalidation, event replay, deletion/restore không khôi phục quyền đã thu hồi.

## 11. Quyết định cần chốt

Loại trường/cơ sở pilot; ai xác minh school owner; một hay nhiều owner; cơ cấu tổ; môn/lớp/học kỳ; ai được xem điểm chi tiết và answer keys; quy tắc self-approval; quyền lịch sử sau hết phân công; nguồn nội dung và copy rights; seat/budget policy; lưu giữ hồ sơ sau nghỉ; quy trình guardian/consent nếu chia sẻ self-study; có cần homeroom/timetable hay chỉ subject assignments.

Ưu tiên khởi đầu: **H0–H2: trường mời giáo viên, phân tổ, phân công và bàn giao an toàn**. H3 bổ sung duyệt học liệu và báo cáo khi quy trình thực tế của trường đã được xác nhận.
