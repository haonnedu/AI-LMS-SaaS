# Duc Quach — cập nhật và bàn giao

Task được phân công và trạng thái chính thức: [Core](../tasks/CORE.md). Các nhánh khác xem [backlog](../tasks/BACKLOG.md).

## 2026-10-22 22:12 +07:00 — FE-02a — bàn giao onboarding/workspace mock

- Người chuẩn bị: Codex theo yêu cầu người dùng, ghi bàn giao phía Duc; chưa có phản hồi/chấp thuận của Hao.
- Task: [FE-02a và execution record trong Core](../tasks/CORE.md). Owner/status chính thức chỉ theo tracker.
- Revision: branch `feat/fe-02-workspace-mock`, base `2379a6e5e70b5c65645880202cae6bab5b11ac8b` cộng working-tree diff và file mới chưa commit. Chưa có SHA mới, push hoặc PR; cần cập nhật revision sau khi commit trước khi reviewer chốt.
- Đã thay đổi: mock login → `/onboarding` → dashboard có workspace cá nhân mẫu; tra cứu/reuse record, retry lỗi lần đầu, hủy kết quả muộn và reset workspace theo auth session generation. Giữ preview truy cập được; không thêm backend/API/provider thật, migration hoặc dependency.
- Kiểm chứng baseline: Windows PowerShell, Node v24.14.1, npm 11.11.0; frontend lint/typecheck/build + standalone exit 0, `npm run test:workspace` 4/4 pass; backlog parser 14/14 pass. Browser dev/production đã kiểm success/existing/retry/cancel/logout/expiry/reload/keyboard; production không có scenario selectors. Lượt review sau đó chỉ sửa docs, không chạy lại và không coi baseline là lượt kiểm mới.
- [Bàn giao, findings, checklist visual và file manifest](../frontend/FE-02a.md); [PR draft theo template](../frontend/FE-02a-PR.md); [geometry/capture chẩn đoán](../frontend/evidence/fe-02a/geometry.json).
- Còn thiếu: visual signoff do raster capture không khớp DOM; chưa có reviewer approval. Không dùng ảnh hiện tại để kết luận giao diện đạt hoặc đủ điều kiện merge. React lifecycle/race mới được kiểm browser thủ công, chưa có automated E2E suite.
- Đề nghị Hao (chưa xác nhận nhận việc): review đúng revision đã commit, tập trung session/operation guards và lookup/ensure/retry; phối hợp thêm `npm run test:workspace` vào frontend CI ở phạm vi tooling đã thống nhất. Workflow chưa được sửa; trước khi có CI step, đề nghị reviewer chạy lệnh này thủ công.
- Hành động tiếp: Duc chuẩn bị commit theo manifest; hai người kiểm trực tiếp login/onboarding/dashboard ở 375×812 và 1440×900 bằng browser/capture đáng tin cậy. Yêu cầu review chi tiết tại [REVIEW.md](REVIEW.md#2026-10-22--fe-02a--onboardingworkspace-mock).
- Chưa commit, push, tạo PR, gửi thông báo hoặc deploy trong phiên này; ghi chú chỉ được chia sẻ qua Git sau commit/push/pull.

## Mẫu cho mỗi phiên

```markdown
## YYYY-MM-DD HH:mm +07:00 — <TASK-ID> — <chủ đề>

- Tác giả: Duc Quach
- Task / trao đổi chi tiết: <link tracker hoặc file discuss>
- Branch / commit / PR: <revision chính xác>
- Đã thay đổi: <behavior và phạm vi file>
- Kiểm chứng: <command, exit code, môi trường, evidence>
- Chưa kiểm chứng / việc còn lại: <nêu rõ>
- Đề nghị Hao: <review/trả lời một việc cụ thể, hoặc không có>
- Đề xuất phiên tiếp theo: <không tự nhận task chưa cập nhật tracker>
```
