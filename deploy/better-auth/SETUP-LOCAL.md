# Setup từng bước: Google và email

Không gửi client secret, API key, SMTP URL hoặc nội dung `.env` vào chat. Các bước dưới chỉ chuẩn bị môi trường; chưa tự tắt Auth0 hoặc di chuyển dữ liệu. Dừng và kiểm tra kết quả sau mỗi nhóm.

## A. Chuẩn bị môi trường local

1. Backup database hiện tại trước khi chạy migration. Giữ bản backup và kiểm cách phục hồi; không xóa volume Docker.
2. Trong root `.env`, thêm `DB_AUTH_PASSWORD` bằng chuỗi ngẫu nhiên riêng. Có thể sinh local với `node -e "console.log(require('node:crypto').randomBytes(32).toString('hex'))"`. Không tái dùng password runtime/migrator.
3. Từ root repo chạy `docker compose up -d db redis` để nhận env và mount mới, rồi `docker compose exec db sh /docker-entrypoint-initdb.d/20-auth-role.sh`. Mong đợi `COMMIT`. Không chạy lại `10-bootstrap.sh` trên database đã có dữ liệu.
4. Chạy `docker compose run --rm --build migrate`, rồi `docker compose run --rm migrate alembic current`. Mong đợi `0007_auth_revocation (head)`; lỗi thì dừng, không downgrade hay xóa dữ liệu.
5. Thêm vào `frontend/.env.local`: `AUTH_PROVIDER=better-auth`, `AUTH_DATABASE_URL=postgresql://eduvia_auth_runtime:<password bước 2>@127.0.0.1:5432/eduvia`, `BETTER_AUTH_SECRET` ngẫu nhiên mới, `BETTER_AUTH_AUDIENCE=https://eduvia-api`. Giữ `APP_BASE_URL=http://127.0.0.1:3000`, Redis và khóa mã hóa session hiện có.
6. Trong `backend/.env`, primary `AUTH_ISSUER=http://127.0.0.1:3000`, `AUTH_AUDIENCE=https://eduvia-api`, `AUTH_JWKS_URL=http://127.0.0.1:3000/api/auth/jwks`. Các biến Auth0 issuer/audience/JWKS cũ chuyển sang `LEGACY_AUTH_*` nếu cần chuyển tài khoản.
7. Muốn giữ workspace cũ: frontend giữ các biến Auth0 cũ và đặt `AUTH0_MIGRATION_ENABLED=1`; làm theo mục chuyển tài khoản ở README. Không bootstrap workspace mới trước khi chuyển.

Env root dùng cho Compose; `frontend/.env.local` cho Next native, `backend/.env` cho API native. Không nhầm ba file này. Restart backend/frontend sau khi cấu hình xong, giữ đúng origin `127.0.0.1`.

## B. Tạo Google OAuth client

1. Mở https://console.cloud.google.com/ và tạo project riêng, ví dụ **Eduvia Development**. Chọn đúng project ở thanh trên cùng.
2. Mở **Google Auth platform**. Nếu có **Get started**, điền tên ứng dụng Eduvia, email hỗ trợ và email liên hệ của mình.
3. Trong **Audience**, chọn External cho người dùng Google cá nhân; để Testing trong giai đoạn local. Thêm email Google của mình và người review vào Test users nếu được yêu cầu.
4. Trong **Clients → Create client**, chọn **Web application**, tên **Eduvia Local**.
5. Authorized JavaScript origins: `http://127.0.0.1:3000`.
6. Authorized redirect URIs: `http://127.0.0.1:3000/api/auth/callback/google`. URL phải trùng từng ký tự; không dùng callback Auth0 cũ.
7. Tạo client. Chép Client ID và Client secret trực tiếp vào `frontend/.env.local` dưới `GOOGLE_CLIENT_ID` và `GOOGLE_CLIENT_SECRET`.
8. Restart frontend; trang login phải có nút Google. Thử bằng test user, mong đợi đến onboarding. Chưa có email/password thì Google-first có thể mở workspace sau khi Google xác nhận email verified.

Tham khảo: https://developers.google.com/workspace/guides/create-credentials và https://developers.google.com/identity/protocols/oauth2/web-server . Chỉ xin `openid`, `email`, `profile`, không cần Drive/Gmail API.

## C. Email

Local có thể dùng một SMTP mail catcher trên `127.0.0.1:1025`: điền `SMTP_URL=smtp://127.0.0.1:1025`, `AUTH_EMAIL_FROM=Eduvia <auth@example.test>`. Thư nằm trong mail catcher, không gửi tới Gmail; dùng để phát triển, không nghiệm thu mailbox thật.

Ví dụ gửi thư thật bằng Resend:

1. Tạo tài khoản tại https://resend.com/ . Kiểm tra quota gói đang chọn, không cần nâng cấp chỉ để bắt đầu thử.
2. Thêm domain mình sở hữu, cấu hình DNS theo dashboard và đợi trạng thái verified. Chưa có domain thì chưa coi cấu hình gửi tới người dùng bất kỳ là hoàn tất; có thể tiếp tục local mail catcher.
3. Tạo API key có quyền gửi email cho domain đã xác minh. Lưu trực tiếp ở máy/môi trường chạy.
4. `SMTP_URL=smtps://resend:<API-key-đã-URL-encode>@smtp.resend.com:465`; `AUTH_EMAIL_FROM=Eduvia <auth@domain-đã-verified>`.
5. Restart frontend; đăng ký email thử và kiểm Inbox/Spam. Chưa xác minh phải bị chặn bootstrap; xác minh rồi đăng nhập được. Reset password phải gửi thư, mật khẩu mới dùng được và mật khẩu cũ bị từ chối.

Thông số SMTP chính thức: https://resend.com/features/smtp-service . Không đưa API key vào frontend public env hoặc chụp màn hình chứa secret.

## D. Liên kết và chuyển đổi

1. Email-first: mở workspace → Trung tâm tài khoản → xác thực lại mật khẩu → Liên kết Google → chọn Google cùng email → xác nhận. Phải đăng nhập lại, vẫn cùng UUID/workspace.
2. Google-first: vào Trung tâm tài khoản, gửi email thiết lập mật khẩu, đặt mật khẩu qua link rồi đăng nhập lại. Sau đó mới thay đổi phương thức; không hủy Google nếu đây là cách đăng nhập cuối cùng.
3. User Auth0 cũ: tạo Better Auth cùng email đã verified, ở onboarding chọn chuyển tài khoản cũ, xác thực lại Auth0 và xác nhận trong 5 phút. Sau logout/login mới kiểm workspace cũ trước khi tắt gate.
4. Dùng HTTPS staging với OAuth callback và SMTP thật, người thứ hai chạy lại tài liệu. Đọc phần cutover trong README trước khi bỏ Auth0 SDK/tenant; chưa làm bước này khi còn user cần chuyển.
