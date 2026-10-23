# Better Auth local + Mailpit — bàn giao Hào

Owner Duc; reviewer đề xuất Hào, chưa signoff. Bổ sung sau retirement Auth0; không sửa API, schema hoặc logic auth application trong đợt này.

## Thay đổi

- Compose profile `dev-mail`, Mailpit v1.31.5 pin digest sha256:94f6b70c1436defae6799d9ac7ff0eeff9540465b842026d5cdb018f1c0234ea. SMTP/UI publish chỉ 127.0.0.1:1025/8025; readyz healthcheck, không relay/forward. Không thêm vào staging.
- Frontend native local env dùng SMTP Mailpit và sender auth@example.test. Đã restart đúng các process Eduvia ở cổng 3000/8000, không đụng process dự án khác. PostgreSQL/Redis/Mailpit đang chạy; auth services native nhận env mới.
- Thêm `npm run test:auth:local`, Playwright config riêng không fixture server/reset schema/flush Redis; tạo account synthetic mới mỗi run. Mật khẩu random, không ghi log; trace tắt. Account/workspace smoke còn trong local DB, không phải dữ liệu thật của người dùng.
- [Setup từng bước](../deploy/better-auth/SETUP-LOCAL.md), [Google local](../deploy/better-auth/GOOGLE-LOCAL.md) và frontend README cập nhật. Auth0 Dashboard teardown vẫn theo runbook retirement; chưa có evidence xóa tài nguyên cloud.

## Evidence hiện tại

**Automated native local PASS (1 browser scenario, lượt cuối 9.0 giây):** signup gửi SMTP vào Mailpit thật; unverified login 403 và bootstrap 401; verify link; email/password login; bootstrap workspace; reload; Account Center; reset password qua Mailpit; password cũ 401; password mới vào cùng UUID/workspace; logout rồi Back/reload/me bị chặn. Không intercept Google hay dùng SMTP fixture trong test này. Native app là localhost 3000/8000 và DB local hiện tại.

Readiness thực trả ready với postgres ok/redis ok. Mailpit UI/API trả HTTP 200, container healthy. Kiểm Compose PASS: profile không bật mặc định, version+digest, port loopback, healthcheck, không relay/forward và không có Mailpit trong staging. Frontend lint/typecheck PASS cho config/test mới. Không sửa application nên không chạy lại toàn bộ backend/fixture suites hoặc production build ngoài phạm vi thay đổi.

Evidence JSON lọc lưu ignored `tmp/better-auth-local/email-smoke-evidence.json` để đối chiếu local; không chứa password/token/cookie. Raw test-results/log là ignored diagnostics, không đẩy session thật lên Git. Các số 54 backend/9 fixture E2E/production build ở retirement là evidence trước đó, không giả thành lượt chạy mới của đợt config này.

## Chưa nghiệm thu

Manual local của người dùng: PENDING. Google OAuth client/credentials thật: PENDING; chưa smoke login/link/unlink/cancel bằng Google thật. Email Internet, HTTPS staging, máy thứ hai, GitHub CI và reviewer signoff: PENDING. Không coi thư Mailpit là Gmail delivery hoặc Google fixture là real-provider smoke. Google-first manual cần Google account thứ hai chưa có Eduvia account; nếu thiếu ghi chưa kiểm thay vì xóa/gộp dữ liệu.

Bước tiếp theo cho người dùng: mở login, tạo email/password bằng email Google định link và verify qua Mailpit; sau đó theo Google setup từng bước. Không gửi secret vào chat. Chưa commit/push.

Commit message đề xuất cho toàn bộ working diff retirement + local mail hiện tại: `feat(auth): retire Auth0 and add local Mailpit smoke tests`.
