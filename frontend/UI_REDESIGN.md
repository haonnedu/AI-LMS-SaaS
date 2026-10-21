# Eduvia — Forest & Lime

Bản thiết kế lại toàn bộ UI, 21/10/2026. Áp dụng UI UX Designer: redesign-makeover, dashboard-saas-ui, design-system-builder, design-to-code. Đây là phiên bản thị giác mới thay cho giao diện xanh nhạt trước đó.

## Thay đổi nhìn thấy ngay

| Trước | Sau | Mục đích |
|---|---|---|
| Sidebar trắng, các mục đều có trọng lượng tương đương | Sidebar xanh rừng `#14382C`, mục chọn lime `#C7EB83` | Tách điều hướng khỏi công việc và tạo nhận diện rõ |
| Banner xanh đậm với tờ giáo án minh họa | Banner lime sáng, typography lớn, hình quỹ đạo và CTA xanh đậm | Thay đổi bố cục và điểm nhấn, làm hành động chính dễ tìm |
| 3 thẻ thống kê tách biệt | Dải 4 chỉ số trên một bề mặt với vạch phân cách | Đọc nhanh lớp, lượt ghi danh, học liệu, bản nháp |
| Dashboard gồm nội dung chào mừng và tài liệu | Công cụ → lịch dạy tương tác → việc cần duyệt → học liệu | Tổ chức theo công việc hàng ngày của giáo viên |
| Các thẻ trắng gần giống nhau | Công cụ lime/peach/lavender; lớp học dùng nền màu rõ, lưới và công thức | Phân biệt loại nội dung ngay khi lướt |
| Menu chiếm nhiều chiều ngang ở tablet | Sidebar dạng icon ở 761–1100px, có tên truy cập và tooltip | Nhường diện tích cho nội dung |

## Phạm vi: 11 màn hình

- `/`: xây lại dashboard bằng component `src/components/dashboard.tsx`. Có chọn ngày 19–25/10, lịch và empty state, liên kết thao tác nhanh, mở chi tiết học liệu.
- `/library`: banner học liệu mới, bộ lọc nền tối, tìm kiếm, bảng phân cấp typography và màu phân loại.
- `/classes`: cover xanh đậm/peach/lavender, công thức, lưới, tiến độ và CTA chi tiết được bố trí lại.
- `/lessons`: stepper, form nền trắng, vùng preview nền xám xanh và trang tài liệu sáng để tạo cảm giác công cụ biên tập.
- `/assessments`: danh sách bài có vạch trạng thái, icon lớn, số bài nộp và CTA; dialog duyệt câu hỏi giữ tương tác.
- `/analytics`: KPI lớn và biểu đồ thanh theo palette mới; vẫn phân biệt dữ liệu quan sát và gợi ý minh họa.
- `/student`: hero lime, tiêu đề lớn, thẻ bài tập rõ hành động; vẫn dùng điều hướng học sinh.
- `/school`: bảng nhân sự và thẻ số liệu theo hệ thống màu mới; dữ liệu minh họa, không gửi lời mời.
- `/admin`: KPI, bảng công việc và trạng thái API theo hệ thống mới.
- `/settings`: form sáng, panel quyền riêng tư xanh đậm, tabs nền đậm.
- `/login`: nhận diện xanh rừng/lime, typography sans lớn, form trắng và vai trò riêng.

Các dialog, trạng thái chọn, thông báo, input, button, table và footer đều nhận theme mới. Tương tác đang có được giữ lại; redesign không chuyển prototype thành backend đã hoạt động.

## Foundations hiện tại

File hiệu lực sau cùng: `src/app/redesign.css`, import sau `globals.css` và `ui-system.css`. Quy tắc trong tài liệu này thay thế các thông số màu/breakpoint cũ ở `UI_UX_DESIGN.md`; các nguyên tắc luồng nghiệp vụ và quyền riêng tư ở tài liệu đó vẫn giữ nguyên.

| Vai trò | Giá trị |
|---|---|
| Forest / Navigation | `#14382C` |
| Primary CTA | `#1D4433` |
| Lime / Selected navigation | `#C7EB83` |
| Hero surface | `#E1EDCA` |
| Canvas | `#F5F6F8` |
| Surface | `#FFFFFF` |
| Text | `#172D27` |
| Secondary text | `#63736D` |
| Peach | `#FAE8D9` |
| Lavender | `#ECE9F9` |

Font hệ thống Segoe UI hỗ trợ tiếng Việt, không tải font ngoài. Tiêu đề trang 28–42px, hero 37–57px, heading khối 18–20px, nội dung 13–15px và metadata 10–12px. Khoảng cách chính 8/16/24/32/40px; radius control 8px, panel 16px, hero 20px.

## Responsive và khả năng truy cập

- Desktop trên 1100px: sidebar 248px có nhãn. Dashboard lịch/công việc hai cột khi đủ diện tích.
- 761–1100px: sidebar 88px dạng icon, có `aria-label` và `title`. Bộ chọn vai trò mở thành panel có nhãn đầy đủ; lịch/công việc xếp dọc.
- Tối đa 760px: sidebar đóng mặc định, mở bằng menu; focus loop và Escape được giữ lại.
- Tối đa 520px: chỉ số 2x2; CTA header thu gọn; lịch và bảng có vùng cuộn riêng; form xếp dọc.
- Nút và liên kết chính tối thiểu 44px. Không đưa chart trang trí vào cây truy cập như dữ liệu thực.
- Số 112 là lượt ghi danh, không khẳng định số học sinh duy nhất. Vạch trang trí trong KPI không có trục thời gian và không phải xu hướng đã đo.
- Native dialog vẫn giữ focus, Escape và khôi phục focus; học sinh không nhận các tab công cụ giáo viên.

## Phạm vi vận hành

Đây là prototype UI dùng dữ liệu minh họa. Auth, RAG, lưu trữ, publication, assignment, submission, billing và phân quyền thật chưa được kết nối. Nội dung thêm trong phiên đặt lại khi tải trang. API health là kiểm tra thực tế, không suy diễn thành đăng nhập hoặc cơ sở dữ liệu sẵn sàng.

Kiểm tra khi bàn giao: lint, TypeScript, production build; kiểm tra trực quan dashboard và các trang đại diện, kiểm tra chọn ngày và chi tiết học liệu. Các kiểm tra trên không thay thế kiểm thử usability hoặc chứng nhận WCAG toàn diện.
