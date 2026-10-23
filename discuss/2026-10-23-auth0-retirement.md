# Auth0 retirement — Better Auth only

Owner implementation: Duc. Reviewer đề xuất: Hào; chưa review/signoff. User chốt bỏ account Auth0 thử nghiệm và dữ liệu Eduvia tương ứng, bắt đầu tài khoản mới; quyết định này supersede gate chuyển đổi trước đó.

## Source

Gỡ SDK/dependency, legacy session/verifier, Auth0 callback/Management API/Action, migration UI/BFF và `/v1/auth/migrate`. Better Auth chạy trực tiếp; không AUTH_PROVIDER, AUTH0_* hay LEGACY_AUTH_* trong runtime/config examples/Compose/CI. Legacy routes trả 404. HttpError dùng module độc lập; Origin/CSRF, server-only JWT, durable revocation và RLS vẫn giữ.

Giữ migrations 0001–0007; migration 0008 bỏ transfer function/table và dừng nếu có receipt cần review. Giữ user_identities cho provisioning/RLS. Cleanup operator yêu cầu issuer/subject/UUID chính xác, Auth0 tenant/database identity; dry-run mặc định, scope locks/transaction, chặn linked identity/shared membership/unreviewed dependencies, retry idempotent. Redis cleanup chỉ eduvia:session:* và eduvia:verify:*.

## Local database evidence

Inventory trước cleanup: schema 0004, đúng 1 user Auth0 và 1 personal workspace/owner membership. Đã pg_dump custom format, copy vào private ignored `tmp/auth0-retirement/before-cleanup.dump`, restore vào database tạm và kiểm 1 user/1 workspace; database restore tạm đã dọn. Backup không commit.

Đã tạo auth runtime role riêng, nâng đến 0007, dry-run kiểm đúng 1 user/1 workspace/1 membership/1 identity, apply trong transaction rồi nâng đến `0008_remove_auth0_transfer (head)`. Sau cleanup: 0 user và 0 workspace. Redis namespace cũ inventory 0 key; không flush Redis. Local env đã bỏ secrets/config Auth0, cấu hình issuer/database Better Auth cho frontend/backend native. Password auth DB/Better secret sinh riêng, không log hay commit.

## Automated evidence

- Backend: 54 PASS, gồm database migrations/bootstrap/RLS, removed transfer endpoint, cleanup dry-run/rollback/retry/mismatch/linked identity/shared membership và Auth0 issuer rejection.
- Backend Ruff check/format PASS. Scripts/verifier suite: 35 PASS. Historical workspace adapter suite: 4 PASS.
- Better Auth browser suite: 9 PASS, gồm email/reset, Google linking/unlinking, session revocation, blocked external redirects/Origin, unverified Google, old routes 404, Redis cleanup namespace isolation/dry-run/retry và visual checks. Provider/email là fixture ký thật/local SMTP, chưa phải cloud smoke.
- Frontend lint/typecheck/production build + standalone preparation PASS; dùng dist test để không đụng cache dev.
- Local/staging Compose config validator PASS, secrets test không in ra output. Local auth runtime kết nối được auth tables, không có USAGE schema edu. Local secret scan PASS.

## Còn phải nghiệm thu

Chưa có Google OAuth client/SMTP thật, chưa smoke HTTPS staging/máy thứ hai/GitHub CI. Không đánh dấu M1 hoàn tất. Browser inventory không có phiên Auth0 Dashboard được đăng nhập; chưa xóa user/application/API/Action hay thu hồi credentials phía tenant. Người quản trị làm checklist cloud teardown trong [runbook](../deploy/better-auth/README.md); không xóa tenant/connection dùng chung.

Hào review ưu tiên cleanup scope/locks, migration grants, single-issuer rejection và session security. [Setup từng bước](../deploy/better-auth/SETUP-LOCAL.md). Chưa commit/push trong lần triển khai này.
