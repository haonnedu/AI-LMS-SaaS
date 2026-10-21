# Eduvia — Đặc tả bộ UI toàn sản phẩm

Trạng thái: bản đặc tả thiết kế; chưa tạo file hoặc màn hình trong Figma.
Ngày: 2026-10-21. Nguồn: README.md, STUDENT_LEARNING.md, SCHOOL_MANAGEMENT.md, EXAM_BLUEPRINTS.md và frontend/src/app/globals.css.

## Định hướng

Thiết kế tiếng Việt cho thị trường Việt Nam. Giữ nhận diện hiện có: xanh #14614E, chữ #263B34, nền #F7F8F5, viền #E4E9E1, bề mặt trắng. Font hiện tại là Segoe UI; kiểm tra font khả dụng trong Figma trước khi chọn font thay thế có đầy đủ dấu tiếng Việt. Cỡ chữ nội dung đề xuất 14–16px; không sao chép các cỡ chữ quá nhỏ của scaffold.

Desktop 1440px, học sinh ưu tiên mobile 390px. Dùng auto-layout, token và component instances; toàn bộ nội dung chính phải là layer chỉnh sửa được. Gắn nhãn riêng Pilot, Mở rộng học sinh, OMR và Nhà trường để prototype không bị hiểu là tính năng đã triển khai.

## Cấu trúc file Figma dự kiến

00 — Bản đồ sản phẩm và hướng dẫn prototype
01 — Foundations: màu, typography, spacing, radius, grid, elevation
02 — Components: navigation, button, input, select, tabs, badge, card, table, dialog, toast, upload, pagination, question, citation, chart legend
03 — Public & Identity
04 — Teacher
05 — Student
06 — School
07 — Platform Admin
08 — Mobile & States

## Danh mục màn hình

| ID | Nhóm | Màn hình và nội dung chính |
|---|---|---|
| P01 | Public | Landing: giá trị sản phẩm, giáo viên/học sinh/nhà trường, cách hoạt động, CTA |
| P02 | Public | Bảng giá: gói cá nhân, trường học, quota AI, so sánh quyền lợi |
| A01 | Identity | Đăng nhập, đăng ký, xác minh email, quên và đặt lại mật khẩu |
| A02 | Identity | Onboarding: vai trò, môn/lớp/bộ sách, tạo hoặc tham gia workspace |
| A03 | Identity | Chấp nhận lời mời, chuyển workspace, lời mời hết hạn |
| T01 | Teacher | Tổng quan: lớp sắp dạy, bài cần duyệt, hạn giao bài, tác vụ nhanh |
| T02 | Teacher | Thư viện: bộ lọc môn/lớp/bộ sách, tài liệu cá nhân và tài liệu được cấp quyền |
| T03 | Teacher | Tải tài liệu: quyền sử dụng, tiến trình xử lý, lỗi, thử lại |
| T04 | Teacher | Chi tiết tài liệu: xem nội dung, metadata, nguồn, quyền chia sẻ |
| T05 | Teacher | Tạo giáo án: chọn nguồn, mục tiêu, thời lượng, phương pháp và mẫu |
| T06 | Teacher | Biên tập giáo án: outline, nội dung, trích nguồn, phiên bản, duyệt và xuất |
| T07 | Teacher | Tạo tài liệu ôn tập: chương, khái niệm, câu luyện tập, đáp án và xuất |
| T08 | Teacher | Trợ lý AI: hội thoại theo nguồn được phép, trích dẫn, không đủ dữ liệu |
| T09 | Teacher | Danh sách lớp, tạo lớp, mã mời và quản lý thành viên |
| T10 | Teacher | Chi tiết lớp: tổng quan, học liệu, bài giao, thành viên, bảng điểm |
| T11 | Teacher | Ngân hàng câu hỏi: chủ đề, loại câu, độ khó, trạng thái duyệt |
| T12 | Teacher | Blueprint đề: phiên bản, ma trận, số câu, điểm, thời gian, nguồn |
| T13 | Teacher | Tạo đề: chọn blueprint, kiểm tra năng lực hỗ trợ, báo thiếu câu |
| T14 | Teacher | Duyệt đề: danh sách câu, đáp án, giải thích, sửa và xuất bản |
| T15 | Teacher | Giao bài: lớp, thời hạn, thời lượng, xem lại và xác nhận giao |
| T16 | Teacher | Bài nộp và kết quả: trạng thái, chi tiết câu trả lời, phản hồi |
| T17 | Teacher | Phân tích lớp: điểm, hoàn thành, chủ đề cần ôn, bằng chứng và gợi ý AI |
| T18 | Teacher / OMR | Tải ảnh phiếu, kiểm tra nhận dạng, sửa ô nghi ngờ, xác nhận điểm |
| T19 | Shared | Hồ sơ, thông báo, bảo mật, gói dịch vụ, quota và thanh toán |
| S01 | Student | Hôm nay: bài đến hạn, buổi học tiếp theo, tiếp tục học |
| S02 | Student | Tham gia lớp bằng mã/link, danh sách và chi tiết lớp |
| S03 | Student | Học liệu và bài học: mục tiêu, nội dung, tài liệu, tiến độ |
| S04 | Student | Trước khi làm bài: hướng dẫn, thời lượng, quy tắc nộp |
| S05 | Student | Làm bài: câu hỏi, chọn đáp án, đánh dấu, điều hướng, lưu trạng thái |
| S06 | Student | Xác nhận nộp, đang gửi, gửi lỗi, biên nhận nộp thành công |
| S07 | Student | Kết quả: điểm, đáp án khi được phép, giải thích, phản hồi |
| S08 | Student expansion | Onboarding tự học: chương trình, tiến độ thực tế, mục tiêu và quỹ thời gian |
| S09 | Student expansion | Chẩn đoán: hướng dẫn, câu hỏi, kết quả có mức độ chắc chắn |
| S10 | Student expansion | Kế hoạch tuần: lịch học, bài ưu tiên, điều chỉnh mục tiêu |
| S11 | Student expansion | Luyện tập theo kỹ năng: gợi ý, giải thích, chuyển bước tiếp theo |
| S12 | Student expansion | Thi thử: blueprint, thời gian, làm bài và báo cáo |
| S13 | Student expansion | Tiến bộ cá nhân: lịch sử, bằng chứng kỹ năng, checkpoint |
| S14 | Student expansion | Gia sư AI theo ngữ cảnh, nguồn và phản hồi chất lượng |
| H01 | School | Tổng quan trường: kỳ học, lớp, giáo viên, việc cần duyệt |
| H02 | School | Thành viên: mời giáo viên, vai trò, trạng thái và quyền |
| H03 | School | Tổ chuyên môn, năm/kỳ học, môn và phân công giảng dạy |
| H04 | School | Giao kế hoạch, theo dõi công việc, nhắc hạn trong sản phẩm |
| H05 | School | Hàng đợi duyệt giáo án/blueprint, nhận xét và lịch sử |
| H06 | School | Kho tài liệu thuộc trường và quyền chia sẻ |
| H07 | School | Báo cáo học thuật theo phạm vi được phép |
| H08 | School | Quota, ngân sách và gói tổ chức |
| H09 | School | Đình chỉ, nghỉ việc, bàn giao có xem trước phạm vi tài sản |
| X01 | Platform admin | Tổng quan vận hành, tình trạng dịch vụ, usage AI |
| X02 | Platform admin | Người dùng, tổ chức, trạng thái và kiểm soát truy cập |
| X03 | Platform admin | Kho kiến thức được cấp phép, nguồn và phiên bản |
| X04 | Platform admin | Gói dịch vụ, hạn mức, thuê bao và giao dịch |
| X05 | Platform admin | Nhật ký thao tác, cấu hình và cảnh báo hệ thống |

## Prototype và trạng thái bắt buộc

1. Giáo viên: đăng nhập → chọn workspace → tải tài liệu → tạo giáo án → kiểm tra nguồn → duyệt → giao cho lớp.
2. Đánh giá: chọn blueprint → tạo đề → xử lý thiếu câu nếu có → duyệt → giao → nhận bài → xem kết quả.
3. Học sinh: nhập mã lớp → xem bài → làm bài → xác nhận nộp → biên nhận → xem phản hồi.
4. Tự học: chọn mục tiêu → chẩn đoán → kế hoạch tuần → luyện tập → checkpoint.
5. Nhà trường: mời giáo viên → phân công → duyệt tài liệu thuộc trường → báo cáo theo quyền.

Mỗi pattern dữ liệu cần thiết kế loading, empty, error/retry và success. Các luồng nhạy với trạng thái cần thêm: mất kết nối khi làm bài, đang lưu/chưa lưu, phiên hết hạn, không có quyền, vượt quota, tài liệu đang xử lý, AI thiếu nguồn, lời mời hết hạn và hành động cần xác nhận.

Pilot chỉ hỗ trợ câu hỏi online một đáp án với chấm điểm xác định. Các dạng câu nâng cao, OMR và tự học thuộc phần mở rộng. Không mô tả offline quiz submission như một năng lực hiện có.

## Nguyên tắc nội dung và quyền

- Phân biệt nội dung AI nháp với nội dung giáo viên đã duyệt; hiển thị nguồn ở nơi ra quyết định.
- Phân biệt kết quả quan sát được với diễn giải AI; trình bày số lượng và độ mới bằng chứng khi nói về kỹ năng.
- Tự học cá nhân không mặc định xuất hiện trong báo cáo lớp/trường.
- Chuyển workspace phải thể hiện rõ ngữ cảnh và chủ sở hữu tài liệu.
- Thi thử giữ nguyên blueprint đã chọn; báo thiếu dữ liệu thay vì âm thầm giảm yêu cầu.
- Dùng dữ liệu minh họa có nhãn trong prototype; không khẳng định chức năng roadmap đã hoạt động.

## Tiêu chí nghiệm thu thiết kế

Mọi màn hình có tên, ID, vai trò và giai đoạn. Navigation nhất quán theo vai trò. Component có trạng thái default, hover/focus, disabled, loading và error khi phù hợp. Input có label và helper/error text. Màu trạng thái đi cùng chữ hoặc icon; kiểm tra contrast và focus. Mobile ưu tiên S01–S07, sau đó T01/T10/T16 và các bước xác thực. Kiểm tra text tiếng Việt không bị cắt và bảng có hành vi responsive rõ ràng.

Trước bàn giao Figma: kiểm tra layer chỉnh sửa được, component instances, font thực tế, overflow, các liên kết prototype và ảnh toàn cảnh từng nhóm. Chỉ ghi hoàn tất sau khi đã có file Figma và kiểm tra trực quan.
