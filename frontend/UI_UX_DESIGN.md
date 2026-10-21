# Eduvia — UI/UX design and handoff

> Bản thị giác mới nhất: [Forest & Lime](UI_REDESIGN.md). Tài liệu đó thay thế palette, dashboard và breakpoint thị giác cũ bên dưới; các giới hạn nghiệp vụ vẫn áp dụng.

Ngày: 21/10/2026. Phương pháp: UI UX Designer — ui-ux-designer, dashboard-saas-ui, design-system-builder và design-to-code.

## Mục tiêu và giả định

Eduvia là web app giảng dạy cho thị trường Việt Nam. Người dùng chính của pilot là giáo viên: chuẩn bị học liệu, soạn bài có nguồn, duyệt nội dung rồi giao bài và đọc kết quả. Học sinh cần tìm bài đến hạn, làm bài và hiểu phản hồi. Nhà trường và quản trị nền tảng là không gian mở rộng.

Các nhu cầu trên được suy ra từ tài liệu dự án, chưa phải kết quả phỏng vấn người dùng. Thiết kế giữ thương hiệu xanh hiện có và dùng Segoe UI để hỗ trợ tiếng Việt, không phụ thuộc tải font ngoài.

## Cấu trúc và phạm vi

| Màn hình | Tuyến | Tác vụ chính | Trạng thái bản mẫu |
|---|---|---|---|
| Tổng quan giáo viên | `/` | Xác định việc cần làm, bắt đầu soạn bài | Lịch tuần, thao tác nhanh, KPI và học liệu mẫu |
| Thư viện | `/library` | Tìm, phân loại và mở học liệu | Tìm kiếm, lọc, sắp xếp tên, không kết quả, thêm metadata mẫu |
| Soạn bài AI | `/lessons` | Nhập nguồn/mục tiêu, xem nháp, duyệt | Form, chỉ dẫn 3 bước, nội dung cố định, tải TXT mẫu |
| Lớp học | `/classes` | Tổ chức lớp và xem tiến độ | Lưới/danh sách, tạo lớp phiên xem, chi tiết tổng quan/học liệu/thành viên |
| Bài tập và kiểm tra | `/assessments` | Lọc trạng thái, kiểm tra câu hỏi | Chi tiết tổng quan/câu hỏi/bài nộp, đánh dấu xem câu mẫu |
| Kết quả | `/analytics` | Nhận biết tiến độ và chủ đề cần ôn | Biểu đồ phân bố điểm, số bài nộp và mẫu số rõ ràng |
| Học sinh | `/student` | Mở bài cần làm và kiểm tra đáp án | Một câu hỏi mẫu có lựa chọn và phản hồi |
| Nhà trường | `/school` | Theo dõi đội ngũ và phân công | Bảng minh họa; lời mời chưa được gửi |
| Quản trị | `/admin` | Theo dõi vận hành | KPI giả lập; kiểm tra kết nối API là yêu cầu thực tế |
| Cài đặt | `/settings` | Điều chỉnh hồ sơ và tùy chọn | Hồ sơ, không gian, checkbox thông báo, kết nối |
| Đăng nhập | `/login` | Hiểu vai trò và vào bản mẫu | Form minh họa, không xác thực hay gửi mật khẩu |

Sidebar hiển thị điều hướng giáo viên hoặc không gian tương ứng với vai trò đang xem. Mục “Xem giao diện vai trò khác” là công cụ khám phá prototype, không phải cơ chế đổi quyền tài khoản. Khi triển khai thật, quyền phải được xác thực ở backend.

## Luồng chính

1. Giáo viên: tổng quan → thư viện → tìm/lọc → chi tiết học liệu → soạn bài → xem nháp → kiểm tra → tải mẫu. Việc xuất bản/giao bài chưa được kết nối.
2. Quản lý lớp: danh sách lớp → tổng quan lớp → học liệu/thành viên → bài tập & kiểm tra.
3. Đánh giá: danh sách bài → lọc nháp → tổng quan bài → câu hỏi → đáp án/giải thích → đánh dấu đã xem mẫu. Bài nộp chưa có kết nối nên hiển thị empty state.
4. Học sinh: góc học tập → làm thử một câu → chọn đáp án → kiểm tra → phản hồi. Không có đồng hồ hoặc điểm số giả lập gây hiểu nhầm đây là kỳ thi thật.

## Hệ thống thị giác

Nguồn token và quy tắc giao diện: `src/app/ui-system.css`. Giao diện nền được giữ trong `globals.css`; lớp hệ thống mới được import sau để có thể rà soát thay đổi độc lập.

| Token | Giá trị | Sử dụng |
|---|---|---|
| `--color-bg-canvas` | `#F7F8F5` | Nền không gian |
| `--color-bg-surface` | `#FFFFFF` | Form, bảng, dialog |
| `--color-text-primary` | `#263B34` | Tiêu đề, nội dung chính |
| `--color-text-secondary` | `#5E7064` | Nội dung hỗ trợ |
| `--color-brand-primary` | `#14614E` | CTA chính, trạng thái chọn |
| `--color-success-text` | `#356348` | Trạng thái thành công |
| `--color-warning-text` | `#805F20` | Cần duyệt, chưa nộp |
| `--color-info-text` | `#426382` | Trạng thái thông tin |
| `--color-error-text` | `#9C3838` | Lỗi nhập liệu khi kết nối |

Typography: tiêu đề trang 27–36px; tiêu đề khối 16–18px; nội dung chính 14–15px; metadata 12–13px; nhãn nhóm/badge 10–11px. Phần chữ trong minh họa trang trí có thể nhỏ hơn vì không chứa thông tin cần thao tác.

Spacing theo thang 4/8px: 4, 8, 12, 16, 24, 32, 48. Control radius 8px; card radius 16px. Chỉ dùng shadow nhẹ cho overlay và thông báo, tránh biến mọi khối thành điểm nhấn cạnh tranh.

## Component và trạng thái

| Component | Quy tắc |
|---|---|
| Button | CTA chính xanh, phụ nền trắng có viền; vùng bấm 44px; hover, focus, disabled rõ |
| Bộ lọc | Nhãn đọc được; `aria-pressed` thể hiện lựa chọn; nút xóa bộ lọc khi không có kết quả |
| Bảng | Tiêu đề cột có ngữ nghĩa; sắp xếp tên có `aria-sort`; tiêu đề sticky trong vùng cuộn; cuộn ngang thay vì tràn trang |
| Dialog chi tiết | Native `dialog` để khóa focus/nội dung nền; có tên, nút đóng, phím Escape và trả focus |
| Modal tạo mẫu | Nhãn input, thông báo giới hạn phiên xem, focus loop và Escape |
| Navigation mobile | Menu đóng mặc định, có `aria-expanded`, focus loop, Escape và lớp nền đóng menu |
| Biểu đồ | Có mô tả văn bản; luôn kèm số bài và phạm vi dữ liệu; màu không là tín hiệu duy nhất |
| Thông báo | Dùng `role=status`, nút đóng rõ; phân biệt thay đổi trong phiên và lưu máy chủ |
| Kết nối | Có checking, online, offline, retry; không suy diễn API online thành DB/account sẵn sàng |

## Responsive

- Từ 1440px: nội dung dashboard và cột lịch 320px; sidebar 264px.
- Dưới 1440px: nội dung chính một cột; lịch/công việc có thể dùng hai cột khi đủ chỗ.
- Dưới 900px: thao tác nhanh chuyển thành danh sách; lịch/công việc xếp dọc.
- Từ 760px trở xuống: sidebar thành menu trượt; card lớp xếp dọc; không dùng menu giáo viên trong vai trò học sinh.
- Từ 520px trở xuống: KPI xếp thành hàng dọc có giá trị canh phải; form và nút tài liệu ưu tiên chiều rộng đầy đủ; dialog cuộn trong viewport.
- Dải ngày có vùng cuộn riêng khi không đủ 7 mục x 44px; bảng cũng có vùng cuộn riêng.

## Những quyết định UX quan trọng

- Giảm chữ quảng bá trong sidebar để nhường chỗ cho điều hướng.
- Dashboard nói rõ 2 tiết dạy và 1 bản nháp cần xem, thay cho lời chào chung chung.
- Số 112 được gọi là lượt ghi danh, không khẳng định là 112 học sinh duy nhất giữa các lớp.
- 4 học liệu trên dashboard khớp bộ dữ liệu thư viện mẫu.
- Chi tiết lớp/bài kiểm tra dùng màn hình có cấu trúc thay vì thông báo một dòng.
- Nháp AI, nguồn chưa xác minh và giai đoạn mở rộng có nhãn rõ ràng.
- Footer tài trợ của plugin chỉ thuộc câu trả lời trong chat; không đưa vào sản phẩm Eduvia.

## Kiểm tra và bước triển khai tiếp

Đã chạy ESLint và TypeScript sau khi thay đổi; kiểm tra trực tiếp luồng chi tiết lớp và tab thành viên trên trình duyệt. Build production và các kiểm tra tương tác khác được ghi nhận trong bàn giao chat khi hoàn tất. Không coi đây là chứng nhận WCAG toàn diện hoặc nghiên cứu usability đã hoàn thành.

Trước pilot: kiểm tra viewport 390/768/1440px, phóng to 200%, trình đọc màn hình và bàn phím; phỏng vấn 3–5 giáo viên bằng tác vụ tìm tài liệu → tạo nháp → xem lớp → duyệt câu hỏi. Theo dõi tỷ lệ hoàn thành, số lần quay lại và điểm nhầm lẫn; chưa có số liệu nghiên cứu để công bố.

Các luồng tài khoản thực, RAG có nguồn, xuất bản, giao/nộp bài, lưu tùy chọn, mời thành viên, phân quyền, billing, OMR và tự học nâng cao vẫn thuộc triển khai tiếp. Tất cả dữ liệu prototype đặt lại khi tải trang; không diễn giải thao tác UI thành tác vụ backend thành công.
