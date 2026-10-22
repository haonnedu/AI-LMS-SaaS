# FE-02a — Onboarding không gian cá nhân với mock

Owner: Duc. Reviewer đề xuất: Hao. Branch: `feat/fe-02-workspace-mock`.
Phần chuẩn bị frontend dựa trên FE-01 mock đã merge PR #5 (`2379a6e`).
FE-02 thật vẫn chờ BE-06/auth thật. Không dùng state mock để cấp quyền API.

## Chạy và thử

Node 24, dependencies hiện có; không thêm package. Chạy `npm run dev`, mở `/login`.

1. **Đăng nhập thử** → `/onboarding` có user mẫu, không sidebar.
2. **Mở không gian mẫu** → tra cứu workspace trong adapter; nếu thiếu thì chuẩn bị
   trong 700ms → dashboard. Lời chào lấy từ session; sidebar lấy tên workspace.
3. **Xem không gian mẫu** → onboarding hiển thị workspace đã có và **Vào không
   gian mẫu**; không chuẩn bị lại, không tự redirect.
4. **Đăng xuất thử**, expiry hoặc reload xóa user/workspace trong React memory.

Truy cập `/onboarding` không có session hiển thị liên kết đăng nhập và preview;
không redirect, không tạo workspace. **Tiếp tục xem bản mẫu** luôn mở dashboard;
session chưa có workspace sẽ thấy **Hoàn thành onboarding**. Học liệu/số liệu vẫn
là minh họa; không có backend workspace API mới.

Dev selector ở onboarding (chọn trước thao tác đầu tiên):

| Scenario | Kết quả |
|---|---|
| Thành công | Chuẩn bị một workspace mẫu, mở dashboard. |
| Đã có workspace | Tra cứu trả workspace sẵn; bỏ qua bước tạo. |
| Lỗi lần đầu | Lần chuẩn bị đầu báo lỗi; **Thử lại** thành công trên cùng adapter. |

Selector bị khóa sau khi bắt đầu, kể cả sau lỗi/cancel. Logout và login lại để
thử scenario khác. Production không có selector auth/workspace; chỉ chạy success.

## State và interface

`WorkspaceSummary` có `id`, `name`, `kind: personal`. `WorkspaceAdapter` có hai
Promise methods: `getPersonalWorkspace()` và `ensurePersonalWorkspace()`.
Đây là interface frontend nội bộ, chưa phải HTTP/DTO contract.

Mock dùng tên **Không gian cá nhân mẫu**. Các lần ensure đồng thời dùng cùng một
Promise; ensure sau thành công trả cùng record. Một adapter không lưu trữ qua
reload và không chia sẻ với adapter của session khác.

Auth context tăng `sessionVersion` đồng bộ khi tạo/xóa session. WorkspaceProvider
nằm dưới AuthProvider và remount theo version; kiểm tra version qua ref để callback
cũ bị từ chối ngay cả trước passive cleanup. Không chỉ dựa vào mock user ID cố định.
Operation ID bảo vệ từng bước await, lỗi và finally. Rời onboarding hủy logic
thao tác đang chờ nhưng giữ workspace đã chấp nhận. Adapter cũ có thể hoàn thành
Promise nội bộ; kết quả không được gắn vào UI hoặc điều hướng nếu đã bị hủy.

## Kiểm tra — 2026-10-22

- `npm run lint`: pass.
- `npm run typecheck`: pass.
- `npm run test:workspace`: 4/4 pass (Promise sharing/idempotency, existing record,
  first-error/retry, adapter isolation). Node có cảnh báo module-type detection;
  không thêm `type: module` cho toàn bộ project chỉ để tắt cảnh báo này.
- `npm run build`: pass ngoài filesystem sandbox, gồm standalone assets.
- MCP backlog parser: `python -m pytest tests/test_backlog.py -q` trong
  `tools/eduvia-mcp` pass 14/14 sau khi thêm ID `FE-02a`.
- Dev browser dùng server đã chạy ở port 3000; production standalone dùng port
  3102 riêng. Không dừng dev server của người dùng.

| Browser scenario | Kết quả quan sát |
|---|---|
| Chưa login mở onboarding | PASS: lời mời login, liên kết preview, không sidebar. |
| Login thành công | PASS: tới onboarding, đúng Minh Anh (mẫu), focus tiêu đề. |
| Chuẩn bị thành công/loading | PASS: action disabled khi loading; dashboard hiện workspace/user. |
| Mở lại onboarding | PASS: workspace card + Vào không gian mẫu, không tự redirect. |
| Existing fixture | PASS: tới dashboard với workspace; unit test xác nhận tái sử dụng record. |
| Lỗi lần đầu → retry | PASS: thông báo lỗi và Thử lại, sau đó dashboard có workspace. |
| Rời trang trong lúc chờ | PASS: dashboard giữ lời nhắc hoàn thành; kết quả cũ không gắn workspace. |
| Logout lúc chờ → login cùng ID | PASS: onboarding phiên mới chưa có workspace, không nhận kết quả cũ. |
| Expiry trong lúc chờ | PASS: bắt đầu preparation 4.4s sau login expiry-5s; về login với thông báo, đăng nhập lại không có workspace cũ. |
| Reload dashboard đã có workspace | PASS: user/workspace bị xóa, preview hiện Chào bạn và login link. |
| Keyboard/live regions | PASS: Tab từ tiêu đề tới action có focus outline; Shift+Tab tới brand; Enter chạy flow, loading polite/error alert. |
| Production | PASS: cả hai selector count=0, demo notice hiện; login → onboarding → dashboard → logout thành công. |
| Console cold reload | PASS: danh sách warning/error rỗng ở dev và production. |

## Responsive và giới hạn evidence

DOM được đo ở 1440×900 và 375×812, không tràn ngang. Card desktop rộng 600px;
mobile rộng 328px trong content 360px (scrollbar 15px), action cao 48px. Trang có
cuộn dọc khi nội dung cao hơn viewport; đây không phải clipping.

- [Geometry và kích thước ảnh](evidence/fe-02a/geometry.json)
- [Onboarding desktop](evidence/fe-02a/onboarding-desktop.jpg)
- [Onboarding mobile](evidence/fe-02a/onboarding-mobile.jpg)
- [Dashboard có workspace](evidence/fe-02a/dashboard-workspace.jpg)

**Visual signoff chưa đạt.** Raster capture tiếp tục hiển thị cột hẹp không khớp
card DOM 600px/328px. Các ảnh trên là evidence chẩn đoán, không xác nhận chữ/nút
hiển thị đúng. Cần ảnh đáng tin cậy và kiểm tra hình ảnh trước khi nghiệm thu.
Phần visual còn thiếu của FE-01 cũng tiếp tục được theo dõi riêng.

## Phối hợp với Hào

Trước tích hợp thật, chốt: thời điểm provisioning phía server, DTO current-user /
workspace, lỗi và retry/idempotency, session lifecycle, membership/authorization.
Không suy ra bảo đảm DB concurrency hoặc quyền từ mock này. Chưa implement
workspace selector, school provisioning hay API dữ liệu học liệu/lớp học.

FE-02a giữ `in_progress` vì còn visual/review; FE-02 giữ `todo`, FE-01 giữ
`in_progress`. [PR draft local](FE-02a-PR.md). Chưa commit/push/PR/deploy.

## Review trước commit/PR — 2026-10-22

Review local toàn bộ source/test mới và diff so với base
`2379a6e5e70b5c65645880202cae6bab5b11ac8b` trên
`feat/fe-02-workspace-mock`; đây chưa phải một source commit mới.
Môi trường xác nhận hiện tại: Windows PowerShell, Node v24.14.1, npm 11.11.0.

### Kết quả review

Không xác nhận thêm lỗi chức năng P0/P1/P2 trong phạm vi mock đã định nghĩa.
Không sửa source/test trong lượt review này. Không coi source review là bằng
chứng backend authorization, DB concurrency hoặc provider integration.

Các điểm đã đối chiếu:

- `openWorkspace` khóa pending đồng bộ trước await; kiểm tra mounted, operation ID
  và auth generation sau cả bước lookup lẫn ensure, cũng như catch/finally.
- Preview links hủy ngay khi navigation bắt đầu; cleanup onboarding hủy khi unmount.
  Result được chấp nhận chỉ sau guard; pending marker được xóa trước success navigation.
- Logout/expiry tăng auth generation; keyed provider không tái sử dụng workspace
  khi đăng nhập lại cùng mock user ID. Reload không restore state từ storage.
- Adapter trả chung pending Promise, reuse record, xóa pending sau rejection và
  cho retry thành công; scenario selector khóa sau lần bắt đầu đầu tiên.
- Onboarding chưa login không provisioning/redirect. AppShell bỏ sidebar ở login/
  onboarding; dashboard phân biệt user/workspace mẫu với nội dung preview.
- Scenario controls được build conditionally cho development; không đổi endpoint,
  quyền, migrations, dependency/lockfile hay generated types.

### Findings / phần còn mở theo ưu tiên

| Ưu tiên | Finding / giới hạn | Xử lý và điều kiện đóng |
|---|---|---|
| P2 — gate còn mở | Visual acceptance chưa có evidence đáng tin cậy. DOM geometry không chứng minh chữ/nút thực sự không bị cắt. | Giữ visual checklist bên dưới chưa đạt; Hào/Đức kiểm tra trực tiếp và lưu ảnh đáng tin cậy trước khi duyệt merge. |
| P2 — phối hợp CI | Job frontend trong `.github/workflows/ci.yml` chạy lint/typecheck/build nhưng chưa chạy `npm run test:workspace`. | Yêu cầu Hào phối hợp thêm lệnh test trong PR tooling riêng hoặc scope đã thống nhất. Trong lúc chưa có CI step, reviewer chạy thủ công và ghi kết quả. Không sửa workflow dùng chung trong đợt này. |
| Giới hạn coverage | 4 automated tests chỉ kiểm adapter; React lifecycle/race/navigation được kiểm browser ở baseline, chưa là automated E2E suite. | Không tuyên bố có automated E2E hoặc full race coverage; dùng matrix browser hiện có khi review. Không thêm framework ở đợt này. |

### Baseline validation được giữ lại

Các lệnh sau đã chạy ở đợt implement trong cùng phiên làm việc, đều exit 0.
Lượt review chỉ sửa tài liệu nên không chạy lại lint/typecheck/build hoặc browser
matrix để tránh báo một lượt chạy cũ thành evidence mới.

| Working directory | Command | Kết quả baseline |
|---|---|---|
| frontend | `npm run lint` | exit 0 |
| frontend | `npm run typecheck` | exit 0 |
| frontend | `npm run test:workspace` | exit 0, 4/4 pass |
| frontend | `npm run build` | exit 0, standalone preparation pass ngoài filesystem sandbox |
| tools/eduvia-mcp | `.\.venv\Scripts\python.exe -m pytest tests/test_backlog.py -q` | exit 0, 14/14 pass |

Review hiện tại kiểm lại `git diff --check`, file scope, docs/evidence links và
status trong tracker. Không có generated/cache/secret file trong danh sách commit.
Source commit mới và second-machine reproduction chưa có; cần bổ sung sau khi
Đức commit và Hào chạy lại. Lượt review này không thay thế approval của Hào.

### Checklist visual thủ công cho Hào/Đức

Thực hiện bằng browser render/capture đáng tin cậy, kiểm cả hai viewport; không
đánh dấu chỉ dựa trên các ảnh chẩn đoán hiện có.

| Trang | 375×812 | 1440×900 | Cần kiểm |
|---|---|---|---|
| `/login` | Chưa đạt | Chưa đạt | Chữ, demo notice, action và focus không bị cắt; scroll khi cần. |
| `/onboarding` | Chưa đạt | Chưa đạt | User, workspace card, loading/error, retry/logout và preview link đọc/bấm được. |
| `/` sau onboarding | Chưa đạt | Chưa đạt | Tên workspace/user rõ; logout truy cập được (mở menu trên mobile), menu đóng/mở/scroll đúng. |

Gate merge vẫn thiếu visual/reviewer signoff. FE-02a và FE-01 giữ `in_progress`,
FE-02 giữ `todo`. Có thể chuẩn bị commit/draft PR với các giới hạn này được ghi rõ;
chưa tuyên bố acceptance đầy đủ hoặc sẵn sàng merge.

### File dự kiến commit

Danh sách 22 file dưới đã bao gồm bàn giao bổ sung ở discuss/DUC.md và discuss/REVIEW.md
(2026-10-22 22:12 +07:00), gồm file tracked đã sửa và file mới chưa track; không có thao tác
stage/commit trong lượt bàn giao. Reviewer cần bảo đảm file mới không bị bỏ sót.

```text
discuss/DUC.md
discuss/REVIEW.md
frontend/FE-01.md
frontend/FE-02a-PR.md
frontend/FE-02a.md
frontend/evidence/fe-02a/dashboard-workspace.jpg
frontend/evidence/fe-02a/geometry.json
frontend/evidence/fe-02a/onboarding-desktop.jpg
frontend/evidence/fe-02a/onboarding-mobile.jpg
frontend/package.json
frontend/src/app/layout.tsx
frontend/src/app/onboarding/page.tsx
frontend/src/components/app-shell.tsx
frontend/src/components/auth/auth-provider.tsx
frontend/src/components/dashboard.tsx
frontend/src/components/workspace/onboarding-screen.tsx
frontend/src/components/workspace/workspace-provider.tsx
frontend/src/components/workspace/workspace.module.css
frontend/src/lib/workspace/mock-adapter.ts
frontend/src/lib/workspace/types.ts
frontend/tests/workspace-adapter.test.mjs
tasks/CORE.md
```

Commit message đề xuất: `feat(frontend): add mock personal workspace onboarding`.
Chưa commit, push, tạo PR, gửi thông báo hoặc deploy.

Bàn giao qua Git: [ghi chú phía Duc](../discuss/DUC.md) và [yêu cầu review đề xuất](../discuss/REVIEW.md). Chưa gửi thông báo trực tiếp hoặc ghi nhận Hao đã nhận review.
