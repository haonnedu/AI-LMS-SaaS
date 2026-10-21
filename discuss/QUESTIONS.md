# Câu hỏi và blocker cần quyết định

Ghi nhận ngày 2026-10-21 từ yêu cầu trực tiếp của người phụ trách trong phiên làm việc. Đây là đầu vào trao đổi, không thay trạng thái tracker.

## Q-01 — Pilot chưa chốt

- Task liên quan: [SCOPE-01](../tasks/CORE.md), [pilot brief hiện có](../tasks/decisions/0005-pilot-scope-success-criteria.md).
- Cần quyết định: giáo viên phụ trách có tên; một cấp/khối, 1–2 môn; bộ sách/phiên bản, nguồn/quyền sử dụng; nhóm 10–20 giáo viên và tiêu chí đo được.
- Người cần xác nhận: người phụ trách sản phẩm và giáo viên chuyên môn; chưa có tên được xác nhận.
- Điều kiện khép câu hỏi: pilot brief được bổ sung và có người có trách nhiệm duyệt.
- Kết quả: chưa có; người dùng xác nhận chưa chốt.

## Q-02 — Ngân sách và region chưa chốt

- Task liên quan: [OPS-01](../tasks/CORE.md), [đề xuất vận hành](../tasks/decisions/0006-ops-environment-security-adr.md).
- Cần quyết định: phương án hosting, region, chi phí dự kiến/giới hạn tháng, owner vận hành và người phê duyệt.
- Người cần xác nhận: người phụ trách sản phẩm/ngân sách; chưa có tên được xác nhận.
- Điều kiện khép câu hỏi: phương án có bảng chi phí và phê duyệt ngân sách/region được ghi.
- Kết quả: chưa có; không mua hoặc deploy dựa trên ghi chú này.

## Q-03 — Yêu cầu máy thứ hai được miễn

- Task liên quan: [BASE-01](../tasks/CORE.md).
- Người dùng đã xác nhận không cần evidence môi trường hoặc chạy lại trên máy thứ hai.
- Đây là thay đổi acceptance, không phải bằng chứng đã chạy trên hai máy. Cần người cập nhật task ghi ngoại lệ này vào execution record để người sau không yêu cầu lại.

## Mẫu thêm câu hỏi

```markdown
## Q-XX — <vấn đề>
- Người ghi / ngày:
- Task và tài liệu liên quan:
- Cần trả lời/chọn điều gì:
- Tác động nếu chưa trả lời:
- Người cần xác nhận (hoặc chưa phân công):
- Đề xuất và tradeoff:
- Điều kiện khép câu hỏi:
- Kết quả / người xác nhận / ngày / decision record:
```
