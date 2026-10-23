# M1 — triển khai flow Auth0 email/password — 2026-10-23

Thực hiện theo yêu cầu trực tiếp của người dùng, sau khi người dùng xác nhận Hào đã bàn giao phần backend/frontend. Owner và task status giữ tại [Core tracker](../tasks/CORE.md); ghi chú này là evidence, không tạo board trạng thái thứ hai.

## Kết quả local

Flow triển khai: `/login` → Auth0 Universal Login signup/login → `/auth/callback` → `/verify-email` hoặc `/onboarding` → atomic user + personal workspace bootstrap → `/dashboard` → reload/refresh → CSRF-protected logout. Password/reset do provider quản lý. Public previews không mount mock auth/workspace providers; dữ liệu thật nằm ở dashboard/BFF riêng.

Backend dùng PyJWT RS256, issuer/audience/expiry/subject checks, fixed JWKS với cache/cooldown, typed `/v1` contracts. Migration 0004 bổ sung `(issuer,subject)`, personal ownership, restricted SECURITY DEFINER bootstrap, FORCE RLS và runtime SELECT-only. Existing identity cần mapping do người có trách nhiệm xác nhận. Migration forward-only.

Next.js dùng official Auth0 SDK, Redis sessionStore, cookie ID HttpOnly/SameSite=Lax, HTTPS Secure. Session/token mã hóa AES-256-GCM và gắn AAD với session ID; không chuyển encrypted record giữa các ID được. Atomic update không phục hồi session đã logout. Refresh/update/logout dùng distributed lock; Redis socket timeout + heartbeat trả lỗi có giới hạn và có recovery. Verification resend lấy subject từ session và áp dụng một lần/phút, năm lần/giờ. Browser không nhận access/refresh token.

## Kiểm chứng

Môi trường: Windows/PowerShell, Python 3.12, Node 24; PostgreSQL 17 và Redis từ Docker Desktop. Source là HEAD `2b81f31` cộng working diff chưa commit; không coi SHA base là SHA đã chứa implementation.

| Kiểm tra | Kết quả đã chạy |
|---|---|
| Backend `python -m ruff check .` / `ruff format --check .` | PASS |
| Backend `python -m pytest -q`, có AUTH_TEST_DATABASE_URL trỏ DB tạm | 45 PASS; gồm 6 PostgreSQL integration cases và JWKS key rotation qua HTTP loopback |
| `scripts/tests` | 35 PASS; verifier isolation, cleanup, redaction và forward-only guard |
| Frontend lint / typecheck / production build | PASS; build còn warning dynamic dependency từ SDK Auth0 DPoP utility; DPoP không bật |
| `npm run test:workspace` | 4 PASS cho historical mock adapter fixtures |
| `npm run test:auth` | 14 PASS trên actual Next.js/FastAPI/Redis + signed OIDC fixture |
| Production Compose verifier | PASS build, bootstrap, upgrade head hai lần, downgrade refusal, 11 public routes, DB/Redis/API outage và recovery; isolated stack đã cleanup |
| Staging config generator + Compose JSON validator | PASS; secrets không in ra output; session Redis dùng network/secret riêng |
| `npm audit --omit=dev` | 0 runtime advisories tại lần kiểm tra local này |

OIDC E2E bao gồm login/provision/reload/logout, old-cookie replay, email chưa verify rồi relogin, callback giả/external return URL, refresh đồng thời chỉ một lần, resend CSRF/cooldown/hour quota, logout tab thứ hai, server session hết hạn, Redis interruption/recovery, hosted signup/wrong password. Redis tests kiểm tra encrypted payload, absolute expiry cap, atomic update sau logout, lock serialization và chống hoán đổi record.

PostgreSQL tests kiểm tra upgrade từ 0003 có dữ liệu legacy: thiếu issuer mapping phải dừng/rollback; mapping rõ ràng giữ user/workspace. Bao gồm same subject/different issuer, cùng email không merge, concurrent bootstrap chỉ một user/workspace, rollback, active status, membership revoke, paginated listing, cross-user spoofed headers, runtime không ghi role, missing context deny và connection-pool reuse.

Ảnh fixture đã xem trực tiếp: [login desktop](../frontend/evidence/auth/login-desktop.png), [dashboard desktop](../frontend/evidence/auth/dashboard-desktop.png), [dashboard mobile](../frontend/evidence/auth/dashboard-mobile.png). Dashboard 375×812 không overflow ngang, các nút/nội dung nhìn thấy. Đây là local functional/visual check, không tự ghi nhận human visual signoff.

Raw local diagnostics nằm trong `tmp/auth-e2e.log` và `tmp/eduvia-m0-20261023t034906z-6ca2a27e/result.json` (ignored, không dùng như artifact có sẵn trên máy khác). Workflow CI đã thêm `auth-integration` và mock-workspace regression step; chưa có GitHub run cho working diff.

## Giới hạn nghiệm thu và bàn giao

- Ban đầu chưa có tenant; hiện đã tạo tenant development và smoke local bằng Auth0/email thật theo bảng bổ sung bên dưới. [Runbook setup](../deploy/auth0/README.md) và [Post-Login Action](../deploy/auth0/post-login.js) đã chuẩn bị.
- Verification/reset mail thật và Auth0 local đã được người dùng xác nhận; chưa có HTTPS staging, email provider production hoặc chạy lại trên máy thứ hai. OIDC fixture không thay bằng chứng môi trường phát hành.
- Chưa có human reviewer signoff, chưa commit/push/PR/merge/deploy. Reviewer đề xuất Hào, chưa tự xác nhận nhận review.
- Migration schema cũ cần backup, issuer mapping và owner mapping rõ ràng. Không xóa volume để vượt migration failure; không downgrade phá dữ liệu.
- Bật user.is_active=false ở Eduvia chặn request tiếp theo. Khóa user/reset ở provider không đồng nghĩa JWT đã phát bị thu hồi tức thì; access-token lifetime 5 phút cộng clock tolerance 30 giây là cửa sổ phải kiểm chứng ở tenant.
- Các chức năng Library/Classes/AI vẫn là preview/planned; dashboard không tạo số liệu giáo dục giả cho tài khoản thật.

## Lệnh chạy lại

1. `docker compose -f compose.auth-test.yaml up -d --wait` từ root.
2. Trong `backend`, đặt AUTH_TEST_DATABASE_URL theo DB test trong compose.auth-test.yaml, rồi chạy `python -m pytest -q`. Chỉ dùng DB có tên kết thúc `_test`: integration fixture sẽ recreate edu schema trong DB đó.
3. Trong `frontend`: `npm ci`, `npx playwright install chromium`, `npm run test:auth`; Node runner tự chạy OIDC fixture, API test và Next.js test build. Python virtualenv mặc định theo OS; có thể đặt AUTH_TEST_PYTHON.
4. Chạy lint/typecheck/build; generate OpenAPI và frontend types theo README khi contract đổi.
5. Sau test: `docker compose -f compose.auth-test.yaml down`. Không dùng stack/database có dữ liệu cần giữ.


## Follow-up manual setup — empty legacy schema

Trong lúc người dùng setup local, database đã có schema edu rỗng và revision 0001_bootstrap nhưng chưa có role. Script khởi tạo cũ rollback khi CREATE SCHEMA gặp schema đã tồn tại. Đã sửa để chỉ nhận baseline trống/0001: kiểm tra schema không có object, tạo role và chuyển owner schema/version table trong transaction. Database có dữ liệu hoặc revision khác bị từ chối. CI auth integration bổ sung regression bootstrap. Kiểm chứng PostgreSQL tạm: 4 bootstrap scenarios + 6 identity integration cases = 10 PASS; lint pass. Test fixture cấp CONNECT rõ ràng, không dựa quyền PUBLIC. Người dùng đã chạy lại bootstrap thành công (COMMIT), migration exit 0 và xác nhận `0004_auth_identity (head)`; API readiness có PostgreSQL/Redis đều ok.

## Bàn giao Hào — manual Auth0 local và chuẩn bị commit

Ngày 2026-10-23, người dùng quyết định **giữ Auth0**, chưa đổi provider. Owner implementation Duc; Hào là reviewer đề xuất. Đây là ghi chú trong repo cho Hào, chưa gửi tin nhắn hoặc nhận review. Thay đổi còn ở working tree, chưa commit/push/deploy.

Evidence dưới đây do người dùng tự chạy và báo pass, không phải automation mới chạy lại:

| Kịch bản | Kết quả |
|---|---|
| Login Auth0 thật, mở dashboard/workspace personal owner | PASS |
| Reload giữ phiên; logout chặn dashboard/onboarding | PASS |
| Login lại có đúng một workspace cũ | PASS |
| Mật khẩu sai bị từ chối | PASS |
| Nhận email reset, mật khẩu mới vào workspace cũ, mật khẩu cũ bị từ chối | PASS |
| Chưa xác minh email vào verify-email, không vào dashboard | PASS |
| Xác minh qua email, đăng nhập lại, mở workspace | PASS |
| Logout tab thứ hai; Back sau logout tự về login | PASS |
| Session endpoint authenticated false/true đúng; không trả Auth0 tokens | PASS |
| /auth/access-token không được expose | PASS |
| Resend verification thật + giới hạn | SKIPPED theo yêu cầu người dùng |
| Chờ token hết hạn và refresh thật sau 6 phút | CHƯA XÁC NHẬN; người dùng chuyển sang trao đổi chi phí |
| Cross-account isolation bằng browser, tài khoản khóa, revoke membership | CHƯA manual check; có integration coverage đã ghi phía trên |

Lỗi đã xử lý trong setup: thiếu User-Delegated Access của Eduvia Local với API audience; thêm grant xong hiện Universal Login. Callback có một lần invalid_state, thử phiên mới thành công; chưa chứng minh nguyên nhân gốc. Thêm log callback chỉ có requestId, mã lỗi đã lọc và missingSession, không ghi message/token/cookie/URL callback.

Hào cần review: JWT/trust boundary và Redis lifecycle; migration 0004 cùng bootstrap legacy-empty; runtime grants/RLS; CSRF và contract; giới hạn email/refresh/revocation. Quyền hiện thực thi ở mức identity và active workspace membership; chưa có nghiệp vụ phân vai giáo viên/học sinh/admin, invitation hoặc UI quản lý thành viên. Chưa đánh dấu task done chỉ dựa vào smoke local.

Còn trước nghiệm thu phát hành: cấu hình/kiểm tra Management API cho resend, email provider production, refresh trên Auth0 thật, HTTPS staging, chạy lại từ runbook trên máy thứ hai, GitHub CI và reviewer signoff. Không đưa secret hoặc dữ liệu session thực vào commit.

### Kiểm tra bổ sung trước commit

Frontend ESLint và `tsc --noEmit`: PASS. Backend Ruff: PASS; 23 auth/context/provisioning tests PASS khi chạy ngoài sandbox. Lần chạy sandbox timeout ở Windows socketpair/asyncio, không coi là pass và không bỏ test. `git diff --check`: PASS; backend/.env và frontend/.env.local được Git ignore. Các full-suite/build/integration kết quả phía trên là lần kiểm chứng trước, không tuyên bố vừa chạy lại.
