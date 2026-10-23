# Review và phản hồi

Mỗi yêu cầu ghi task và revision. Người yêu cầu đề xuất reviewer; người review tự ghi kết luận của mình.

## 2026-10-23 — M1 identity slice (912c0d2) — review của Hao (nháp do agent chuẩn bị)

> **Đây là nháp do agent chuẩn bị cho Hao xác nhận, không phải approval.** Hao cần tự đọc lại các finding, chỉnh mức độ và ghi kết luận chính thức. Agent chỉ đọc source và chạy các lệnh không phá hủy; không sửa code/test/tracker, không commit.

- Người chuẩn bị: agent theo yêu cầu người dùng; reviewer đề xuất: Hao (chưa xác nhận nhận review). Ngày 2026-10-23 (Asia/Ho_Chi_Minh).
- Task: [Core BE-01..06, FE-01..04, QA-01..02, DOC-01](../tasks/CORE.md) (execution record 2026-10-23), bàn giao của Duc: [2026-10-23-auth-implementation.md](2026-10-23-auth-implementation.md), runbook [deploy/auth0/README.md](../deploy/auth0/README.md), ADR [0001](../tasks/decisions/0001-identity-provider-adr.md) / [0002](../tasks/decisions/0002-session-token-trust-boundary-adr.md).
- **Revision đã xem:** commit `912c0d2` (merge `5f05030`), diff `git diff 77d2aa6 5f05030` (79 file). Working tree lúc review có file ngoài diff (`backend/app/api/workspace_access.py`, `backend/migrations/versions/0009_classes.py` untracked; `backend/app/core/config.py` sửa thêm `upload_max_bytes`); không thuộc phạm vi review này và không được đánh giá.
- Phạm vi đọc: `backend/app/core/auth.py`, `app/api/identity.py`, `app/main.py`, `app/services/user_provisioning.py`, `app/infrastructure/context.py`, `migrations/versions/0004_auth_identity.py`, `deploy/postgres/bootstrap.sql`, compose/CI, `frontend/src/lib/server/*`, `src/proxy.ts`, `src/app/api/**`, `account-screen.tsx`, tests backend và `frontend/tests/auth/*`, docs/`.env.example`.

### Lệnh đã chạy (trên revision trên, Windows/Git Bash)

| Lệnh | Kết quả |
|---|---|
| `backend/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` (từ `backend/`) | `39 passed, 10 skipped, 1 warning in 2.80s`. 10 skipped = 6 `test_identity_integration.py` + 4 `test_bootstrap.py` vì không có `AUTH_TEST_DATABASE_URL`/PostgreSQL tạm; **PostgreSQL integration không được chạy lại trong lượt review này** |
| `python -m ruff check .` / `ruff format --check .` (backend) | `All checks passed!` / `40 files already formatted` |
| `python scripts/export_openapi.py` ra file tạm, so với `contracts/openapi.json` | Không drift; file tạm đã xóa |
| `npm.cmd run lint` (từ `frontend/`) | Không có cảnh báo/lỗi (`--max-warnings 0`) |
| `npm.cmd run typecheck` | **Không kết luận được**: 37 lỗi TS đều là `TS2307 Cannot find module` (`@auth0/nextjs-auth0`, `@playwright/test`) và lỗi `implicit any` kéo theo, vì `frontend/node_modules` trên máy này thiếu `@auth0`, `@playwright`, `redis` (chưa `npm ci` theo lockfile mới). Không chạy `npm install` theo yêu cầu. Lệnh này cũng ghi lại `frontend/next-env.d.ts`; đã `git checkout` file đó về trạng thái commit. Handover của Duc ghi typecheck PASS, chưa có bằng chứng độc lập |
| Không chạy | Playwright (`test:auth`), Docker, `next dev`, PostgreSQL integration, GitHub CI (chưa có run cho diff này) |

### Bảng finding

Mức: P1 = chặn merge (security/isolation/mất dữ liệu); P2 = sửa trước M1 gate; P3 = follow-up. **Không tìm thấy P1** trong phạm vi đã đọc; xem "Quyết định đề xuất".

| ID | Mức | File:dòng | Mô tả | Đề xuất |
|---|---|---|---|---|
| R-01 | P2 | `frontend/tests/auth/start-service.mjs:12`, `frontend/src/lib/server/auth.ts:25`, `.github/workflows/ci.yml:179-186` | E2E `test:auth` chạy trên `next dev` qua HTTP (`APP_BASE_URL=http://127.0.0.1:3105`). Cờ cookie chỉ được assert `httpOnly` và `SameSite=Lax` (`login.spec.ts:27-28`). `Secure` khi HTTPS, host-only và hành vi production build chưa có test nào; handover cũng ghi HTTPS staging chưa kiểm chứng. Đây là acceptance FE-01/ADR 0002 ("HttpOnly, Secure, SameSite=Lax, host-only") | Thêm unit test cho cấu hình cookie với `APP_BASE_URL` https, hoặc chạy một ca E2E trên `next start` và assert `Set-Cookie` (Secure, không Domain). Ít nhất kiểm `Set-Cookie` trên staging HTTPS trước M1 gate |
| R-02 | P2 | `frontend/src/lib/server/auth.ts:60-66`, `frontend/tests/auth/login.spec.ts:30-31,52,85` | Logic CSRF (Origin + token) đúng, nhưng test chỉ kiểm POST **thiếu cả Origin lẫn token** (403). Chưa có ca: Origin sai + token đúng, Origin đúng + token sai, token của session khác. QA-02 yêu cầu suite CSRF có evidence; hiện test vẫn pass nếu một nửa điều kiện bị xóa | Thêm 3 ca trên cho `bootstrap`, `resend-verification`, `logout` (`page.request.post` với header tùy chỉnh) |
| R-03 | P2 | `frontend/src/components/auth/account-screen.tsx:97-111`, `frontend/tests/auth/login.spec.ts` (không có ca), handover mục "Cross-account isolation... CHƯA manual check" | FE-04 ("switch invalidate tenant caches") và QA-02 ("hai users ... workspace switch") chưa có test ở tầng browser: tài khoản thử chỉ có 1 workspace nên selector/`more()`/`switchWorkspace` chưa chạy với >=2 workspace; không có ca hai user khác nhau trên cùng browser/Redis. Phía backend có coverage (`test_identity_integration.py:182,270`) nên không phải lỗ hổng isolation, nhưng acceptance hàng FE-04/QA-02 chưa đủ | Thêm E2E: user A có thêm membership qua DB fixture, chuyển workspace, rồi logout/login user B và khẳng định không còn dữ liệu A; hoặc ghi rõ FE-04/QA-02 còn `in_progress` vì thiếu ca này |
| R-04 | P2 | handover mục "Giới hạn nghiệm thu", `frontend/src/lib/server/auth.ts:80-88` | Bằng chứng chỉ manual/chưa có: refresh token thật trên Auth0 (chưa xác nhận sau 6 phút; code dựa vào `getAccessToken()` rồi `updateSession()` trong lock, rủi ro với refresh-token rotation + reuse detection nếu ghi Redis lỗi giữa chừng), resend verification thật (SKIPPED), máy thứ hai, HTTPS staging, GitHub CI (job `auth-integration` chưa chạy lần nào), revoke/khóa tài khoản bằng browser. Callback từng gặp `invalid_state` chưa rõ nguyên nhân gốc | Giữ BE-01/FE-01/QA-01/DOC-01 ở `in_progress`; trước M1 gate: chạy refresh thật (đợi quá 5 phút, thêm ca Redis lỗi sau refresh), `auth-integration` xanh trên GitHub, người thứ hai chạy lại runbook |
| R-05 | P2 | `DEVELOPMENT.md:13`, `backend/README.md:59`, `tasks/decisions/0001-identity-provider-adr.md:3,34`, `tasks/decisions/0002-session-token-trust-boundary-adr.md:3` | Docs drift: (a) DEVELOPMENT.md nói "tenant/email setup and real-provider smoke remain outstanding" trong khi handover/ADR ghi tenant dev đã tạo và smoke Auth0/email thật đã làm (cần thống nhất: đã có smoke local, chưa có staging/production); (b) lệnh trong backend README thiếu `test_bootstrap.py` mà CI có chạy (`ci.yml:179`) và handover coi là regression bắt buộc; (c) hai ADR vẫn ghi "Trạng thái: Đề xuất"; ADR 0001 mục 3 vẫn nêu "Dev Mode ... mock token" và phương án Supabase/Keycloak, mâu thuẫn với phần "Chốt triển khai" (Auth0, không có mock). DOC-01 yêu cầu implemented-status cập nhật | Cập nhật ba chỗ trên; chuyển trạng thái ADR theo quyết định của owner/người chịu trách nhiệm (reviewer không tự đổi) |
| R-06 | P3 | `backend/app/core/auth.py:23,32` | `PyJWKClient(timeout=5, lifespan=300)`: PyJWT 2.15.1 có cooldown refresh khi `kid` lạ (mặc định 30 giây, đã xác minh trong source và `test_auth.py:99-150`), nhưng `get_signing_key` giữ một lock toàn cục trong lúc fetch và hết `lifespan` thì không dùng key cũ nếu fetch lỗi. Khi JWKS Auth0 chậm/lỗi, các request xác thực xếp hàng tối đa ~5 giây/lần trong thread pool và trả 503 dù cache cũ còn khóa hợp lệ | Cân nhắc stale-if-error (giữ JWK set cuối vài phút); thêm log/metric cho `identity_unavailable` |
| R-07 | P3 | `backend/app/core/auth.py:33-41`, `backend/app/api/identity.py:83-87` | Không loại tường minh token machine-to-machine (`gty=client-credentials`, `sub` kết thúc `@clients`). Hiện an toàn vì Post-Login Action không chạy cho client-credentials nên thiếu claim email (401/403). Nếu sau này thêm Action Credentials Exchange hoặc cấp M2M cho audience Eduvia, token M2M có thể tạo user | Từ chối `gty == "client-credentials"` hoặc allowlist `azp`; thêm negative test |
| R-08 | P3 | `backend/app/main.py:80-84`, `backend/app/api/identity.py:149-153` | Handler `DBAPIError` trả 503 `database_unavailable` cho mọi lỗi DB (kể cả lỗi lập trình/constraint/thiếu grant) và không log gì, nên lỗi grant hoặc RLS vô hình với vận hành. SQLSTATE `28000` dùng chung cho "Missing verified identity" và "Account disabled" nên cả hai thành `account_disabled` | Log tên lỗi + sqlstate + requestId (không log tham số); dùng SQLSTATE/message riêng |
| R-09 | P3 | `backend/app/main.py:24-28` | Guard runtime-role chỉ so tên `eduvia_runtime` và chỉ khi `auth_issuer` được bật; không kiểm `rolsuper`/`rolbypassrls` thật của kết nối | Check lúc startup/readiness: `rolsuper` và `rolbypassrls` của `current_user` phải false |
| R-10 | P3 | `backend/migrations/versions/0004_auth_identity.py:35-42,52-57`; `backend/tests/test_identity_integration.py:44-77` | Mapping `identity_map` chỉ kiểm `startswith("https://")`; issuer thiếu dấu `/` cuối (Auth0 dùng `https://tenant.auth0.com/`) sẽ gán sai issuer, user thật sau đó bootstrap thành user mới với workspace mới (tách đôi dữ liệu, không mất dữ liệu). Test legacy chỉ có ca một owner hợp lệ và ca thiếu mapping; chưa có ca personal workspace 0 owner / 2 owner dừng migration, hoặc một user sở hữu 2 personal workspace vi phạm `uq_personal_owner` | Chuẩn hóa/kiểm issuer khớp `AUTH_ISSUER`; thêm 2-3 test dừng/rollback cho dữ liệu mơ hồ |
| R-11 | P3 | `backend/migrations/versions/0004_auth_identity.py:45-46,110-115` | Upsert ghi đè `email` và `display_name` theo claim ở **mỗi lần** bootstrap; `users_email_key` bị bỏ nên email không còn unique, và DB không lưu `email_verified`. An toàn cho identity hiện tại (khóa là `(issuer,sub)`), nhưng các tính năng sau (invitation, tìm user theo email) không được tin cột `email` làm định danh | Ghi vào ADR/tracker: invitation gắn vào `(issuer,sub)` đã xác thực hoặc yêu cầu email_verified lúc chấp nhận; cân nhắc không ghi đè tên người dùng đã chỉnh sau này |
| R-12 | P3 | `backend/migrations/versions/0004_auth_identity.py:119-128`, `backend/app/api/identity.py:144-147` | Đúng thiết kế "không resurrect": user `is_active=false` bị chặn (28000 -> 403 `account_disabled`); workspace personal archived hoặc membership revoked không được bật lại, API trả 403 `workspace_unavailable`. Nhưng chưa có đường khôi phục/UI quản trị nào nên user kẹt nếu dữ liệu bị đặt nhầm | Ghi vào runbook quy trình DBA khôi phục (SQL có audit); không cần đổi code |
| R-13 | P3 | `backend/migrations/versions/0004_auth_identity.py:135-143`, `backend/tests/test_identity_integration.py:22-33` | Grant cho runtime bọc trong `IF EXISTS eduvia_runtime`: nếu role runtime được tạo sau migration thì không có SELECT/EXECUTE và API fail closed (an toàn, khó chẩn đoán). Integration test chạy migration bằng superuser của DB test, không phải `eduvia_migrator`; đường ownership/`ALTER FUNCTION OWNER`/membership role chỉ được verifier Compose (`containers` job) kiểm | Ghi thứ tự bắt buộc (bootstrap -> migrate) trong runbook; thêm thông báo lỗi rõ khi thiếu role |
| R-14 | P3 | `frontend/src/lib/server/session-store.ts:34-40,46-51` | `open()` ném lỗi khi giải mã sai (đổi `SESSION_ENCRYPTION_KEY`, record hỏng/bị hoán đổi): `get()` không trả `null` nên mọi request mang cookie đó nhận 503/trang lỗi thay vì bị coi là hết phiên. Runbook nói "đổi khóa yêu cầu logout mọi phiên" nhưng thực tế người dùng thấy lỗi tới khi xóa cookie hoặc login lại | Bắt lỗi xác thực GCM trong `get()`: xóa key Redis và trả `null` (log mã lỗi), giữ nguyên lỗi cho lỗi Redis |
| R-15 | P3 | `frontend/src/lib/server/auth.ts:25`, `frontend/src/lib/server/session-store.ts:41-43` | `rolling:false` cùng `inactivityDuration:7200`: cần xác nhận SDK có áp dụng inactivity khi `rolling:false` không. Idle 2 giờ thực tế đến từ TTL Redis (tối đa 7200 giây, chỉ làm mới khi `set/update`, tức mỗi lần gọi `/api/session` hoặc BFF `backend()`); SSR `requireSession` không làm mới. Chấp nhận được nhưng chỉ test ở mức TTL (`session-store.spec.ts:23`) | Ghi rõ ngữ nghĩa idle trong runbook; thêm một ca E2E idle |
| R-16 | P3 | `frontend/src/lib/server/auth.ts:51`, `frontend/next.config.ts:5` | `AUTH_TEST_MODE=1` bật log stack frame trong `failure()` và đổi `distDir` mà không có guard theo `NODE_ENV` (chỉ `allowInsecureRequests` có guard ở `auth.ts:28`). Compose staging không truyền biến này nên hiện không khai thác được; chỉ có tài liệu cấm | Fail startup khi `NODE_ENV=production` và `AUTH_TEST_MODE=1` |
| R-17 | P3 | `frontend/src/lib/server/auth.ts:10-13` | `APP_BASE_URL` rỗng rơi về `http://127.0.0.1:3000`, và production vẫn cho `http` với loopback (cookie `secure:false`). Staging `--tunnel` sinh `APP_BASE_URL=''` (`deploy/generate-env.py`). Fail-closed trên thực tế (callback về localhost sẽ lỗi) nhưng khó chẩn đoán | Production bắt buộc `APP_BASE_URL`, báo `auth_unconfigured` thay vì dùng mặc định |
| R-18 | P3 | `frontend/src/lib/server/auth.ts:76-94` | Ghi chú cho endpoint tương lai: `backend()` chỉ chuyển tiếp GET hoặc POST **không body, không Content-Type**, luôn `response.json()`; chỉ non-GET được kiểm CSRF và mọi route là allowlist tĩnh (không có catch-all `/api/backend/[...path]`, tốt). Khi thêm POST/PUT có body cần: chuyển tiếp body có giới hạn kích thước, kiểm Content-Type, giữ CSRF, xử lý 204/non-JSON, và không cho `path` đến từ input chưa chuẩn hóa | Ghi vào hướng dẫn BFF; thêm test cho từng route mutation mới |
| R-19 | P3 | `frontend/src/app/api/auth/resend-verification/route.ts:13-29` | Mỗi lần gửi lại lấy một Management API M2M token mới (không cache), mỗi token tính vào hạn mức M2M của tenant; rate limit tính cả request lỗi ở provider (đã ghi trong runbook); không có giới hạn toàn cục ngoài quota theo identity | Cache token M2M đến gần hết hạn; thêm giới hạn toàn cục nhẹ nếu mở đăng ký công khai |
| R-20 | P3 | `frontend/next.config.ts:7-18`, `frontend/src/lib/server/auth.ts:25` | Chưa có `Content-Security-Policy`, `Strict-Transport-Security` (có thể ở TLS terminator) và cookie không dùng tiền tố `__Host-`. Token không nằm trong trình duyệt nên ảnh hưởng XSS bị giới hạn, nhưng CSP vẫn là lớp phòng thủ cần cho trang đăng nhập | Thêm CSP cơ bản và HSTS ở staging; cân nhắc `__Host-eduvia_session` khi có HTTPS |
| R-21 | P3 | `frontend/src/proxy.ts:7`, `frontend/tests/auth/login.spec.ts:60-64` | (a) `/auth/backchannel-logout` bị 404 nên Auth0 không đẩy được logout; thu hồi chỉ có hiệu lực qua refresh thất bại hoặc `is_active=false` (handover đã ghi). (b) Chưa thấy test xác nhận SDK cấp **session ID mới** khi callback thành công lúc cookie cũ còn tồn tại (session fixation); test "old-cookie replay" của handover là về logout. Không xác minh được vì thiếu `node_modules/@auth0` | Thêm ca E2E: có cookie cũ, đăng nhập user khác, khẳng định ID cookie đổi và record cũ bị xóa |
| R-22 | P3 | `frontend/tests/auth/login.spec.ts:7,21,23`, `compose.yaml:105` | (a) Mỗi lần chạy test ghi đè ba ảnh đã commit trong `frontend/evidence/auth/` nên cây làm việc bẩn sau test và evidence bị thay thế im lặng. (b) Compose dev dùng chung Redis (DB 2, không mật khẩu) cho session với cache/broker; staging đã tách và có mật khẩu | Ghi ảnh vào `test-results/` (đã ignore), chỉ copy evidence khi cần; ghi chú dev-only trong README |
| R-23 | P3 | `frontend/src/components/auth/account-screen.tsx:26-31,34` | `response.json()` ném `SyntaxError` khi proxy/BFF trả non-JSON; `handleError` hiển thị `error.message` thô cho người dùng. Không rò bí mật nhưng thông báo khó hiểu | Bắt lỗi parse và dùng thông báo chung "Chưa thể hoàn thành. Vui lòng thử lại." |

Số lượng: **P1 = 0, P2 = 5 (R-01..R-05), P3 = 18 (R-06..R-23)**.

### Đạt (đã xác minh trong source/lệnh trên)

- **Token trust boundary** (`auth.py:25-48`, `identity.py:64-90`): chỉ RS256 (kiểm header `alg` trước và `algorithms=["RS256"]` khi decode; test HS256/none ở `test_auth.py:73`), `kid` bắt buộc, `iss`/`aud` khớp cứng, bắt buộc `iss aud sub exp iat`, leeway 30 giây, giới hạn độ dài token 16384 và `sub` <= 255, JWKS URL cố định từ cấu hình (header `jku` bị bỏ qua, có test), JWKS lỗi kết nối -> 503 `identity_unavailable` chứ không phải 401, xác minh chạy trong thread (`asyncio.to_thread`) nên không chặn event loop.
- **Identity API** (`identity.py`): không có đường nào đọc `X-User-*`/header danh tính hay body; `email_verified` lấy từ claim đã ký, thiếu -> 403 `email_unverified`; `404 workspace_not_found` dùng chung cho "không tồn tại" và "không phải thành viên" nên không lộ sự tồn tại; mọi `/v1` trả `Cache-Control: no-store` kèm `requestId`; pagination chỉ trả membership của chính user.
- **main.py**: guard role runtime; docs/openapi tắt ở production; handler lỗi trả schema `{error:{code,message},requestId}`; không rò chi tiết exception.
- **CORS GET-only là chủ ý, không phải lỗi**: `allow_methods=["GET"]`, `allow_headers` không có `Authorization` (`main.py:94-95`). Trình duyệt chỉ gọi `/api/*` cùng origin của Next.js BFF (`account-screen.tsx` dùng đường dẫn tương đối; không có `NEXT_PUBLIC_*` hay URL backend phía client; `API_INTERNAL_URL` chỉ đọc ở server). `/v1/auth/bootstrap` là POST nhưng chỉ BFF gọi server-to-server, khớp `backend/README.md`.
- **Migration 0004** (đọc source): ánh xạ dữ liệu cũ bắt buộc `identity_map` rõ ràng, thiếu -> dừng và rollback (test khẳng định version vẫn `0003`); personal workspace phải có đúng một owner; toggle `NO FORCE` nằm trong cùng transaction DDL của Alembic rồi `FORCE` lại ở dòng 68; bỏ constraint cũ rồi thêm `uq_user_identity (issuer,sub)`; hàm `SECURITY DEFINER` đặt `search_path=pg_catalog,edu`, owner `eduvia_identity_owner` NOLOGIN NOBYPASSRLS, `REVOKE ALL ... FROM PUBLIC`, `REVOKE CREATE` sau khi đổi owner; policy cho owner chỉ có SELECT/INSERT/UPDATE (không DELETE); runtime chỉ còn SELECT trên 3 bảng cộng EXECUTE ba hàm; user `is_active=false` không bị update và không tạo workspace (`WHERE edu.users.is_active`); upsert khóa dòng danh tính nên bootstrap đồng thời chỉ tạo một workspace (có test); downgrade ném lỗi (forward-only).
- **bootstrap.sql / test_bootstrap.py**: đường "schema edu rỗng + 0001" chỉ nhận baseline rỗng (không object trong `pg_class/pg_proc/pg_type`, `alembic_version` đúng một dòng `0001_bootstrap`), mọi lỗi rollback cả transaction; DB có dữ liệu hoặc revision khác bị từ chối không đổi trạng thái (4 ca: fresh, adopt 0001, populated, wrong_revision). Tên DB dùng `:"database_name"` thay vì hard-code.
- **BFF**: cookie `HttpOnly`, `SameSite=Lax`, host-only, `Secure` theo HTTPS; token và profile mã hóa AES-256-GCM với AAD là session ID (hoán đổi record bị từ chối, có test), TTL Redis giới hạn bởi hạn tuyệt đối 24 giờ và tối đa 2 giờ idle, `update` dùng `XX` nên không hồi sinh phiên đã logout; khóa phiên phân tán (`SET NX PX` + Lua release theo owner) cho refresh/update/logout; không có endpoint trả token (`enableAccessTokenEndpoint:false`, `/auth/*` khác login/callback bị 404, `/api/session` chỉ trả tên/email/CSRF); `returnTo` cố định `/onboarding`, redirect callback cố định theo `appOrigin()` (có test `returnTo` ngoài); log lỗi chỉ chứa mã đã lọc bằng regex và `requestId` (không message/token/cookie/URL); `redirect:"error"` + timeout 5 giây khi gọi backend; `/api/backend/*` là allowlist tĩnh, `id` được kiểm định dạng và query chỉ nhận `cursor`/`limit`; resend lấy `sub` từ session, không nhận body, rate limit Lua nguyên tử.
- **Tests/CI**: backend có 6 ca integration PostgreSQL (concurrency, spoof, revoke, runtime không ghi role, same-sub-different-issuer, pagination) và test verifier (sai chữ ký, alg confusion, thiếu claim, JWKS outage, rotation); frontend có 14 ca E2E theo handover (đã đối chiếu danh sách ở `login.spec.ts` và `session-store.spec.ts`); CI có job `auth-integration` và `test:workspace` (đóng P2 CI từ lượt FE-02a). Contract OpenAPI không drift, ruff sạch.
- **Secrets**: `backend/.env.example` và `frontend/.env.example` chỉ có placeholder/comment (`YOUR_TENANT`, giá trị rỗng); `git ls-files` không chứa `.env` thật, `.env*` được ignore; không thấy secret/private key trong diff (khóa fixture OIDC sinh lúc chạy; `test-secret`, `"a".repeat(64)` chỉ ở test). Ảnh evidence là ảnh fixture, chưa có human visual signoff.
- **Docs khác**: runbook Auth0 nhất quán với code về token 5 phút, clock tolerance 30 giây, mapping migration, role `eduvia_identity_owner`, và nêu rõ các giới hạn (không thu hồi JWT tức thì, resend/refresh chưa xác nhận).

### Quyết định đề xuất

**Không có P1 trong phạm vi đã đọc: đề xuất chấp nhận code ở mức đã merge (`5f05030`) với điều kiện giữ BE-01..06, FE-01..04, QA-01..02, DOC-01 ở `in_progress` và không coi M1 gate là đạt cho tới khi xử lý R-01..R-05** (1: kiểm cờ cookie HTTPS và test CSRF đầy đủ, R-01/R-02; 2: ca nhiều workspace/hai user, R-03; 3: refresh Auth0 thật, `auth-integration` xanh trên GitHub, người thứ hai chạy lại runbook, R-04; 4: sửa docs/ADR, R-05). P3 đưa vào backlog; nên làm sớm R-10 (migration trên DB có dữ liệu) và R-14 (vận hành khi xoay khóa).

Giới hạn của nháp này: không chạy PostgreSQL integration, Playwright, Docker hay build; `typecheck` không kết luận được trên máy này (thiếu dependency); hành vi nội bộ của `@auth0/nextjs-auth0` (R-15, R-21) suy ra từ code gọi, chưa đọc source SDK. **Kết luận chính thức, SHA đã xem và ngày: để Hao tự xác nhận và ghi bổ sung bên dưới.**

### Phản hồi — Hao — (chưa có)

- Revision đã xem: _để Hao ghi_
- Kết luận: _để Hao ghi_


## 2026-10-22 — FE-02a — onboarding/workspace mock

- Người chuẩn bị: Codex theo yêu cầu người dùng, phía Duc; reviewer đề xuất: Hao (chưa xác nhận nhận review).
- Task/revision: [Core FE-02a](../tasks/CORE.md), branch `feat/fe-02-workspace-mock`; base `2379a6e5e70b5c65645880202cae6bab5b11ac8b` cộng diff/file mới chưa commit. Chưa có source SHA mới hoặc remote PR. Cập nhật SHA sau commit; reviewer phải xem revision đó, không duyệt chỉ theo base.
- Thay đổi: login thử đi qua onboarding, workspace mẫu gắn với từng auth generation, reuse/retry và bỏ kết quả cũ khi rời route/logout/expiry. Không có backend, migration, HTTP contract, dependency hay authorization change.
- Evidence và phạm vi commit: [FE-02a.md](../frontend/FE-02a.md); nội dung PR chuẩn bị tại [FE-02a-PR.md](../frontend/FE-02a-PR.md). Baseline lint/typecheck/build, 4 adapter tests, 14 backlog tests pass; review docs không phải lượt chạy lại.
- Cần tập trung: guard sau mỗi await/catch/finally, pending Promise reuse, session mới cùng user ID không kế thừa workspace cũ; onboarding chưa login không provisioning, preview vẫn truy cập được.
- Còn mở P2: visual gate chưa đạt vì capture sai so với DOM; frontend CI chưa gọi `test:workspace`. Đề nghị phối hợp workflow riêng; trong lúc chưa có CI step, reviewer chạy test thủ công. Không tự gán deadline hoặc xác nhận Hao đã nhận việc.
- Checklist visual: kiểm trực tiếp login/onboarding/dashboard ở 375×812 và 1440×900, chữ/nút không bị cắt, scroll/focus/logout truy cập được; lưu ảnh đáng tin cậy. Ảnh hiện có chỉ để chẩn đoán.
- Kết luận reviewer / SHA đã xem / ngày / kiểm tra đã chạy: **chưa có**; để Hao tự bổ sung. Chưa tuyên bố acceptance đầy đủ hoặc sẵn sàng merge.

## 2026-10-21 — BASE-01 / BASE-05 — tooling và CI

- Người chuẩn bị: Codex theo yêu cầu người dùng; branch `fix/tooling-ci`, base `302762b` cộng diff chưa commit.
- Phạm vi: setup tương thích PowerShell 5.1/7; verifier theo Alembic head và schema identity; regression tests và CI Windows/Linux.
- Evidence và hành động cần review: [BASE-tooling-ci.md](BASE-tooling-ci.md).
- Cần reviewer xác nhận: setup không thay môi trường trong CheckOnly; migration chỉ chạy trên DB tạm; timeout/cleanup/report an toàn; CI artifact không chứa env file.
- Reviewer con người / SHA duyệt: chưa có. CI của branch mới chưa chạy trước khi push; không coi CI xanh của base là bằng chứng cho diff này.

## Cập nhật yêu cầu lint/format bên dưới

Bản sửa đã merge qua PR #1; [Foundation CI tại 302762b](https://github.com/haonnedu/AI-LMS-SaaS/actions/runs/39560321514) xanh. Yêu cầu bên dưới là bản ghi trước commit; không còn chờ push bản sửa lint. Không tự ghi nhận reviewer con người nếu chưa có thông tin review cụ thể.

## 2026-10-21 — BASE-02 / DB-02 — sửa lint/format migration 0002

- Người chuẩn bị: Codex theo yêu cầu người dùng; chưa có reviewer con người xác nhận nhận review.
- Task: [BASE-02 và DB-02 trong Core](../tasks/CORE.md); finding [D-01](2026-10-21-source-review.md).
- Revision: base `c99874481683692c84b58ac7ae99da87a31e4637` cộng migration local có Git blob `4e2b4b4cebe533ff7635660fcd434434f4ef3356`; chưa có commit/PR cho bản sửa.
- Phạm vi: xóa 2 import thừa, format lệnh tạo index; SQL, revision và upgrade/downgrade không đổi. Không có dependency/API/contract/workflow change.
- [Evidence và phạm vi commit](BASE-02-lint-format.md): lint/format pass, 16 tests pass, OpenAPI không drift, DB trống upgrade/repeat upgrade và readiness thật 200.
- Cần reviewer: xác nhận diff chỉ đổi import/format, xem evidence đúng revision và kiểm tra Foundation CI sau push. Không coi bản sửa này đã hoàn tất identity/RLS hoặc M0.
- Chưa kiểm chứng: GitHub CI trên SHA mới; chưa có người review chấp thuận. Các thiếu sót schema/roles/RLS vẫn mở.
- Kết luận reviewer / revision đã xem / ngày: **chưa có**; để reviewer tự bổ sung.

## Mẫu yêu cầu

```markdown
## YYYY-MM-DD — <TASK-ID> — <chủ đề>

- Người yêu cầu / reviewer đề xuất: <tên> / <người còn lại>
- Task: <link tracker>
- PR / commit cần review: <link hoặc SHA>
- Phạm vi: <behavior thay đổi; migration/contract/dependency impact>
- Acceptance cần kiểm tra: <điều kiện quan sát được>
- Evidence: <lệnh, exit code, môi trường; phân biệt mock và integration>
- Điểm cần tập trung: <rủi ro/câu hỏi cụ thể>
- Chưa kiểm chứng: <giới hạn và blocker>

### Phản hồi — <reviewer> — <ngày giờ>

- Revision đã xem: <SHA>
- Kết luận: <cần sửa / chấp thuận / cần thêm bằng chứng>
- Finding: <file:dòng, vấn đề, kết quả mong đợi>
- Kiểm tra đã thực hiện: <evidence hoặc chỉ đọc source>

### Xử lý phản hồi — <tác giả> — <ngày giờ>

- Finding đã xử lý / còn mở: <liên kết>
- Revision mới và kiểm tra bổ sung: <SHA/evidence>
- Yêu cầu reviewer xem lại: <phạm vi>
```

Trước khi chốt: acceptance đạt, tests phù hợp, migration/contract được xem xét, không rò secrets/dữ liệu, giới hạn evidence được ghi. Reviewer chấp thuận chưa tự đồng nghĩa task `done`; áp dụng đầy đủ [Definition of Done](../tasks/BACKLOG.md).

2026-10-23 — Đề xuất Hào review [retirement diff](2026-10-23-auth0-retirement.md): single-issuer verifier, cleanup guards/transaction, migration 0008 và session boundaries. Chưa có reviewer signoff.

2026-10-23 — Đề xuất Hào review Compose loopback/profile isolation và native smoke không reset dữ liệu; chưa reviewer signoff. [Evidence](2026-10-23-local-auth-mailpit.md).
