# Better Auth: setup, chuyển tài khoản và cutover

Trạng thái: implementation chuyển đổi theo giai đoạn; không tự đổi `.env` đang chạy, không migrate DB local có dữ liệu và không xóa tài khoản Auth0. Checkpoint Auth0 trước chuyển đổi: `912c0d2`. Nghiệm thu cần thêm Google/email thật, HTTPS staging và máy thứ hai.

## 1. Cấu hình

1. Backup PostgreSQL trước migration; kiểm tra phục hồi được. Không xóa volume và không downgrade identity migrations.
2. Sinh `DB_AUTH_PASSWORD`, `BETTER_AUTH_SECRET` (ít nhất 32 random bytes) và `SESSION_ENCRYPTION_KEY` (32 bytes dạng 64 hex) riêng biệt. Nhập trực tiếp env, không gửi vào chat hoặc commit.
3. DBA chạy `deploy/postgres/auth-role.sql` qua psql có `DB_AUTH_PASSWORD` và `POSTGRES_DB` trong environment. Script không xoay password role đã tồn tại. Database volume mới chạy `20-auth-role.sh` sau bootstrap; volume cũ phải chạy riêng script role, không chạy lại bootstrap trên schema có dữ liệu.
4. Chạy Alembic upgrade head bằng migrator: `0005_multi_identity` backfill alias, schema auth; `0006_identity_transfer` thêm cổng chuyển/audit receipt, `0007_auth_revocation` lưu mốc thu hồi phiên bền vững. Giữ nguyên UUID và dữ liệu sản phẩm. Next.js dùng `eduvia_auth_runtime`, không dùng migrator/admin hoặc `eduvia_runtime`.
5. Frontend: `AUTH_PROVIDER=better-auth`, `APP_BASE_URL=http://127.0.0.1:3000`, `AUTH_DATABASE_URL=postgresql://eduvia_auth_runtime:<password>@127.0.0.1:5432/eduvia`, `SESSION_REDIS_URL`, `SESSION_ENCRYPTION_KEY`, `BETTER_AUTH_SECRET`, `BETTER_AUTH_AUDIENCE=https://eduvia-api`, `SMTP_URL`, `AUTH_EMAIL_FROM`.
6. Backend: `AUTH_ISSUER=http://127.0.0.1:3000` (không slash cuối), `AUTH_AUDIENCE=https://eduvia-api`, `AUTH_JWKS_URL=http://127.0.0.1:3000/api/auth/jwks`. HTTP chỉ được chấp nhận ở loopback ngoài production; staging dùng HTTPS. BFF và API phải truy cập được public JWKS origin.
7. Local SMTP có thể dùng mail catcher ở loopback 1025. Production phải cấu hình SMTP thật, domain/sender đã xác minh; SMTP URL không được log. Verification/reset email do Better Auth tạo token và xử lý.

## 2. Google OAuth

1. Tạo OAuth Web client trong Google Cloud; consent screen, email hỗ trợ và test users ở chế độ Testing. Không dùng credential của Auth0.
2. Authorized JavaScript origin: origin ứng dụng. Redirect URI: `<APP_BASE_URL>/api/auth/callback/google`; đăng ký riêng local/staging. Điền `GOOGLE_CLIENT_ID` và `GOOGLE_CLIENT_SECRET` phía server.
3. Thiếu Google config: nút Google không hiện ở login và link bị vô hiệu hóa; không fallback provider giả.
4. Email đã verified mới được dùng. Implicit linking bị tắt; cùng email không tự gộp. V1 yêu cầu Google cùng email với user Better Auth.
5. Email-first: Account Center → xác thực lại mật khẩu → Google OAuth → xác nhận liên kết. Callback chỉ lưu bằng chứng ngắn hạn; chưa attach trước xác nhận. Google-first: thiết lập mật khẩu qua email trước khi thay đổi phương thức; không gỡ cách đăng nhập cuối cùng.

## 3. Giữ workspace Auth0 cũ

1. Giữ các env Auth0 cũ, thêm `AUTH0_MIGRATION_ENABLED=1`. Backend đặt `LEGACY_AUTH_ISSUER`, `LEGACY_AUTH_AUDIENCE`, `LEGACY_AUTH_JWKS_URL` đúng tenant cũ; primary AUTH_* là Better Auth.
2. Đăng ký/xác minh Better Auth bằng cùng email; chưa bấm mở workspace mới. Trên onboarding chọn chuyển tài khoản cũ → `/account/migrate`.
3. Xác thực lại Auth0 cũ, quay về trang chuyển trong 5 phút. Bấm xác nhận chuyển; BFF xác minh cả hai session, không lấy source UUID từ browser và không sao chép mật khẩu.
4. Backend kiểm proof RS256 riêng issuer `<APP_BASE_URL>/migration`, audience `<audience>/migration`, sub đích, nguồn allowlist và lifetime 5 phút. Transaction gắn alias vào UUID cũ; receipt ràng buộc proof với đích, retry idempotent, conflict trả 409.
5. Chuyển thành công kết thúc cả hai phiên; login Better Auth rồi mở workspace, kiểm UUID user/workspace và role không đổi.
6. Nếu đã bootstrap user đích riêng thì chặn gộp; không xóa user/workspace để vượt lỗi. Hào/owner xử lý tình huống này theo quy trình dữ liệu riêng.

## 4. Cutover và bảo mật vận hành

- Kiểm báo cáo user legacy chưa có alias primary; khóa gate chỉ khi mọi user cần giữ đã chuyển hoặc có phương án khôi phục được xác minh. Không coi local fixture là smoke tenant thật.
- Tắt `AUTH0_MIGRATION_ENABLED`, bỏ LEGACY_AUTH_* rồi restart. Auth0 login/callback không còn public khi gate tắt. Không tự đóng tenant trước khi kiểm xong dữ liệu.
- SDK legacy hiện còn để phục vụ chuyển đổi. Xóa SDK/config/Action/legacy tests trong một diff cleanup sau cutover đã kiểm chứng; chưa tuyên bố repo hoàn toàn không còn Auth0.
- Redis session mã hóa, TTL idle 2 giờ và absolute cap 24 giờ; session cookie không chứa JWT API. Tombstone ngăn stale refresh phục hồi session logout; mốc thu hồi trong auth database chặn phiên cũ ngay cả khi Redis phục hồi record cũ sau thay đổi mật khẩu/phương thức. Cookie cache tắt. `/api/auth/token`, `/get-session`, link/unlink nội bộ bị chặn ở public handler.
- Next.js truy cập PostgreSQL bằng role auth riêng trên network `auth`; không có quyền schema edu. Public JWKS chỉ có public keys; private keys do Better Auth mã hóa trong auth database.
- Log chỉ event/code/request ID, không log password, token, cookie hoặc SMTP payload. Sao lưu auth DB gồm password hashes và encrypted signing keys với quyền hạn phù hợp.

## 5. Kiểm thử

`docker compose -f compose.auth-test.yaml up -d --wait`; backend dùng `AUTH_TEST_DATABASE_URL` trỏ database tên kết thúc `_test` khi chạy integration tests. Trong frontend chạy `npm run test:better-auth`. Fixture xóa schema auth/edu chỉ trong DB test, SMTP cục bộ và Google fixture có RS256/PKCE; không dùng Google account thật.

Không chạy test setup vào DB sản phẩm. Không chạy hai E2E suites đồng thời vì dùng chung test build directory. Chạy lint/typecheck/build tuần tự cho Next.js.

### Khác biệt verification so với checkpoint Auth0

Better Auth không tạo phiên đăng nhập cho email/password chưa verified. `/verify-email` ở chế độ Better Auth là trang hướng dẫn/gửi lại chung, không hiển thị dữ liệu tài khoản; dashboard, onboarding và Account Center vẫn có server guard. Resend public yêu cầu email, Origin/JSON và quota một phút/năm mỗi giờ, trả nội dung không tiết lộ tài khoản có tồn tại. Auth0 cũ vẫn dùng phiên unverified và resend server-side theo session trong giai đoạn tương thích.
