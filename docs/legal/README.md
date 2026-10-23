# Tài liệu pháp lý và quyền riêng tư của Eduvia (DỰ THẢO)

> **Trạng thái: dự thảo.** Tất cả tài liệu trong thư mục này do nhóm kỹ thuật/sản phẩm soạn để luật sư xem xét. **Chúng không phải tư vấn pháp lý và không khẳng định Eduvia tuân thủ bất kỳ quy định nào.** Mọi giả định pháp lý được đánh dấu dạng `[Cần pháp lý xác nhận: ...]`. Các chỗ trống dạng `[...]` là thông tin chưa có (tên pháp nhân, địa chỉ, đầu mối bảo vệ dữ liệu...), không được tự bịa.

Không đưa dữ liệu học sinh thật vào hệ thống trước khi các tài liệu dưới đây được duyệt (xem `tasks/decisions/0008-privacy-consent-retention.md`, mục 0 và mục 6).

## 1. Danh sách tài liệu

| Tài liệu | Đối tượng đọc | Mục đích |
|---|---|---|
| [privacy-notice.md](privacy-notice.md) | Giáo viên, học sinh, phụ huynh | Thông báo xử lý dữ liệu cá nhân đầy đủ |
| [guardian-consent.md](guardian-consent.md) | Cha mẹ/người giám hộ | Phiếu đồng ý: (a) giấy tại trường, (b) nội dung màn hình link |
| [student-notice.md](student-notice.md) | Học sinh (trình độ lớp 9) | Thông báo ngắn khi vào lớp |
| [teacher-terms.md](teacher-terms.md) | Giáo viên | Điều khoản sử dụng, cam kết bản quyền tài liệu tải lên |
| [lawyer-brief.md](lawyer-brief.md) | Luật sư | Tóm tắt sản phẩm, luồng dữ liệu, câu hỏi cần trả lời |

Bản rút gọn dùng trong ứng dụng nằm ở `frontend/src/content/privacy-notice.ts` và `frontend/src/content/consent-text.ts`. Hai tệp này phải được cập nhật cùng lúc với bản markdown (`privacy-notice.md` và `guardian-consent.md` mục B).

## 2. Ai phải duyệt

| Bước | Người duyệt | Ghi chú |
|---|---|---|
| Soát pháp lý | Luật sư độc lập [tên/văn phòng luật] | Trả lời 6 câu hỏi trong `lawyer-brief.md`; sửa các mục `[Cần pháp lý xác nhận]` |
| Duyệt nghiệp vụ | Chủ sản phẩm Eduvia [tên người chịu trách nhiệm] | Xác nhận mô tả đúng hành vi thực tế của sản phẩm |
| Duyệt kỹ thuật | Hao Nguyen và Duc (nhóm kỹ thuật) | Xác nhận các biện pháp bảo mật và thời hạn lưu giữ có thể thực hiện được |
| Duyệt phía nhà trường pilot | Đại diện nhà trường [tên trường, chức danh] | Xác nhận quy trình thu phiếu giấy tại trường |

Người chịu trách nhiệm phê duyệt cuối cùng là [Cần chỉ định: người đại diện pháp luật của pháp nhân vận hành Eduvia].

## 3. Phiên bản và `privacy_policy_version`

Hệ thống ghi mỗi lần đồng ý kèm một chuỗi `privacy_policy_version` (xem migration `backend/migrations/versions/0016_privacy_consent.py`). Chuỗi này chỉ định chính xác văn bản mà người dùng đã thấy.

| Giai đoạn | Định dạng | Ví dụ |
|---|---|---|
| Dự thảo (chưa được luật sư duyệt) | `YYYY-MM-draft` | `2026-10-draft` |
| Sau khi được duyệt | `YYYY-MM-vN` (N tăng dần trong cùng tháng) | `2026-11-v1`, `2026-11-v2` |

Quy tắc:

1. Hằng số `PRIVACY_NOTICE_VERSION` trong `frontend/src/content/privacy-notice.ts` là nguồn duy nhất cho giao diện. Giá trị hiện tại: `2026-10-draft`.
2. Bản `-draft` chỉ dùng cho môi trường phát triển/thử nghiệm nội bộ; **không** dùng để thu đồng ý của học sinh thật. [Cần pháp lý xác nhận: đồng ý ghi theo phiên bản dự thảo có giá trị hay không; đề xuất là không.]
3. Khi nội dung thay đổi về mục đích, bên nhận dữ liệu, thời hạn lưu giữ hoặc quyền, phải tăng phiên bản và yêu cầu xác nhận lại (0008 mục 3, bước 4). Thay đổi chính tả không cần tăng phiên bản nhưng phải ghi vào nhật ký thay đổi.
4. Mỗi phiên bản đã duyệt phải được lưu nguyên văn (tag git `legal-YYYY-MM-vN`) để có thể chứng minh văn bản người dùng từng đồng ý.
5. Phiếu giấy tại trường phải in kèm mã phiên bản ở chân trang để đối chiếu với bản ghi trong hệ thống.

## 4. Nhật ký thay đổi

| Phiên bản | Ngày | Nội dung |
|---|---|---|
| 2026-10-draft | 2026-10-23 | Bản dự thảo đầu tiên, chưa được duyệt |
