# Setup từng bước: Google và email

Không gửi client secret, API key, SMTP URL hoặc nội dung `.env` vào chat. Hướng dẫn này dành cho Better Auth; không chuyển tài khoản Auth0. Cloud Auth0 teardown là checklist riêng trong README. Dừng và kiểm tra kết quả sau mỗi nhóm.

## A. Chuẩn bị môi trường local

1. Backup database hiện tại trước khi chạy migration. Giữ bản backup và kiểm cách phục hồi; không xóa volume Docker.
2. Trong root `.env`, thêm `DB_AUTH_PASSWORD` bằng chuỗi ngẫu nhiên riêng. Có thể sinh local với `node -e "console.log(require('node:crypto').randomBytes(32).toString('hex'))"`. Không tái dùng password runtime/migrator.
3. Từ root repo chạy `docker compose up -d db redis` để nhận env và mount mới, rồi `docker compose exec db sh /docker-entrypoint-initdb.d/20-auth-role.sh`. Mong đợi `COMMIT`. Không chạy lại `10-bootstrap.sh` trên database đã có dữ liệu.
4. Chạy `docker compose run --rm --build migrate`, rồi `docker compose run --rm migrate alembic current`. Mong đợi `0008_remove_auth0_transfer (head)`; lỗi thì dừng, không downgrade hay xóa dữ liệu.
5. Thêm vào `frontend/.env.local`: `AUTH_DATABASE_URL=postgresql://eduvia_auth_runtime:<password bước 2>@127.0.0.1:5432/eduvia`, `BETTER_AUTH_SECRET` ngẫu nhiên mới, `BETTER_AUTH_AUDIENCE=https://eduvia-api`. Giữ `APP_BASE_URL=http://127.0.0.1:3000`, Redis và khóa mã hóa session hiện có.
6. Trong `backend/.env`, primary `AUTH_ISSUER=http://127.0.0.1:3000`, `AUTH_AUDIENCE=https://eduvia-api`, `AUTH_JWKS_URL=http://127.0.0.1:3000/api/auth/jwks`. Không giữ cấu hình Auth0/legacy.

Env root dùng cho Compose; `frontend/.env.local` cho Next native, `backend/.env` cho API native. Không nhầm ba file này. Restart backend/frontend sau khi cấu hình xong, giữ đúng origin `127.0.0.1`.

## B. Chạy email local bằng Mailpit

Sau khi role/migrations/env ở mục A đã xong, làm từng bước dưới. Không chạy lại cleanup hoặc reset database.

1. Tại root repo chạy `docker compose --profile dev-mail up -d --wait db redis mailpit`. Mong đợi cả ba healthy. Mailpit chỉ mở loopback 1025/8025, không gửi email ra Internet; profile này không được thêm vào staging.
2. Trong `frontend/.env.local` đặt `SMTP_URL=smtp://127.0.0.1:1025` và `AUTH_EMAIL_FROM=Eduvia <auth@example.test>`. Env trên máy hiện tại đã được cấu hình; máy khác tự điền hai dòng này.
3. Mở terminal backend: `cd D:\Data\Git_Space\AI-LMS-SaaS\backend`, rồi `.\.venv\Scripts\python.exe scripts/run_api.py`. Giữ terminal chạy. Mong đợi Uvicorn tại 127.0.0.1:8000. Nếu cổng đã có app Eduvia thì dùng terminal cũ/restart đúng process, không chạy thêm server.
4. Mở terminal thứ hai: `cd D:\Data\Git_Space\AI-LMS-SaaS\frontend`, rồi `npm.cmd run dev`. Mong đợi Next tại 127.0.0.1:3000. Đổi env thì restart frontend.
5. Mở `http://127.0.0.1:8000/health/ready`: phải có status ready, postgres ok và redis ok. Mở `http://127.0.0.1:8025`: phải thấy hộp thư Eduvia local.
6. Mở `http://127.0.0.1:3000/login`, chọn tạo tài khoản. Có thể dùng email Google sẽ liên kết sau này; mật khẩu tự đặt chỉ trên form. Thư xác minh ở Mailpit, không nằm trong Gmail. Trước khi bấm link phải bị chặn login/bootstrap.
7. Trong Mailpit chọn thư đúng email vừa đăng ký, mở link xác minh trong cùng browser; quay lại login bằng email/password. Bấm mở workspace cá nhân. Mong đợi dashboard và role owner; F5 vẫn giữ phiên/workspace.
8. Mở Account Center → đặt lại mật khẩu qua email; vào Mailpit lấy thư reset mới nhất. Đặt mật khẩu mới rồi login lại: mật khẩu cũ bị từ chối, workspace vẫn cũ.
9. Đăng xuất → Back → F5 → mở thẳng dashboard. Phải quay lại login và không đọc được dữ liệu tài khoản.

Dừng riêng hộp thư bằng `docker compose --profile dev-mail stop mailpit`; thư là dữ liệu test tạm và có thể mất khi container được recreate. Không bật SMTP relay/forward, không expose cổng ra LAN/Internet.

### Chạy lại smoke tự động trên app local

Tại frontend: `npm.cmd run test:auth:local`. Cần PostgreSQL/Redis/Mailpit/backend/frontend đang chạy ở các cổng phía trên; lần đầu cài browser bằng `npx.cmd playwright install chromium`.

Suite này KHÔNG reset schema hoặc flush Redis. Mỗi lần tạo một tài khoản synthetic `local-smoke-...@example.test` và workspace mới trong DB local, mật khẩu random không log, email chỉ vào Mailpit. Không dùng để nghiệm thu Google hoặc email gửi Internet. Trace tắt; attachment evidence được lọc không chứa password/token/cookie. Không chạy song song nhiều lần để tránh quota; không thay thế bộ test disposable `test:better-auth` trong CI.

## C. Tạo Google OAuth client

1. Mở https://console.cloud.google.com/ và tạo project riêng, ví dụ **Eduvia Development**. Chọn đúng project ở thanh trên cùng.
2. Mở **Google Auth platform**. Nếu có **Get started**, điền tên ứng dụng Eduvia, email hỗ trợ và email liên hệ của mình.
3. Trong **Audience**, chọn External cho người dùng Google cá nhân; để Testing trong giai đoạn local. Thêm email Google của mình và người review vào Test users nếu được yêu cầu.
4. Trong **Clients → Create client**, chọn **Web application**, tên **Eduvia Local**.
5. Authorized JavaScript origins: `http://127.0.0.1:3000`.
6. Authorized redirect URIs: `http://127.0.0.1:3000/api/auth/callback/google`. URL phải trùng từng ký tự; không dùng callback Auth0 cũ.
7. Tạo client. Chép Client ID và Client secret trực tiếp vào `frontend/.env.local` dưới `GOOGLE_CLIENT_ID` và `GOOGLE_CLIENT_SECRET`.
8. Restart frontend; trang login phải có nút Google. Thử bằng test user, mong đợi đến onboarding. Chưa có email/password thì Google-first có thể mở workspace sau khi Google xác nhận email verified.

Tham khảo: https://developers.google.com/workspace/guides/create-credentials và https://developers.google.com/identity/protocols/oauth2/web-server . Chỉ xin `openid`, `email`, `profile`, không cần Drive/Gmail API.

## D. Email thật — để đợt sau

Đợt hiện tại dùng Mailpit theo mục B. Các bước dưới dành cho nghiệm thu email Internet sau này.

Ví dụ gửi thư thật bằng Resend:

1. Tạo tài khoản tại https://resend.com/ . Kiểm tra quota gói đang chọn, không cần nâng cấp chỉ để bắt đầu thử.
2. Thêm domain mình sở hữu, cấu hình DNS theo dashboard và đợi trạng thái verified. Chưa có domain thì chưa coi cấu hình gửi tới người dùng bất kỳ là hoàn tất; có thể tiếp tục local mail catcher.
3. Tạo API key có quyền gửi email cho domain đã xác minh. Lưu trực tiếp ở máy/môi trường chạy.
4. `SMTP_URL=smtps://resend:<API-key-đã-URL-encode>@smtp.resend.com:465`; `AUTH_EMAIL_FROM=Eduvia <auth@domain-đã-verified>`.
5. Restart frontend; đăng ký email thử và kiểm Inbox/Spam. Chưa xác minh phải bị chặn bootstrap; xác minh rồi đăng nhập được. Reset password phải gửi thư, mật khẩu mới dùng được và mật khẩu cũ bị từ chối.

Thông số SMTP chính thức: https://resend.com/features/smtp-service . Không đưa API key vào frontend public env hoặc chụp màn hình chứa secret.

## E. Kiểm thử tài khoản mới

1. Đăng ký email/password → nhận thư → xác minh → login → mở workspace mới → reload giữ phiên.
2. Email-first: Account Center → xác thực mật khẩu → Google cùng email → xác nhận → login lại. Cả hai cách phải mở cùng UUID/workspace.
3. Google-first: thiết lập password qua email trước khi hủy Google; không hủy phương thức cuối cùng.
4. Reset password: password cũ bị từ chối, password mới dùng được; logout rồi Back/reload không truy cập dữ liệu.
5. HTTPS staging và người thứ hai chạy lại các bước trên; ghi evidence riêng với fixture tests. Không còn bước chuyển tài khoản Auth0.

Database local đã dọn account/workspace thử nghiệm cũ trong lần retirement; xem discuss. Setup máy khác vẫn cần role/migration và env riêng. Hướng dẫn xóa resource Auth0 Dashboard nằm trong README; không mặc định coi thao tác cloud đã hoàn tất.

## F. Manual Google / Account Center

Chỉ làm sau khi tạo client mục C và restart frontend. [Hướng dẫn Google từng bước](GOOGLE-LOCAL.md) có checkpoint và cách nhập secret trực tiếp. Không dùng kết quả Google fixture để đánh dấu manual Google thật pass.

Nguồn cấu hình Mailpit: https://mailpit.axllent.org/docs/install/docker/ và https://mailpit.axllent.org/docs/api-v1/ . Image pin theo version + digest; UI/SMTP chỉ bind loopback, không relay.
