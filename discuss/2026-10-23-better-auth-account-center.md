# Better Auth + Account Center — bàn giao Hào

Người dùng đổi quyết định sau khi cân nhắc chi phí: thay Auth0 bằng Better Auth, email/password + Google, liên kết có xác nhận, giữ UUID/workspace cũ. Cho phép giai đoạn xác minh Auth0 cũ, không gộp hai user đã có workspace riêng; Google phải cùng email. Owner implementation Duc, reviewer đề xuất Hào; chưa có reviewer signoff.

Checkpoint trước chuyển đổi có sẵn trong repo: `912c0d2`. Source mới là working diff, chưa commit/deploy. Không sửa secret local, không apply migration vào DB người dùng và không tự đóng tenant Auth0.

## Thay đổi

- Better Auth 1.7.12, PostgreSQL adapter/role riêng, SMTP email, Redis session encryption + tombstone, RS256 JWT server-side cho BFF/FastAPI.
- Migration 0005 backfill nhiều danh tính, giữ user/workspace IDs và chuyển RLS; 0006 restricted transfer với proof audience riêng và receipt idempotent; 0007 lưu mốc thu hồi phiên bền vững trong auth schema.
- Login/signup/verify/reset form Eduvia, Account Center, password reauth, Google link OAuth → pending proof → xác nhận, unlink và revoke session.
- Cổng chuyển tài khoản đòi hai session verified cùng email và Auth0 login mới trong 5 phút; không email auto-merge.
- Env/Compose và [runbook](../deploy/better-auth/README.md) bổ sung. SDK Auth0 tạm giữ phục vụ gate chuyển đổi, chưa xóa trước khi user cũ chuyển xong.

## Evidence hiện tại

- Backend suite: 55 PASS, gồm 7 PostgreSQL integration scenarios và 5 multi-verifier checks. Có legacy backfill, concurrent bootstrap, RLS/pool/revocation, transfer giữ UUID/workspace, retry, spoof/conflict và negative grants.
- Better Auth email E2E thực: PASS signup/verify/login/workspace/reload/reset/logout, chặn token endpoint và CSRF. SMTP là local fixture, không phải provider production.
- Runtime dependency audit sau cài: 0 runtime advisories. Audit toàn bộ có advisory dev dependencies, chưa tự nâng các dependency ngoài scope.
- Better Auth suite cuối: 8 PASS (email; Google/link/unlink; Auth0 migration; external redirect/Origin/unverified Google; Google-first đặt password + expiry; encryption/tombstone; atomic proof/counter; visual desktop/mobile). Bài Google chạy bổ sung đã pass ca khác email bị từ chối và retry đúng email.
- Legacy Auth0 transition suite: 14 PASS. Historical workspace adapter: 4 PASS. Scripts/verifier unit suite: 35 PASS.
- Frontend lint/typecheck/production build + standalone asset preparation PASS; dùng dist test để không đụng build dev của người dùng. Backend Ruff check/format PASS. Warning build từ Auth0 DPoP utility vẫn còn vì SDK giữ phục vụ migration.
- Fresh PostgreSQL container upgrade bằng `eduvia_migrator` (không superuser): head `0007_auth_revocation`, kiểm quyền auth runtime không đọc edu.users, API runtime không ghi aliases, function owner không CREATE schema, auth runtime có quyền update revocation marker. Container/network riêng đã dọn.
- Staging Compose generator/validator PASS với secrets test bị ẩn; chưa deploy staging. Ảnh login desktop/mobile đã xem, mobile không overflow ngang; chưa có human visual signoff.
- Chưa nghiệm thu Google/email thật, HTTPS staging, máy thứ hai, GitHub CI hoặc cutover. Người dùng xác nhận chưa có Google OAuth client/SMTP; đã chuẩn bị [setup từng bước](../deploy/better-auth/SETUP-LOCAL.md).

## Hào cần review

Ưu tiên RLS alias/transfer grants, proof issuer/audience binding, pending link callback không đổi session, tombstone/logout races, session/schema permissions và cutover runbook. Không đánh dấu done theo số lượng code hoặc fixture pass. Các phần admin/invitation/Apple/Facebook/đổi email/gộp dữ liệu ngoài scope.

## Durable revocation và failure mode

Mốc `auth.session_revocations` được ghi trước khi xác nhận link, unlink, reset password có token hợp lệ và trước transfer. Request sau đó kiểm mốc DB trước khi trả session; Redis epoch/tombstone là lớp bổ sung. Nếu mutation thất bại sau mốc, user có thể phải login lại; không giữ phiên cũ để che lỗi. Google E2E cố tình phục hồi encrypted Redis record cũ, xóa Redis epoch và xác nhận session vẫn bị từ chối bởi DB. API/token/JWKS separation được kiểm qua bootstrap thật: public JWKS giữ nguyên public keys, auth JSON không trả session/token.

Raw logs/trace trong tmp và frontend/test-results là ignored diagnostics, không phải artifacts có sẵn trên máy Hào. Không commit secret, SMTP payload hay session thật. Chưa commit/push trong lần triển khai này.
