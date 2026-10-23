# Setup Auth0 cho Eduvia

Triển khai code không tự tạo tenant hoặc gửi email. Tenant development đã được tạo và người dùng đã kiểm tra flow Auth0/email thật trên local ngày 2026-10-23. Email provider production, HTTPS staging và máy thứ hai chưa được nghiệm thu.

## 1. Tạo ứng dụng và API

1. Tạo tenant development trong Auth0. Tạo tenant staging riêng trước khi phát hành; không dùng user thử làm dữ liệu production.
2. Applications → Create Application → **Regular Web Application**. Dùng domain tenant mặc định; chưa cần custom domain.
3. Authentication → Database → tạo/bật `Username-Password-Authentication`, dùng Auth0 user store. Cho phép signup; chỉ enable connection này cho ứng dụng, tắt social/passwordless cho bản đầu. Bật password policy và attack protection/brute-force protection của Auth0.
4. APIs → Create API: tên `Eduvia API`, Identifier `https://eduvia-api`, signing algorithm **RS256**, token expiration **300 giây**, Allow Offline Access bật.
5. Trong Eduvia API → Application Access → Eduvia Local → Edit, cấp **User-Delegated Access** và lưu. Nếu dùng per-app authorization mà thiếu grant này, Auth0 trả `invalid_request`: client is not authorized to access resource server. Đây là quyền user flow, không thay bằng quyền Client Access/M2M.
6. Application settings: callback `http://127.0.0.1:3000/auth/callback`, logout URL `http://127.0.0.1:3000/login`, web origin `http://127.0.0.1:3000`. Dùng đúng một origin khi chạy local; nếu dùng localhost thì thêm URL tương ứng và đổi APP_BASE_URL.
7. Bật Authorization Code + Refresh Token grants, refresh token rotation; đặt absolute lifetime 24 giờ, idle 2 giờ. Không dùng implicit hoặc password grant.
8. Actions → Triggers → Post Login: tạo Action từ `post-login.js`, thêm secret `EDUVIA_API_AUDIENCE=https://eduvia-api`, deploy và gắn Action vào flow. Claim namespace cố định `https://eduvia.app/claims/` là định danh, không phải endpoint phải deploy.

## 2. Email và tài khoản chưa xác minh

1. Cấu hình email provider riêng trong Auth0 để gửi verification/reset mail thật, cấu hình sender/domain theo nhà cung cấp. Không dùng email test của Auth0 như cấu hình phát hành.
2. Bật verification email khi signup. Template redirect về `/login` trên origin ứng dụng. Password reset sử dụng link **Forgot password** trên Universal Login.
3. Backend bắt buộc `email_verified=true` từ access token đã ký trước bootstrap. Sau xác minh, user chọn **Tôi đã xác minh — đăng nhập lại** để nhận claim mới.
4. Tạo M2M application cho Auth0 Management API, chỉ cấp `update:users` cần cho `POST /api/v2/jobs/verification-email`. Client này chỉ dùng server-side; application không có endpoint sửa user tùy ý.
5. Điền hai biến `AUTH0_MANAGEMENT_CLIENT_*` để bật nút gửi lại. Khi chưa cấu hình, endpoint trả 503; không giả thành công. Rate limit theo identity, một lần/phút và năm lần/giờ, áp dụng cho cả request thất bại ở provider.

## 3. Cấu hình local

Sao chép các tên biến từ `frontend/.env.example` và `backend/.env.example` vào env local. Không commit `.env`, không gửi secret trong chat. Sinh hai khóa khác nhau, mỗi khóa 32 random bytes dạng hex, cho `AUTH0_SECRET` và `SESSION_ENCRYPTION_KEY` bằng `node -e "console.log(require('node:crypto').randomBytes(32).toString('hex'))"` trên máy mình.

Frontend:
- `APP_BASE_URL=http://127.0.0.1:3000`
- `API_INTERNAL_URL=http://127.0.0.1:8000`
- `AUTH0_DOMAIN=<tenant>.auth0.com`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_SECRET`
- `AUTH0_AUDIENCE=https://eduvia-api`, `AUTH0_CONNECTION=Username-Password-Authentication`
- `SESSION_REDIS_URL=redis://127.0.0.1:6379/2`, `SESSION_ENCRYPTION_KEY`
- `AUTH0_MANAGEMENT_CLIENT_ID`, `AUTH0_MANAGEMENT_CLIENT_SECRET`

Backend:
- `AUTH_ISSUER=https://<tenant>.auth0.com/` (giữ dấu `/` cuối)
- `AUTH_AUDIENCE=https://eduvia-api`
- `AUTH_JWKS_URL=https://<tenant>.auth0.com/.well-known/jwks.json`
- API `DATABASE_URL` dùng `eduvia_runtime`. Migrations chạy riêng với `eduvia_migrator`.

Khởi tạo Compose mới sẽ tạo runtime/migrator/NOLOGIN function owner. Volume cũ không chạy lại init script: DBA phải tạo role `eduvia_identity_owner` và grant role đó cho migrator, sau đó kiểm tra grants; không xóa volume để vượt lỗi migration. Khi chưa có Auth0, preview và health vẫn chạy; protected endpoints trả lỗi cấu hình, không fallback mock.

Chạy local: `docker compose up -d db redis`, chạy migration bằng migrator, `scripts/dev-backend.ps1`, rồi `npm run dev` trong frontend. Khi chạy toàn bộ Compose, biến auth phải đặt trong env cấp root dùng cho Compose; frontend/.env.local chỉ dành cho Next.js chạy native.

## 4. Migration và deploy

- Migration `0004_auth_identity` forward-only. Existing users bắt buộc file JSON mapping `{ "<user UUID>": "https://<issuer>/" }` do người có trách nhiệm xác nhận. Chạy `alembic -x identity_map=/absolute/path/map.json upgrade head`. Không suy đoán issuer từ email.
- Workspace personal cũ phải có đúng một owner; nhiều workspace cho cùng owner cần xử lý dữ liệu trước migration. Migration dừng và rollback khi dữ liệu mơ hồ.
- Administrator prerequisite cho database cũ: `CREATE ROLE eduvia_identity_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; GRANT eduvia_identity_owner TO eduvia_migrator;`. Chỉ chạy CREATE nếu role chưa tồn tại. Runtime không được là thành viên role này.
- Snapshot/backup trước migration; deploy migration rồi backend/frontend. Rollback application không downgrade schema phá dữ liệu. Nếu cần rollback schema, phục hồi backup đã kiểm chứng.
- Staging: dùng HTTPS origin trong callback/logout/APP_BASE_URL; cookie tự bật Secure. `compose.staging.yaml` có Redis session riêng trên network `session`, frontend không nối database network. Session Redis restart làm logout, không phục hồi phiên cũ từ bản sao.
- Token/profile trong Redis mã hóa AES-256-GCM với SESSION_ENCRYPTION_KEY. Đổi khóa yêu cầu logout mọi phiên. Không expose Redis hoặc token endpoint ra Internet.
- Không đặt AUTH_TEST_MODE ở staging/production. HTTP fixture chỉ được phép ngoài production, backend chỉ cho localhost khi APP_ENV=test.

## 5. Kiểm chứng và troubleshooting

- Đăng ký email thật → nhận thư → chưa verify không bootstrap → verify → login lại → mở workspace → reload → logout → Back/reload không thấy dữ liệu thật.
- Quên mật khẩu → nhận thư → reset → mật khẩu cũ thất bại, mật khẩu mới đăng nhập được. Kiểm tra hành vi thu hồi session ở tenant; access token đã phát có lifetime 5 phút cộng clock tolerance 30 giây, không hứa thu hồi JWT lập tức.
- Thử callback bị hủy, backend/Redis down, user bị khóa, revoke membership và hai user khác nhau.
- `auth_unavailable`/503: kiểm tra env, issuer/audience/JWKS và Redis. `email_unverified`: Action và claim đã cập nhật chưa, đăng nhập lại sau verify. `invalid_token`: kiểm tra API audience và RS256, không gửi ID token cho FastAPI.
- User bị khóa phải đặt `edu.users.is_active=false` để backend chặn request tiếp theo; chỉ khóa ở Auth0 không thu hồi ngay JWT đã phát. Không có UI quản trị khóa user trong slice này.
- Logs ghi request ID/code, không ghi bearer/cookie/password. Theo dõi callback failure, refresh failure, bootstrap failure và Redis availability.

Tài liệu tham khảo: https://github.com/auth0/nextjs-auth0 ; https://auth0.com/docs/authenticate/database-connections ; https://auth0.com/docs/manage-users/user-accounts/verify-emails ; https://auth0.com/docs/authenticate/database-connections/password-change .


### Volume local cũ chỉ có migration 0001

Nếu `edu` đã tồn tại nhưng chưa có object và `public.alembic_version` chỉ chứa `0001_bootstrap`, script bootstrap hiện hỗ trợ tiếp nhận baseline này: tạo role, chuyển owner schema rỗng và bảng Alembic cho migrator trong cùng transaction. Script từ chối schema có bảng/function/type hoặc revision khác; không tự chuyển quyền dữ liệu sản phẩm. Chạy `docker compose exec db sh /docker-entrypoint-initdb.d/10-bootstrap.sh` một lần, đợi `COMMIT` rồi mới chạy migration. Nếu đã có role từ lần chạy thành công, không dùng script này để đổi mật khẩu.

### Lỗi gặp khi smoke local

- `authorization_error` / `invalid_request`: kiểm tra API Application Access đã cấp User-Delegated Access cho đúng Regular Web Application.
- `invalid_state`: bắt đầu lại từ `/login` trong một cửa sổ mới, dùng đúng origin `127.0.0.1`, không tái dùng callback hoặc transaction cũ. Một lần thử bằng phiên mới đã thành công; chưa kết luận nguyên nhân gốc nếu tái diễn.
- Windows native: dùng `127.0.0.1` cho Redis URL; trong lần setup này `localhost` timeout dù container Redis khỏe.
- Sau login, `/onboarding` hiện nút **Mở workspace cá nhân**. Người dùng bấm nút để bootstrap hoặc lấy lại workspace rồi chuyển dashboard; hiện chưa tự bỏ qua màn hình cho tài khoản cũ.
