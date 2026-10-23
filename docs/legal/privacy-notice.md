# Thông báo xử lý dữ liệu cá nhân của Eduvia

> **DỰ THẢO — phiên bản `2026-10-draft` — chưa được luật sư duyệt, chưa có hiệu lực.** Văn bản này mô tả cách Eduvia dự kiến xử lý dữ liệu, không khẳng định đã tuân thủ pháp luật. [Cần pháp lý xác nhận: đối chiếu Nghị định 13/2023/NĐ-CP và Luật Bảo vệ dữ liệu cá nhân 2025 (hiệu lực từ 2026-01-01); xác định văn bản nào áp dụng và ngày chuyển tiếp.]

## 1. Ai chịu trách nhiệm về dữ liệu của bạn

- Bên kiểm soát dữ liệu: [tên pháp nhân vận hành Eduvia], mã số doanh nghiệp [...], địa chỉ [...].
- Đầu mối bảo vệ dữ liệu: [họ tên / bộ phận bảo vệ dữ liệu cá nhân — chưa chỉ định], email [...].
- Trường tham gia pilot: [tên trường]. [Cần pháp lý xác nhận: nhà trường là đồng kiểm soát, bên kiểm soát riêng, hay bên xử lý thay cho Eduvia; cần ký thỏa thuận nào giữa trường và Eduvia.]

## 2. Eduvia là gì

Eduvia là hệ thống hỗ trợ dạy và học cho trường trung học. Giáo viên tải tài liệu của mình lên, dùng AI để soạn nháp bài giảng và đề kiểm tra, rồi giao bài trắc nghiệm một đáp án đúng cho lớp. Học sinh vào lớp bằng đường link mời của giáo viên và làm bài trên hệ thống. Việc chấm điểm bài trắc nghiệm do hệ thống tính theo đáp án, **không dùng AI**.

## 3. Dữ liệu chúng tôi thu thập

| Đối tượng | Dữ liệu | Nguồn |
|---|---|---|
| Giáo viên | Email, tên hiển thị, thông tin đăng nhập (mật khẩu được lưu dưới dạng băm, hoặc liên kết với tài khoản Google) | Giáo viên nhập khi đăng ký |
| Giáo viên | Tài liệu tải lên, nội dung bài giảng/đề/câu hỏi do giáo viên soạn, thông số yêu cầu AI, lịch sử thao tác duyệt | Giáo viên tạo ra |
| Giáo viên | Tên lớp, danh sách lớp, kết quả của học sinh trong lớp mình dạy | Hệ thống tạo ra khi học sinh làm bài |
| Học sinh | Email, tên hiển thị, thông tin đăng nhập (email và mật khẩu, hoặc tài khoản Google) | Học sinh nhập khi tạo tài khoản |
| Học sinh | Năm sinh (nếu được yêu cầu) | Học sinh/gia đình khai khi vào lớp [Cần pháp lý xác nhận: có được thu năm sinh hay chỉ cờ "dưới tuổi quy định"] |
| Học sinh | Lớp đã tham gia, mã học sinh do trường cấp (nếu có), thời điểm vào/rút khỏi lớp | Link mời và giáo viên |
| Học sinh | Bài làm: câu trả lời đã chọn, thời điểm bắt đầu/nộp, điểm từng câu, điểm tổng | Học sinh làm bài; hệ thống chấm |
| Học sinh/phụ huynh | Bản ghi đồng ý của phụ huynh/người giám hộ: ai xác nhận, cách thức (giấy tại trường, link, tự đồng ý khi đủ tuổi), thời điểm, phiên bản văn bản | Trường, phụ huynh hoặc học sinh |
| Mọi người dùng | Phiên đăng nhập (lưu tạm trong Redis, mã hóa), nhật ký kỹ thuật (mã yêu cầu, mã lỗi; không ghi nội dung bài làm, email hay mã đăng nhập) | Hệ thống |

Chúng tôi **không** thu thập: số căn cước/định danh nhà nước, số điện thoại hay địa chỉ của học sinh, ảnh chụp giấy đồng ý, vị trí, dữ liệu sinh trắc học.

## 4. Mục đích sử dụng

1. **Học tập**: cho học sinh xem bài được giao và làm bài.
2. **Chấm điểm**: tính điểm bài trắc nghiệm theo đáp án giáo viên đã duyệt; giáo viên có thể điều chỉnh có ghi lý do.
3. **Theo dõi tiến bộ**: giáo viên xem kết quả của lớp; học sinh xem kết quả của chính mình sau khi giáo viên công bố.
4. **Vận hành dịch vụ**: đăng nhập, xử lý tác vụ nền, hỗ trợ kỹ thuật, tính mức sử dụng.
5. **Bảo mật**: phát hiện truy cập bất thường, chống gian lận bài làm, ngăn rò rỉ dữ liệu giữa các lớp/giáo viên.
6. Với giáo viên: **soạn nháp bằng AI** từ tài liệu giáo viên tải lên.

Chúng tôi không bán dữ liệu, không dùng dữ liệu cho quảng cáo, và không dùng tài liệu hay bài làm để huấn luyện mô hình AI theo mặc định. [Cần pháp lý xác nhận: cam kết này phải khớp hợp đồng với nhà cung cấp AI.]

## 5. Căn cứ pháp lý

| Đối tượng / hoạt động | Căn cứ dự kiến |
|---|---|
| Giáo viên (tài khoản, tài liệu, AI) | Sự đồng ý khi chấp nhận Điều khoản sử dụng và thông báo này; thực hiện hợp đồng dịch vụ. [Cần pháp lý xác nhận] |
| Học sinh từ đủ [16] tuổi | Sự đồng ý của chính học sinh. [Cần pháp lý xác nhận: ngưỡng 16 hay 18.] |
| Học sinh dưới [16] tuổi | Sự đồng ý của cha mẹ/người giám hộ, kèm sự đồng ý của học sinh từ đủ 7 tuổi nếu luật yêu cầu. [Cần pháp lý xác nhận: ngưỡng tuổi, và việc phiếu giấy do trường thu có đủ làm bằng chứng đồng ý không.] |
| Bảo mật, chống lạm dụng, nhật ký | Lợi ích chính đáng/nghĩa vụ bảo vệ hệ thống. [Cần pháp lý xác nhận: pháp luật có thừa nhận căn cứ này không, hay mọi xử lý đều cần đồng ý.] |

## 6. Chia sẻ dữ liệu với bên thứ ba

Chúng tôi chỉ chia sẻ dữ liệu ở mức cần thiết với các bên xử lý sau (tên cụ thể sẽ điền khi đã ký hợp đồng):

| Bên nhận | Mục đích | Dữ liệu gửi | Dữ liệu KHÔNG gửi | Vị trí |
|---|---|---|---|---|
| Nhà cung cấp lưu trữ/máy chủ [tên, quốc gia] | Chạy ứng dụng, cơ sở dữ liệu PostgreSQL, Redis, lưu tệp | Toàn bộ dữ liệu trong hệ thống (mã hóa khi lưu theo cấu hình [...]) | — | [vùng: ...] |
| Nhà cung cấp email [tên, quốc gia] | Gửi email xác minh, đặt lại mật khẩu | Địa chỉ email, nội dung email hệ thống | Bài làm, điểm | [...] |
| Nhà cung cấp mô hình ngôn ngữ (LLM) [tên, quốc gia] | Soạn nháp bài giảng/đề từ tài liệu của giáo viên | **Chỉ** đoạn văn bản trích từ tài liệu giáo viên tải lên, thông số yêu cầu của giáo viên | Tên học sinh, mã học sinh, email, câu trả lời, điểm, tên tệp, đáp án đúng | [có thể ở nước ngoài] |
| Nhà cung cấp embedding [tên, quốc gia] | Tạo vector tìm kiếm cho tài liệu | **Chỉ** đoạn văn bản của tài liệu giáo viên, câu truy vấn của giáo viên | Như trên | [có thể ở nước ngoài] |
| Google (nếu chọn đăng nhập Google) | Xác thực | Email, tên theo tài khoản Google | Dữ liệu học tập | Theo Google |

**Chuyển dữ liệu ra nước ngoài.** Văn bản giáo viên tải lên có thể được gửi tới nhà cung cấp LLM/embedding đặt ở nước ngoài. Dữ liệu của học sinh (tên, mã, bài làm, điểm) không được gửi cho các nhà cung cấp này. Vì vậy giáo viên **không được** đưa dữ liệu cá nhân của học sinh vào tài liệu tải lên (xem Điều khoản giáo viên). Hệ thống không tự động quét để phát hiện dữ liệu như vậy. [Cần pháp lý xác nhận: nghĩa vụ lập hồ sơ đánh giá tác động chuyển dữ liệu ra nước ngoài và đánh giá tác động xử lý dữ liệu; thời điểm nộp hồ sơ; có cần ngừng gửi cho đến khi hồ sơ được lập hay không.]

Chúng tôi chỉ tiết lộ dữ liệu cho cơ quan nhà nước khi pháp luật yêu cầu. [Cần pháp lý xác nhận]

## 7. Thời gian lưu giữ

**Các thời hạn dưới đây là đề xuất đang chờ duyệt, chưa phải chính sách đang áp dụng. Hiện hệ thống chưa tự động xóa dữ liệu.** [Cần pháp lý xác nhận: từng thời hạn.]

| Dữ liệu | Đề xuất |
|---|---|
| Tài khoản (email, tên) | Đến khi tài khoản bị xóa, cộng 30 ngày |
| Hồ sơ học sinh, bài làm, điểm | Hết năm học, cộng 1 năm; hoặc đến khi có yêu cầu xóa hợp lệ |
| Lớp học, bài giao | Hết năm học, cộng 1 năm |
| Tài liệu giáo viên tải lên | Đến khi giáo viên xóa (xóa sẽ kéo theo xóa đoạn trích, vector và tệp gốc) |
| Yêu cầu và kết quả sinh nháp AI | 1 năm |
| Tác vụ nền đã xong | 90 ngày |
| Lời mời vào lớp | 30 ngày sau khi hết hạn |
| Tệp xuất | 30 ngày |
| Nhật ký chuyển đổi tài khoản | 1 năm |
| Số liệu mức sử dụng (không chứa dữ liệu cá nhân) | 2 năm |
| Phiên đăng nhập | Tối đa 24 giờ; hết hạn sau 2 giờ không hoạt động |
| Bản sao lưu | [Chưa có chính sách; cần chốt thời hạn hết hạn sao lưu] |

## 8. Quyền của bạn

Bạn có quyền: **truy cập** và nhận bản sao dữ liệu; **chỉnh sửa**; **xóa**; **rút lại đồng ý**; hạn chế hoặc phản đối xử lý [Cần pháp lý xác nhận: phạm vi các quyền theo luật]; và **khiếu nại** tới chúng tôi, hoặc tới cơ quan có thẩm quyền [Cần pháp lý xác nhận: tên cơ quan tiếp nhận khiếu nại] hoặc khởi kiện theo quy định.

Cách thực hiện trong ứng dụng:

- **Học sinh**: vào trang `/student/privacy` để tải bản xuất dữ liệu của mình, gửi yêu cầu xóa, và xem trạng thái đồng ý. Phụ huynh/người giám hộ có thể gửi yêu cầu qua nhà trường hoặc email ở mục 12.
- **Giáo viên**: trong danh sách lớp, giáo viên có thao tác xuất dữ liệu của học sinh, rút học sinh khỏi lớp và gửi yêu cầu xóa/ẩn danh hóa học sinh khi có đề nghị. Giáo viên xóa tài liệu ngay trong thư viện; tài khoản giáo viên xóa qua email ở mục 12.
- **Rút lại đồng ý**: học sinh bị rút khỏi lớp ngay, sau đó dữ liệu được xóa hoặc ẩn danh hóa theo mục 9.

Chúng tôi sẽ trả lời yêu cầu trong [số ngày — Cần pháp lý xác nhận: thời hạn luật định, ví dụ 72 giờ hay 15 ngày].

**Xóa nghĩa là gì.** Với học sinh, "xóa" được thực hiện bằng ẩn danh hóa (pseudonymisation): tên, email, mã học sinh được thay bằng nhãn chung ("Học sinh đã xóa") và gỡ liên kết với tài khoản. Điểm có thể được giữ ở dạng không gắn với danh tính để thống kê lớp. [Cần pháp lý xác nhận: dữ liệu ẩn danh hóa kiểu này còn là dữ liệu cá nhân không; khi nào phải xóa hẳn bài làm và điểm.] Bản sao lưu cũ có thể còn dữ liệu đã xóa đến khi hết hạn; khi khôi phục từ sao lưu, các yêu cầu xóa sẽ được áp dụng lại.

## 9. Dữ liệu của trẻ em và học sinh dưới tuổi quy định

- Học sinh dưới [16] tuổi chỉ được dùng Eduvia khi có sự đồng ý của cha mẹ/người giám hộ. [Cần pháp lý xác nhận: ngưỡng tuổi.]
- Cách ghi nhận đồng ý: (a) phiếu giấy do nhà trường thu và giáo viên/nhà trường xác nhận trong hệ thống; (b) phụ huynh bấm đồng ý qua đường link; (c) học sinh đủ tuổi tự đồng ý. Hệ thống lưu: ai xác nhận, cách thức, thời điểm, phiên bản văn bản. Hệ thống **không lưu** ảnh phiếu, số điện thoại hay tên phụ huynh. [Cần pháp lý xác nhận: phương án (a) có đủ chứng cứ đồng ý không.]
- Chưa có đồng ý hợp lệ thì học sinh không thấy bài giao và không làm bài được.
- Chúng tôi chỉ thu dữ liệu tối thiểu cần để học và chấm điểm, không dùng dữ liệu trẻ em để quảng cáo hay lập hồ sơ thương mại.
- Phụ huynh có thể rút đồng ý bất kỳ lúc nào (xem `guardian-consent.md`).
- Dữ liệu của học sinh không bao giờ được gửi cho nhà cung cấp AI.

## 10. Biện pháp bảo mật

- Phân tách dữ liệu theo từng không gian làm việc bằng chính sách bảo vệ cấp hàng của cơ sở dữ liệu (row-level security); học sinh chỉ đọc được dữ liệu của chính mình qua các hàm chuyên dụng.
- Đáp án đúng chỉ nằm ở máy chủ, không gửi xuống trình duyệt của học sinh.
- Mã hóa khi truyền (TLS) và mã hóa khi lưu [cấu hình mã hóa đĩa/đối tượng — cần điền sau khi chọn nhà cung cấp]; phiên đăng nhập được mã hóa; mật khẩu lưu dạng băm.
- Phân quyền theo vai trò; quyền tối thiểu cho tài khoản dịch vụ; nhật ký kỹ thuật che email, mã đăng nhập và đường dẫn nhạy cảm.
- Quy trình khi có sự cố rò rỉ: [quy trình và thời hạn thông báo — Cần pháp lý xác nhận].
- Sao lưu và khôi phục: [chưa có sao lưu tự động; cần hoàn tất trước khi nhận dữ liệu thật].

Không biện pháp nào bảo đảm an toàn tuyệt đối.

## 11. Thay đổi thông báo

Khi thay đổi nội dung quan trọng, chúng tôi tăng số phiên bản và yêu cầu bạn (hoặc phụ huynh) xác nhận lại.

| Phiên bản | Ngày | Thay đổi |
|---|---|---|
| 2026-10-draft | 2026-10-23 | Bản dự thảo đầu tiên |

## 12. Liên hệ

Email: [email bảo vệ dữ liệu] — Điện thoại: [...] — Địa chỉ: [...] — Đầu mối: [họ tên, chức danh].
