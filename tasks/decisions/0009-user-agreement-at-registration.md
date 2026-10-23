# 0009 — Chấp nhận Thỏa thuận người dùng khi đăng ký là căn cứ cho mọi vai trò

> Ngày: 2026-10-23. Trạng thái: **Đã quyết định (owner), chờ đính kèm xác nhận bằng văn bản của luật sư.**
> Người quyết định: chủ sản phẩm Eduvia, dựa trên kết luận của luật sư do owner chuyển lại.
> Liên quan: [0008 — Quyền riêng tư, đồng ý của người giám hộ và lưu giữ dữ liệu](0008-privacy-consent-retention.md), [`docs/legal/README.md`](../../docs/legal/README.md).

## 1. Bối cảnh

- Quyết định 0008 (PILOT-05) đề xuất một luồng đồng ý của cha mẹ/người giám hộ cho học sinh dưới tuổi quy định. Migration `0016_privacy_consent` đã xây xong luồng đó: học sinh tự khai năm sinh (`edu.student_set_birth_year`), giáo viên/nhà trường ghi nhận phiếu giấy hoặc gửi liên kết một lần cho phụ huynh, và `edu.student_start_attempt` chặn bắt đầu làm bài (EV017) khi chưa có đồng ý.
- Luồng này làm tăng ma sát cho học sinh và giáo viên (khai năm sinh, thu phiếu, chờ phụ huynh) và chưa có câu trả lời pháp lý về việc nó có bắt buộc hay không.
- Owner đã hỏi luật sư. Văn bản này ghi lại kết luận đó, **không** tranh luận lại nội dung pháp lý.

## 2. Kết luận của luật sư (do owner chuyển lại)

- Luật sư: [Tên luật sư/đơn vị].
- Ngày trả lời: [Ngày].
- Tham chiếu: [Tham chiếu email/văn bản].
- Nội dung, theo owner chuyển lại: việc người dùng **chấp nhận Thỏa thuận người dùng và Thông báo quyền riêng tư tại bước đăng ký tài khoản** là đủ cho mọi người dùng, **kể cả học sinh**; **không bắt buộc** thu đồng ý của cha mẹ/người giám hộ.

Nhóm kỹ thuật không tự đánh giá kết luận trên. Mọi câu hỏi về phạm vi áp dụng (ví dụ học sinh rất nhỏ tuổi, trường yêu cầu riêng) do owner trao đổi lại với luật sư.

## 3. Quyết định

1. **Căn cứ cho mọi vai trò** (giáo viên, học sinh, quản trị trường): người dùng chấp nhận `Thỏa thuận người dùng` + `Thông báo quyền riêng tư` khi đăng ký. Không có tài khoản nào được dùng sản phẩm (tạo/mở workspace cá nhân qua `POST /v1/auth/bootstrap`) trước khi đã chấp nhận đúng phiên bản hiện hành.
2. **Hai bước trong giao diện**:
   - Form đăng ký email/mật khẩu có ô bắt buộc "Tôi đã đọc và đồng ý với Thỏa thuận người dùng và Thông báo quyền riêng tư" (liên kết tới `/terms` và `/privacy`); nút gửi bị khóa khi chưa đánh dấu.
   - Vì người dùng chưa đăng nhập ngay sau khi đăng ký (phải xác minh email), việc **ghi nhận** chấp nhận diễn ra ở bước xác thực đầu tiên: màn hình onboarding gọi `GET /v1/auth/agreements`; nếu chưa chấp nhận phiên bản hiện hành thì hiển thị lại ô đồng ý và gửi `POST /v1/auth/agreements`, sau đó mới gọi bootstrap. Người dùng đăng nhập bằng Google cũng đi qua bước này.
3. **Đồng ý của người giám hộ trở thành tùy chọn và tắt mặc định.** Toàn bộ cơ chế của migration 0016 được giữ nguyên trong code. Cấu hình `PRIVACY_CONSENT_MODE`:
   - `signup` (mặc định): không chặn bắt đầu làm bài, không hỏi năm sinh, không hiển thị thẻ "Cần sự đồng ý của phụ huynh".
   - `guardian`: hành vi của 0016 (hỏi năm sinh, chặn EV017 với học sinh dưới `PRIVACY_CONSENT_AGE` chưa có đồng ý). Dùng khi một trường yêu cầu.
4. Phiên bản văn bản được cấu hình ở backend: `TERMS_VERSION` (Thỏa thuận người dùng) và `PRIVACY_POLICY_VERSION` (Thông báo quyền riêng tư); giao diện dùng hằng số `USER_AGREEMENT_VERSION` và `PRIVACY_NOTICE_VERSION` nhưng **luôn gửi phiên bản mà backend trả về** khi ghi nhận. Khi văn bản đã được luật sư duyệt thay thế bản dự thảo, hai biến phải được tăng **cùng lúc** (xem `docs/legal/README.md` mục 3).

## 4. Những gì được ghi nhận cho mỗi lần chấp nhận

Bảng `edu.user_agreements` (migration `0017_terms_acceptance`), mỗi văn bản một dòng:

| Trường | Ý nghĩa |
|---|---|
| `user_id` | Người chấp nhận (`edu.actor_id()` — định danh đã xác minh, không lấy từ body) |
| `document` | `user_agreement` hoặc `privacy_notice` |
| `version` | Phiên bản văn bản đã hiển thị (ví dụ `2026-10-draft`) |
| `accepted_at` | Thời điểm ghi nhận (giờ máy chủ cơ sở dữ liệu) |
| `method` | `signup` (lần đầu) hoặc `reaccept` (chấp nhận lại khi phiên bản tăng) |
| `client_hash` | Tùy chọn: sha256 của User-Agent trình duyệt. **Không lưu địa chỉ IP.** |

Bản ghi là append-only (runtime chỉ có SELECT/INSERT, FORCE RLS theo `user_id = edu.actor_id()`), duy nhất theo `(user_id, document, version)` nên ghi lại cùng phiên bản là idempotent. Mỗi lần ghi nhận có một dòng audit `auth.agreements_accepted` (chỉ chứa ID và phiên bản).

## 5. Hệ quả

- Học sinh có thể làm bài ngay sau khi tham gia lớp; giáo viên không phải thu phiếu đồng ý trong chế độ mặc định.
- Dữ liệu `birth_year`/`consent_status`/`student_consents` hiện có vẫn được giữ và vẫn xóa được qua `edu.erase_student`/`edu.erase_self`. Danh sách đồng ý của lớp (`GET .../classes/{id}/consents`) vẫn hoạt động ở cả hai chế độ và trả thêm `mode`.
- Bật lại chế độ `guardian` cho một trường không cần migration: học sinh đã khai năm sinh vẫn được đánh giá theo năm sinh, học sinh chưa khai sẽ được hỏi.
- Mọi người dùng đã có tài khoản trước thay đổi này sẽ được yêu cầu chấp nhận ở lần mở onboarding kế tiếp (bootstrap trả 409 `agreement_required`).
- Rủi ro còn lại: căn cứ pháp lý phụ thuộc hoàn toàn vào kết luận của luật sư ở mục 2; nếu kết luận thay đổi, chỉ cần đổi `PRIVACY_CONSENT_MODE=guardian`.

## 6. Việc còn mở

| # | Việc | Owner |
|---|---|---|
| 1 | **Đính kèm xác nhận bằng văn bản của luật sư** (email hoặc văn bản có chữ ký) vào hồ sơ dự án và điền các chỗ trống ở mục 2 **trước khi pilot** | Owner |
| 2 | Luật sư duyệt nội dung `Thỏa thuận người dùng` (`frontend/src/content/user-agreement.ts`, dựng từ `docs/legal/teacher-terms.md`) và `Thông báo quyền riêng tư`; sau đó tăng `TERMS_VERSION`/`PRIVACY_POLICY_VERSION` cùng lúc | Owner + luật sư |
| 3 | Xác nhận với trường pilot là họ không yêu cầu đồng ý của phụ huynh; nếu có, bật `PRIVACY_CONSENT_MODE=guardian` | Owner |
