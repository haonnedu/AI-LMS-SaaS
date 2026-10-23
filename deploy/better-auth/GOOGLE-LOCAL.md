# Google local — mỗi lần một bước

Giữ nguyên origin `http://127.0.0.1:3000`; không xen localhost. Chỉ nhập secret trong `.env.local`, không gửi chat hoặc chụp màn hình có secret. Flow email local và Mailpit phải chạy trước.

## Tạo client

1. Mở https://console.cloud.google.com/ . Chọn hoặc tạo project riêng **Eduvia Development**. Checkpoint: tên project xuất hiện trên thanh trên.
2. Mở **Google Auth platform**; nếu có Get started, điền app name Eduvia, support email và contact email của ông. Người dùng tự hoàn tất các điều khoản nếu có. Checkpoint: vào được trang cấu hình ứng dụng.
3. **Audience**: dùng External và Testing nếu console yêu cầu; thêm tài khoản Google của mình và reviewer vào Test users khi cần. Không bật public production để bỏ qua cấu hình test.
4. **Clients → Create client → Web application**, tên **Eduvia Local**.
5. Authorized JavaScript origins: `http://127.0.0.1:3000`. Authorized redirect URIs: `http://127.0.0.1:3000/api/auth/callback/google`. Checkpoint: cả hai URL đúng origin và callback đúng đường dẫn.
6. Tạo client. Copy Client ID vào GOOGLE_CLIENT_ID, Client secret vào GOOGLE_CLIENT_SECRET trong `frontend/.env.local`. Secret có thể chỉ hiện lúc tạo: lưu an toàn ngay trên máy, không commit file tải về. Không đưa vào biến NEXT_PUBLIC_*.
7. Restart frontend. Checkpoint: trang login có nút **Đăng nhập bằng Google**. Chỉ xin openid/email/profile; không cần bật Gmail hoặc Drive API.

## Email-first: kiểm tài khoản đã có mật khẩu

1. Dùng email trùng Google để đăng ký Eduvia email/password; xác minh bằng Mailpit và mở workspace. Ghi UUID ở `/api/backend/me` và workspace ID trong `/api/backend/workspaces` vào ghi chú local, không cần gửi session JSON/token.
2. Vào `/account`, xác thực lại password, bấm link Google, chọn đúng Google account cùng email. Sau callback phải còn bước xác nhận; chưa xác nhận thì chưa được tính là đã link.
3. Xác nhận link: phiên kết thúc. Login bằng Google, mở workspace: UUID/workspace phải giữ nguyên.
4. Logout, login bằng email/password: vẫn cùng UUID/workspace.
5. Thử chọn Google khác email hoặc hủy consent: không được link sai account, workspace không thay đổi. Xác thực lại trước khi retry nếu intent đã bị dùng/hết hạn.
6. Unlink Google sau reauth: phải có email/password sử dụng được, logout rồi email/password vẫn vào workspace cũ. Có thể link lại theo flow trên.

## Google-first: kiểm tài khoản mới

Dùng tài khoản Google thứ hai CHƯA đăng ký Eduvia. Không tự xóa/gộp account email-first để ép test. Nếu chưa có account thứ hai, ghi ca này chưa manual verify.

1. Login Google → onboarding → workspace. Trong Account Center chưa có password, không được gỡ Google là phương thức cuối.
2. Gửi email thiết lập password, lấy thư đúng địa chỉ trong Mailpit, đặt password. Phiên cũ kết thúc.
3. Login email/password, đối chiếu UUID/workspace; phải giống trước. Sau reauth mới được unlink Google.

## Lỗi thường gặp

- redirect_uri_mismatch: so URL callback từng ký tự và đúng client; không dùng `/auth/callback` cũ.
- Không có nút Google: thiếu một trong hai env hoặc frontend chưa restart.
- Email đã có tài khoản nhưng Google chưa link: login email/password và dùng Account Center, không tự gộp bằng email.
- Không nhận thư trong Gmail: local dùng Mailpit tại http://127.0.0.1:8025 .
- Test user bị chặn: kiểm project/client/Audience và tài khoản đang chọn; không tắt state/PKCE hoặc sửa bảo vệ callback.

Ghi kết quả từng ca pass/fail cùng ngày/browser. Google thật, Mailpit local và SMTP Internet là ba evidence khác nhau.

Nguồn chính thức: https://developers.google.com/identity/protocols/oauth2/web-server .
