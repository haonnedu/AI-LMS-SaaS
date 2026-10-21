# Đặc tả phạm vi Pilot & Định nghĩa thành công (Task SCOPE-01)

> Ngày: 2026-10-21. Trạng thái: Đề xuất đặc tả nghiệp vụ.

## 1. Phạm vi Pilot ban đầu (Initial Pilot Scope)
Theo kế hoạch triển khai của Eduvia ([IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md)), giai đoạn pilot đầu tiên tập trung vào:
- **Quy mô giáo viên:** 10–20 giáo viên trong một cơ sở giáo dục hoặc nhóm chuyên môn thử nghiệm.
- **Cấp học / Khớp chương trình:** Chọn 1 cấp học cụ thể (ví dụ: THPT) và 1–2 môn học chủ lực (ví dụ: Toán hoặc Ngữ văn/Tiếng Anh).
- **Mục tiêu đầu ra của Pilot:** Giáo viên sử dụng hệ thống để soạn thảo học liệu hỗ trợ AI, review, tạo đề trắc nghiệm chuẩn cấu trúc blueprint, giao bài online đơn giản và thu thập kết quả, đánh giá học sinh.

---

## 2. Tiêu chí Thành công & Thất bại (Success & Failure Criteria)

### A. Tiêu chí Thành công (Success Criteria)
1. **Tiết kiệm thời gian soạn thảo:** Giảm thời gian chuẩn bị câu hỏi và đề kiểm tra bám sát ma trận kiến thức cho giáo viên ít nhất 30–50%.
2. **Độ chính xác và an toàn nội dung:** Đề kiểm tra được tạo ra phải tuân thủ tuyệt đối cấu trúc blueprint đã chọn, không bịa đặt kiến thức (hallucination) và được kiểm duyệt qua quy trình review của giáo viên trước khi xuất bản.
3. **Ổn định hệ thống và bảo mật tenant:** Hoàn thành các bài kiểm tra trực tuyến suôn sẻ, không xảy ra sự cố rò rỉ đáp án hoặc mất mát dữ liệu bài làm của học sinh.

### B. Tiêu chí Thất bại (Failure Criteria - Cần dừng hoặc điều chỉnh)
1. Hệ thống AI sinh đề sai kiến thức cốt lõi với tỉ lệ cao, khiến giáo viên tốn nhiều thời gian sửa hơn là tự soạn.
2. Lỗi bảo mật phân quyền tenant hoặc rò rỉ dữ liệu giữa các lớp học / giáo viên khác nhau.
3. Độ trễ hoặc lỗi kết nối khi học sinh đồng loạt làm bài thi trực tuyến gây gián đoạn tiết học.
