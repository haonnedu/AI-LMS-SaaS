// Condensed in-app user agreement for every role (decision 0009), derived from
// docs/legal/teacher-terms.md. Keep in sync with the markdown.
// DRAFT: not approved by counsel. Bump together with the backend TERMS_VERSION (docs/legal/README.md).
export const USER_AGREEMENT_VERSION = "2026-10-draft";

export const USER_AGREEMENT_SECTIONS: { title: string; paragraphs: string[] }[] = [
  {
    title: "Bản dự thảo",
    paragraphs: [
      "Đây là bản dự thảo, chưa được luật sư duyệt và chưa có hiệu lực. Bên cung cấp dịch vụ: [tên pháp nhân vận hành Eduvia], [địa chỉ], gọi là \"Eduvia\". Người sử dụng dịch vụ (giáo viên, học sinh, quản trị nhà trường) gọi là \"bạn\". Thỏa thuận này áp dụng cho giai đoạn pilot.",
      "Khi tạo tài khoản, bạn xác nhận đã đọc và đồng ý với Thỏa thuận người dùng này và Thông báo quyền riêng tư. Hệ thống ghi lại phiên bản văn bản, thời điểm và cách bạn đồng ý.",
    ],
  },
  {
    title: "1. Tài khoản",
    paragraphs: [
      "Bạn đăng ký bằng email và mật khẩu hoặc tài khoản Google, và phải cung cấp thông tin đúng. Bạn chịu trách nhiệm giữ bí mật thông tin đăng nhập và mọi hoạt động trong tài khoản; báo ngay cho [email hỗ trợ] nếu nghi ngờ bị lộ.",
      "Không chia sẻ tài khoản, không dùng tài khoản của người khác.",
    ],
  },
  {
    title: "2. Lớp học và dữ liệu học sinh",
    paragraphs: [
      "Giáo viên chỉ thêm học sinh vào lớp bằng đường link mời và chỉ chia sẻ link cho đúng học sinh của lớp. Giáo viên chỉ xem kết quả của học sinh trong lớp mình dạy và chỉ dùng cho mục đích giảng dạy, đánh giá trong nhà trường.",
      "Tệp xuất điểm chứa tên học sinh. Người tải về chịu trách nhiệm bảo quản, không đăng công khai và không gửi cho người không có thẩm quyền.",
      "Học sinh chỉ thấy bài được giao và kết quả của chính mình. Nhà trường có thể bật thêm bước xác nhận của phụ huynh nếu trường yêu cầu.",
    ],
  },
  {
    title: "3. Tài liệu tải lên",
    paragraphs: [
      "Khi tải tài liệu, bạn xác nhận mình là tác giả hoặc có quyền hợp pháp sử dụng tài liệu cho mục đích giảng dạy, và cho phép Eduvia xử lý nó (lưu trữ, tách đoạn, tạo chỉ mục tìm kiếm, gửi đoạn văn bản cho nhà cung cấp AI để soạn nháp).",
      "Không tải lên sách giáo khoa, sách tham khảo hay đề thi có bản quyền của bên khác khi chưa được phép. Bạn giữ quyền sở hữu tài liệu của mình; Eduvia chỉ dùng nó để cung cấp dịch vụ cho bạn và không dùng để huấn luyện mô hình AI theo mặc định.",
      "Tuyệt đối không tải lên tài liệu chứa tên, mã, ảnh, bài làm, điểm hay thông tin cá nhân khác của học sinh hoặc người thứ ba. Nếu lỡ tải lên, hãy xóa ngay và báo [email hỗ trợ].",
    ],
  },
  {
    title: "4. Nội dung do AI tạo là bản nháp",
    paragraphs: [
      "AI có thể sai hoặc thiếu. Mọi giáo án, câu hỏi, đáp án, đề do AI soạn chỉ là bản nháp; giáo viên phải đọc, sửa và duyệt trước khi dùng với học sinh, đặc biệt là đáp án đúng của từng câu trắc nghiệm vì điểm được tính tự động theo đáp án đó.",
    ],
  },
  {
    title: "5. Sử dụng được chấp nhận",
    paragraphs: [
      "Không tải nội dung vi phạm pháp luật, độc hại hoặc xâm phạm quyền người khác; không cố truy cập dữ liệu của lớp hay người dùng khác; không dò hay phá cơ chế bảo mật; không làm quá tải hệ thống; không gian lận khi làm bài.",
    ],
  },
  {
    title: "6. Quyền của bạn với dữ liệu",
    paragraphs: [
      "Bạn có thể xem, xuất bản sao và yêu cầu xóa dữ liệu của mình như mô tả trong Thông báo quyền riêng tư. Bạn có thể ngừng sử dụng và yêu cầu xóa tài khoản bất kỳ lúc nào; trước khi xóa, hãy xuất dữ liệu cần giữ.",
    ],
  },
  {
    title: "7. Tạm ngưng và chấm dứt",
    paragraphs: [
      "Eduvia có thể tạm ngưng hoặc chấm dứt tài khoản nếu bạn vi phạm thỏa thuận, khi có rủi ro bảo mật, hoặc theo yêu cầu của cơ quan có thẩm quyền, kèm thông báo [thời hạn] trừ trường hợp khẩn cấp.",
    ],
  },
  {
    title: "8. Giới hạn trách nhiệm và pháp luật áp dụng",
    paragraphs: [
      "Dịch vụ pilot được cung cấp \"như hiện có\", không cam kết liên tục hay không lỗi. [Điều khoản giới hạn trách nhiệm, luật áp dụng và cơ quan giải quyết tranh chấp — luật sư soạn.]",
    ],
  },
  {
    title: "9. Thay đổi thỏa thuận",
    paragraphs: [
      "Khi thay đổi, Eduvia thông báo và tăng số phiên bản. Bạn cần đồng ý lại với phiên bản mới trước khi tiếp tục sử dụng.",
    ],
  },
];
