# Eduvia — Full project backlog

> Cập nhật: 2026-10-21. Tracker chung cho nhóm 2 người. **Đây là kế hoạch, không phải danh sách tính năng đã implement.** Toàn bộ task ban đầu là `todo` vì chưa có bằng chứng nghiệm thu từng task. Scaffold hiện có vẫn cần baseline verification.

## 1. Nguồn sự thật và cách tìm task

| Nhánh | Tracker chi tiết | Phạm vi |
|---|---|---|
| Core | [CORE.md](CORE.md) | M0–M7: setup, identity/RLS, jobs/quota/storage, RAG, authoring/blueprints, classes, assessment, pilot |
| Nhà trường | [SCHOOL.md](SCHOOL.md) | H0–H4: teacher lifecycle, scopes, tổ chuyên môn, phân công, duyệt và pilot trường |
| Học sinh | [STUDENT.md](STUDENT.md) | L0–L4: skills, independent learning, standalone assessment, planner, mock exams, adaptive gates |
| OMR, billing và mở rộng | [OMR_BILLING.md](OMR_BILLING.md) | Các nhánh tùy chọn sau core gates; discovery cho phạm vi tương lai |

Thiết kế nguồn: [delivery plan](../IMPLEMENTATION_PLAN.md), [architecture](../ARCHITECTURE.md), [database](../DATABASE.md), [development](../DEVELOPMENT.md), [blueprints](../EXAM_BLUEPRINTS.md), [school](../SCHOOL_MANAGEMENT.md), [student](../STUDENT_LEARNING.md).

**Trạng thái chỉ được sửa tại hàng task trong tracker chi tiết**, không sao chép danh sách trạng thái vào file này. DSH Todo là checklist phiên làm việc, không đồng bộ tự động giữa hai người hoặc với Git. Khi kết thúc phiên, cập nhật task trong repo cùng evidence. Nếu chuyển sang GitHub Issues, thực hiện cutover rõ: Issues thành state authority, Markdown giữ scope/design và mapping ID→Issue; không duy trì hai board trạng thái thủ công.

## 2. Quy tắc làm việc cho hai người

- Mỗi task có **một owner**; `—` là chưa nhận việc. Hai người chốt tên/handle trong SET-01, không tự giả định ai làm backend/frontend.
- Trước khi nhận: pull/rebase thay đổi mới, đọc dependencies, sửa owner/status rồi push hoặc mở draft PR để người kia thấy. Git không có task lock: nếu cùng nhận, dừng và thống nhất trước khi code.
- Branch gợi ý: `feat/DB-02-identity-schema`; PR gắn task ID, scope, test evidence và migration impact.
- Người còn lại review; không cùng sửa một migration/schema contract chưa thống nhất. Khi tách nhánh song song, thống nhất migration identifiers và API types trước merge.
- Một task `in_progress` chính/người; có thể review task của nhau song song. Chia thêm task nếu khó review trong một PR nhỏ.
- Không bắt buộc mỗi task đúng một ngày. Các hàng là work packages có nghiệm thu; nếu vượt khoảng 1–2 ngày dự kiến, tách ID con như `DB-02a`, cập nhật dependencies trước làm. Không đánh dấu parent done khi còn con chưa nghiệm thu.
- Task không còn cần dùng `cancelled` cùng lý do, không xóa ID đã được tham chiếu. Scope mới thêm ID mới; giữ SET/BASE/AUTH/DB/BE/FE/QA/DOC cũ để không mất lịch sử.

### Trạng thái

| Giá trị | Ý nghĩa |
|---|---|
| todo | Chưa bắt đầu; không đồng nghĩa đã đủ dependency |
| ready | Dependencies đạt, scope/acceptance rõ, có thể nhận |
| in_progress | Owner đang thực hiện |
| review | PR và evidence đã sẵn sàng, chờ người thứ hai |
| blocked | Ghi blocker cụ thể, người giải quyết và điều kiện mở lại |
| done | Đạt acceptance + Definition of Done, đã merge hoặc có quyết định nghiệm thu được ghi |
| cancelled | Bỏ phạm vi có lý do và ghi tác động dependencies |

DSH Todo chỉ có pending/in_progress/completed: map todo/ready→pending; review vẫn in_progress nếu còn việc; blocked giữ pending với ghi chú. Không map cancelled thành completed mà không nói rõ.

### Ghi chú và evidence của task

Thêm subsection ngay trong tracker chứa task khi nhận việc:

```text
### DB-02 — execution record
Owner: <handle>
Reviewer: <handle còn lại>
Branch/PR: <link>
Acceptance bổ sung / ngoài scope: ...
Commands + kết quả + môi trường: ...
Evidence/artifact: ...
Blocker / người xử lý / điều kiện mở lại: ...
Ngày cập nhật: ...
```

Không lưu secrets, raw student data hoặc credential-bearing URLs trong evidence. Với task chỉ có ADR, evidence là decision record đã review; không yêu cầu application test giả tạo.

## 3. Definition of Done

1. Acceptance ở hàng task đạt; scope thay đổi được review, không chỉ hoàn thành code.
2. Tests liên quan pass trên môi trường thật phù hợp: DB/RLS bằng runtime role, provider integration có staging/manual evidence nếu cần; mocks không thay mọi integration check.
3. Lint/typecheck/build áp dụng pass; migrations/contract generation và rollback/forward-fix được xem xét khi có thay đổi.
4. Permission/tenant/privacy/error states được kiểm tra cho endpoint/UI/job mới. Không secrets/answer keys lọt DTO/log/export ngoài quyền.
5. Người thứ hai review; PR/commit và kết quả kiểm tra được ghi, docs cập nhật nếu behavior thay đổi.
6. Chỉ mark done sau các điều kiện trên. Viết tài liệu backlog không hoàn thành task sản phẩm bên trong.

## 4. Dependencies và milestone gates

Cột Phụ thuộc sử dụng task ID hoặc gate trong bảng dưới. Dấu phẩy hoặc chấm phẩy là **AND**. `—` không có prerequisite task, vẫn phải tuân policy. Gate nghĩa toàn bộ task của milestone đã nghiệm thu, không chỉ có skeleton. Gate không được hiểu là task ID mới hoặc một trạng thái tự động tính bởi DSH.

| Gate | Điều kiện nghiệm thu |
|---|---|
| M0 | Nhóm M0 trong CORE đạt: baseline reproducible, auth/tenant/schema/pilot/deployment decisions được chốt |
| M1 | Nhóm M1 đạt: session/onboarding/isolation/revocation/concurrency và E2E pass |
| M2 | Nhóm M2 đạt: jobs recover, quota races an toàn, private storage và audit có tests |
| M3 | Nhóm M3 đạt: rights-aware versioned ingestion/retrieval/citations/deletion và RAG eval |
| M4 | Nhóm M4 đạt: manual/AI review, single-choice blueprint validation, immutable exam và safe exports |
| M5 | Nhóm M5 đạt: invitations/enrollment/assignments/mobile portal với class isolation |
| M6 | Nhóm M6 đạt: server-authoritative attempts/save/submit/scoring/release/corrections và race tests |
| M7 | Nhóm M7 đạt: security/load/privacy/restore/deployment/pilot signoff |
| H0–H4 | Mỗi gate Hn đạt khi tất cả task trong mục Hn của SCHOOL và dependencies đạt |
| L0–L4 | Mỗi gate Ln đạt khi tất cả task trong mục Ln của STUDENT và dependencies đạt; optional extraction/adaptive quyết định explicit theo gate, không mặc nhiên bắt buộc |

Luồng core chính M0→M1→M2→M3→M4→M5→M6→M7. CLASS-01..04 có thể bắt đầu sau M1 song song jobs/RAG, nhưng assignment publication phải đợi M4. Bảng task là authority cho phụ thuộc cụ thể.

**H, L, OMR, billing là các nhánh ưu tiên riêng**, không phải Phase 6→7 bắt buộc và không tự nằm trong estimate M0–M7. H0 có thể thiết kế sau nền core cần thiết; trường pilot cần full H4 gates. L không cần fake teacher class và không bắt buộc deploy microservice ngày đầu. Không chạy toàn bộ nhánh cùng lúc với team 2 người.

## 5. Bắt đầu thế nào / chia việc song song

| Đợt | Người A (đề xuất, chưa assign) | Người B (đề xuất, chưa assign) | Gate phối hợp |
|---|---|---|---|
| Baseline | SET-02, BASE-01/02/04 | SET-01, BASE-03 sau BASE-01 | Cùng review BASE-05 và quyết định M0 |
| Identity | DB-01..05 và provisioning backend | Session flow/UI, contract fixtures sau chốt AUTH-02 | UI mock chỉ phục vụ phát triển, không đánh dấu integration done |
| Jobs/RAG | Jobs/storage/ingest | Progress/library UI + contract và fixtures | Review quota/rights tests trước tích hợp |
| Authoring | Bank/blueprint validation + publication | Manual editor/review/export UX | Chốt revisions và audience DTO trước |
| Teaching/assessment | Attempt/scoring concurrency | Class/student quiz/results UI | Cùng kiểm thử deadline/reconnect/key leakage |
| Pilot | Deploy/restore/observability | E2E/accessibility/onboarding | Cả hai signoff, có owner nghiệp vụ |

**Việc đầu tiên:** SET-01, SET-02 rồi BASE-01. Sau đó BASE-02/03/04 song song. Chưa có task nào được tuyên bố đã chạy trong đợt lập backlog này.

## 6. Phạm vi full backlog và refinement

Bộ tracker phủ roadmap sản phẩm hiện được mô tả: core teacher pilot, school teacher-management, independent learner, mock exams, OMR, billing và discovery cho mở rộng. “Full” không phải cam kết mọi tính năng tương lai đã có specification cuối cùng.

- M0–M1 có thể đưa vào sprint đầu sau refinement; milestone xa cần review lại acceptance theo feedback và provider/version thực tế.
- Không ép triển khai essay auto-grading, adaptive model, LMS/SIS integrations hoặc microservice extraction trước prerequisites.
- Không tự đổi các task thành ready/done vì scaffold hoặc tài liệu đã tồn tại.
- Estimate từng task sau discovery; không lấy tổng số hàng làm cam kết lịch delivery.
