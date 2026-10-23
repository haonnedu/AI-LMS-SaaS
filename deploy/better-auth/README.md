# Better Auth — hệ thống xác thực duy nhất

Eduvia dùng email/mật khẩu và Google qua Better Auth. Next.js giữ session trong Redis và gọi FastAPI bằng RS256 JWT 5 phút phía server; browser không nhận JWT. Không còn SDK, verifier hoặc cổng chuyển tài khoản Auth0. Tài khoản mới bắt đầu với UUID/workspace mới.

## Setup

Làm theo [hướng dẫn từng bước](SETUP-LOCAL.md). Backup PostgreSQL trước migration; chạy bằng migrator đến `0008_remove_auth0_transfer`. Next.js dùng `eduvia_auth_runtime`, API dùng `eduvia_runtime`; không dùng DBA trong application.

Frontend cần APP_BASE_URL, AUTH_DATABASE_URL, BETTER_AUTH_SECRET, BETTER_AUTH_AUDIENCE, SESSION_REDIS_URL, SESSION_ENCRYPTION_KEY, SMTP_URL và AUTH_EMAIL_FROM. Google tùy chọn cần cả GOOGLE_CLIENT_ID và GOOGLE_CLIENT_SECRET. Backend dùng AUTH_ISSUER=APP_BASE_URL, AUTH_AUDIENCE cùng audience BFF, AUTH_JWKS_URL=APP_BASE_URL/api/auth/jwks. Issuer không có slash cuối; HTTP chỉ loopback ngoài production. Các dịch vụ phải truy cập được JWKS origin; local guide dùng frontend/backend native, staging dùng public HTTPS.

## Dọn account Auth0 thử nghiệm

Không reset database/volume. Backup và restore vào database tạm trước; dừng application cũ trước cleanup. Migrations 0001–0007 giữ nguyên lịch sử; nếu DB ở 0004, nâng đến 0007 trước cleanup, sau đó lên head.

`backend/scripts/cleanup_legacy_account.py` yêu cầu `CLEANUP_DATABASE_URL` qua environment bằng DBA role. Chạy từ backend: `python -m scripts.cleanup_legacy_account --issuer <https-tenant.auth0.com/> --subject <auth0-subject> --user-id <UUID>` mặc định dry-run. Xem inventory rồi chạy cùng tham số thêm `--apply`. Không dùng email để xác định ownership. Script chỉ hỗ trợ issuer tenant auth0.com và subject database auth0|; chặn identity phụ, receipt chuyển đổi, workspace dùng chung và bảng phụ thuộc chưa review. Table locks và transaction bảo vệ scope; lỗi rollback, retry sau xóa trả already_absent.

`frontend/scripts/cleanup-legacy-sessions.mjs` dùng SESSION_REDIS_URL; mặc định dry-run, thêm `--apply` chỉ xóa namespace `eduvia:session:*` và `eduvia:verify:*`. Không xóa khóa Better Auth hoặc distributed lock dùng chung. Browser cookie Auth0 cũ không còn được đọc; có thể xóa cookie `eduvia_session` qua browser settings.

Migration 0008 dừng nếu còn transfer receipts cần review; không tự xóa receipt của tài khoản đã chuyển. Không downgrade phá dữ liệu.

## Xóa trên Auth0 Dashboard

Thao tác này độc lập với cleanup PostgreSQL và cần quyền quản trị tenant. Xóa đúng test user trong User Management → Users; xóa application Eduvia Local, test M2M application/API Eduvia và Action dành riêng Eduvia sau khi kiểm không còn consumer. Thu hồi credentials và kiểm không còn resource Eduvia. Không xóa tenant hoặc connection dùng chung với dự án khác. Code cleanup không tự tuyên bố tài nguyên cloud đã bị xóa.

## Session và Account Center

Session Redis mã hóa, idle 2 giờ/absolute 24 giờ, cookie HttpOnly/SameSite=Lax/Secure HTTPS; cookie cache tắt. Durable revocation chặn session cũ sau thay đổi phương thức/mật khẩu. Redis outage trả 503. BFF mutations kiểm Origin và CSRF; auth forms public kiểm Origin/JSON, callback allowlist và SDK state/PKCE.

Email/password bắt buộc verified trước đăng nhập/bootstrap; `/verify-email` là hướng dẫn/resend chung, không lộ tài khoản. Google yêu cầu email verified, không implicit linking. Link Google cùng email cần reauth password, OAuth, xác nhận; unlink cần password sẵn có và không được gỡ phương thức cuối. Google-first đặt password qua email. Sau thay đổi phương thức yêu cầu login lại; UUID/workspace không đổi.

## Verification

`docker compose -f compose.auth-test.yaml up -d --wait`; backend integration dùng AUTH_TEST_DATABASE_URL có tên DB kết thúc `_test`. Frontend `npm run test:better-auth` (alias `test:auth`) chạy PostgreSQL/Redis/SMTP/Google ký RS256 thật trong fixture, không phải Google/email production. Không chạy song song backend integration và browser suite vì reset chung disposable DB. Chạy frontend typecheck/build tuần tự.

Gate nghiệm thu còn cần Google/email thật, HTTPS staging, review Hào và người thứ hai chạy lại setup. Không log password/token/cookie/SMTP URL. Backup auth schema chứa password hash và signing keys mã hóa: giữ ở thư mục private ignored.

## Hộp thư dev local

`docker compose --profile dev-mail up -d --wait db redis mailpit`; UI http://127.0.0.1:8025 và SMTP loopback 1025. Profile opt-in, image pin version/digest, không relay và không có trong staging. Native frontend dùng smtp://127.0.0.1:1025. [Setup từng bước](SETUP-LOCAL.md) và [Google local](GOOGLE-LOCAL.md). Test `npm run test:auth:local` cần dịch vụ native có sẵn; tạo synthetic account/workspace, không reset dữ liệu.
