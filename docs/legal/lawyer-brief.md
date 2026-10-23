# Bản tóm tắt cho luật sư — Eduvia (pilot với học sinh trung học)

> **DỰ THẢO nội bộ, ngày 2026-10-23.** Nhóm kỹ thuật/sản phẩm soạn để luật sư xem xét. Không phải tư vấn pháp lý, không khẳng định tuân thủ. Mọi nhận định pháp lý trong các tài liệu `docs/legal/` đều mang nhãn `[Cần pháp lý xác nhận: ...]` và cần được chốt.

## 1. Sản phẩm

Eduvia là hệ thống LMS có hỗ trợ AI cho trường trung học Việt Nam. Giáo viên tải tài liệu của mình lên, dùng AI (mô hình ngôn ngữ + tìm kiếm vector) để soạn nháp giáo án/câu hỏi/đề, tự duyệt, rồi giao bài trắc nghiệm một đáp án đúng. Học sinh vào lớp qua link mời, đăng nhập bằng tài khoản (email/mật khẩu hoặc Google, qua Better Auth), làm bài; hệ thống chấm tất định theo đáp án, không dùng AI. Pilot: 10–20 giáo viên, một cấp học, một hoặc hai môn (`tasks/decisions/0005-pilot-scope-success-criteria.md`). Học sinh có thể dưới 16 tuổi. Hệ thống sẽ ghi nhận đồng ý của người giám hộ (giấy tại trường, link, hoặc học sinh đủ tuổi tự đồng ý) kèm `privacy_policy_version`, và hỗ trợ xuất/xóa (ẩn danh hóa) dữ liệu theo yêu cầu.

Tài liệu dự thảo kèm theo: `privacy-notice.md`, `guardian-consent.md`, `student-notice.md`, `teacher-terms.md`, `README.md` (quy ước phiên bản). Kiểm kê dữ liệu chi tiết: `tasks/decisions/0008-privacy-consent-retention.md`.

## 2. Luồng dữ liệu

- **Đăng ký/đăng nhập** (giáo viên, học sinh): trình duyệt → Next.js (frontend) → Better Auth (email, băm mật khẩu, hoặc Google OAuth) → bảng `edu.users`, `edu.user_identities`; phiên mã hóa AES-256-GCM trong Redis (tuyệt đối 24 giờ, không hoạt động 2 giờ).
- **Giáo viên tải tài liệu**: trình duyệt → API → object storage (tệp gốc) + PostgreSQL (`documents`, `document_chunks`).
  - Worker → **nhà cung cấp embedding [có thể ở nước ngoài]**: chỉ văn bản các đoạn trích.
- **Soạn nháp AI**: giáo viên nhập thông số → API/worker → truy xuất tối đa 8 đoạn liên quan → **nhà cung cấp LLM [có thể ở nước ngoài]**: lời nhắc cố định + thông số giáo viên + các đoạn trích. Không gửi tên tệp, email, dữ liệu học sinh, đáp án của học sinh. Prompt/nguồn/đầu ra không ghi log.
- **Học sinh tham gia lớp**: link mời (lưu băm) → API → `edu.accept_class_invitation` tạo `edu.students` (sao `display_name` từ tài khoản) và `enrollments`; **dự kiến** chặn nếu chưa có đồng ý hợp lệ.
- **Làm bài**: học sinh → API → các hàm `edu.student_*` (RLS) → `quiz_attempts`, `student_answers`; đáp án đúng chỉ ở server (`question_keys`, runtime không SELECT); chấm bằng `app/services/scoring.py` → `grading_results`, `grades`. Không gọi nhà cung cấp bên ngoài.
- **Giáo viên xem/xuất kết quả**: API → CSV điểm lớp (chứa tên học sinh) → máy giáo viên (ngoài hệ thống).
- **Xóa/xuất theo yêu cầu** (dự kiến): `/student/privacy`, thao tác trong danh sách lớp → job → ẩn danh hóa `students` + tombstone để áp dụng lại sau khi khôi phục sao lưu.
- **Lưu trữ**: PostgreSQL (+pgvector), object storage, Redis (phiên, broker chỉ chứa id job), log JSON (đã che email/token). Hiện chưa có sao lưu tự động. Nhà cung cấp hosting/email/LLM/embedding: [chưa chọn].

## 3. Sáu câu hỏi cần trả lời

1. **Ngưỡng tuổi.** Cần đồng ý của cha mẹ/người giám hộ cho học sinh dưới 16 hay dưới 18? Học sinh từ đủ 7 tuổi có phải đồng ý song song? Học sinh THPT 16–17 tuổi tự đồng ý được không? Hệ thống hiện không thu ngày sinh; phương án: thu năm sinh, hoặc lớp được gắn cờ "dưới tuổi quy định". Chọn phương án nào là đủ và tối thiểu?
2. **Phiếu giấy qua trường.** Phiếu giấy do trường thu và giáo viên/nhà trường xác nhận trong hệ thống (Eduvia chỉ lưu mã tham chiếu, người xác nhận, thời điểm, phiên bản; không lưu tên/liên hệ phụ huynh hay ảnh phiếu) có đủ là bằng chứng đồng ý không? Trường giữ phiếu bao lâu? Vai trò pháp lý của trường (đồng kiểm soát/bên xử lý) và cần ký thỏa thuận gì? Một ô chọn trên link có đủ xác minh phụ huynh không?
3. **Chuyển dữ liệu ra nước ngoài và đánh giá tác động.** Văn bản tài liệu của giáo viên (có thể chứa thông tin cá nhân giáo viên, không cố ý chứa dữ liệu học sinh) được gửi tới nhà cung cấp LLM/embedding ở nước ngoài. Có phải lập hồ sơ đánh giá tác động xử lý dữ liệu và hồ sơ đánh giá tác động chuyển dữ liệu ra nước ngoài cho pilot 10–20 giáo viên không? Nộp cho cơ quan nào, khi nào (trước khi bắt đầu xử lý?), và có miễn trừ cho quy mô nhỏ không? Nếu nhà cung cấp cam kết không lưu giữ/không huấn luyện thì có thay đổi nghĩa vụ không? Nếu chọn nhà cung cấp trong nước thì có đơn giản hơn không? Nơi lưu trữ chính (PostgreSQL, object storage) có bắt buộc đặt tại Việt Nam không?
4. **Luật áp dụng và thời điểm chuyển tiếp.** Nghị định 13/2023/NĐ-CP và Luật Bảo vệ dữ liệu cá nhân 2025 (hiệu lực 2026-01-01): hiện văn bản nào áp dụng, hai văn bản chồng nhau thế nào, có nghị định hướng dẫn nào chưa ban hành, và các mốc chuyển tiếp/hạn hoàn thiện hồ sơ là gì? Dữ liệu trẻ em có bị coi là dữ liệu nhạy cảm không và kéo theo nghĩa vụ nào (chỉ định bộ phận/nhân sự bảo vệ dữ liệu, đánh giá tác động)? Có luật chuyên ngành về giáo dục áp dụng cho dữ liệu học sinh không?
5. **Thời hạn lưu giữ.** Có chấp nhận các đề xuất trong `0008` mục 2 không (tài khoản: đến khi xóa + 30 ngày; học sinh/bài làm/điểm: năm học + 1 năm; tài liệu: đến khi giáo viên xóa; sinh nháp AI: 1 năm; tác vụ nền: 90 ngày; lời mời: 30 ngày sau hết hạn; tệp xuất: 30 ngày; nhật ký chuyển danh tính: 1 năm; số liệu sử dụng: 2 năm; phiên: 24 giờ)? Có thời hạn tối thiểu/tối đa luật định cho dữ liệu học bạ/điểm không? Thời hạn hết hạn của bản sao lưu?
6. **Điểm ẩn danh hóa còn là dữ liệu cá nhân không?** Khi xóa, hệ thống ẩn danh hóa (đổi tên thành "Học sinh đã xóa", bỏ mã học sinh, bỏ liên kết tài khoản) nhưng có thể giữ điểm và câu trả lời để thống kê lớp và vì bảng điểm là append-only. Dữ liệu này có còn là dữ liệu cá nhân (tái định danh được từ lớp, thời điểm, giáo viên)? Khi nào bắt buộc xóa hẳn bài làm/điểm? Tombstone tái áp dụng sau khôi phục sao lưu có hợp lệ không?

Câu hỏi bổ sung (nếu còn thời gian): thời hạn trả lời yêu cầu của chủ thể dữ liệu; quy trình và thời hạn thông báo sự cố; cơ quan nhận khiếu nại; giới hạn trách nhiệm trong điều khoản giáo viên; quyền sử dụng tài liệu giáo khoa của giáo viên.

## 4. Biện pháp kỹ thuật hiện có (đối chiếu mã nguồn)

| Biện pháp | Vị trí |
|---|---|
| Bảng/ hàm đồng ý của người giám hộ, `privacy_policy_version`, yêu cầu xóa/xuất | `backend/migrations/versions/0016_privacy_consent.py` (đang được soạn; kiểm tra trạng thái khi review) |
| Học sinh chỉ đọc dữ liệu của chính mình qua hàm SECURITY DEFINER `edu.student_assignments`, `student_attempt`, `student_start_attempt`, `student_save_answer`, `student_submit`, `student_results`; actor kiểm tra bằng `edu.assessment_actor_student` | `backend/migrations/versions/0015_assessment.py` |
| Bảng điểm append-only; trigger bảo vệ câu trả lời (`edu.student_answer_guard`) | `0015_assessment.py` |
| Đáp án đúng chỉ ở server (`question_keys`, runtime không có SELECT) | `0014_generation_exams.py`, `0015_assessment.py` |
| Prompt gửi LLM không chứa định danh; ≤ 8 nguồn; không ghi log prompt/đầu ra | `backend/app/services/llm.py`, `backend/app/services/generation.py` |
| Embedding chỉ nhận văn bản đoạn trích | `backend/app/services/embeddings.py`, `backend/app/services/indexing.py` |
| Chấm điểm tất định, không gọi nhà cung cấp | `backend/app/services/scoring.py` |
| Xóa tài liệu: purge chunks/vector/object | `edu.purge_document_chunks` (job `document.delete`) |
| Che email/token/url/key trong audit log | `backend/app/core/audit.py` |
| Phiên mã hóa AES-256-GCM, TTL 24h/2h | `frontend/src/lib/server/auth.ts` |
| Kiểm kê dữ liệu được kiểm thử tự động đối chiếu migration | `backend/tests/test_privacy_inventory.py` |

Chưa có (theo `0008` mục 4.2, 6): sao lưu tự động và khôi phục có kiểm chứng, job purge theo tuổi, lifecycle cho tệp xuất, hợp đồng xử lý dữ liệu và cấu hình không lưu giữ với nhà cung cấp AI, quét PII trong tài liệu tải lên.

## 5. Nhóm sẽ làm gì sau khi có câu trả lời

1. Sửa các văn bản trong `docs/legal/`, chốt `privacy_policy_version` dạng `YYYY-MM-vN`, đồng bộ `frontend/src/content/*.ts`.
2. Chỉnh quy tắc theo ngưỡng tuổi đã chốt (cờ lớp hoặc năm sinh) trong luồng tham gia lớp và bắt đầu làm bài.
3. Hoàn thiện xóa/ẩn danh hóa, xuất dữ liệu, tombstone, purge theo tuổi theo thời hạn đã duyệt.
4. Chọn nhà cung cấp theo kết luận về vị trí/chuyển dữ liệu; ký hợp đồng xử lý dữ liệu; cấu hình không lưu giữ/không huấn luyện; lập hồ sơ đánh giá tác động nếu bắt buộc.
5. Chỉ sau các bước trên mới mời học sinh thật vào pilot.
