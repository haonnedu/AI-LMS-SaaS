# Thiết kế học tập chủ động cho học sinh — Eduvia

> **Trạng thái:** đề xuất thiết kế, chưa triển khai. Ngày: 2026-10-20.
> Tài liệu này không xác nhận hệ thống đã sẵn sàng production, đã đáp ứng pháp lý, hoặc đang cung cấp cấu trúc chính thức của một kỳ thi.

## 1. Mục tiêu và tài liệu liên quan

Mở rộng Eduvia từ công cụ teacher-led thành nền tảng có thêm student-led learning: học sinh chủ động chọn mục tiêu, đánh giá đầu vào, học theo lộ trình và theo dõi tiến bộ. Hai trải nghiệm dùng chung nền tảng chương trình, câu hỏi và đánh giá nhưng không đồng nhất quyền sở hữu dữ liệu.

- [README.md](README.md): định hướng sản phẩm và phạm vi pilot giáo viên hiện tại.
- [ARCHITECTURE.md](ARCHITECTURE.md): kiến trúc core, bảo mật, jobs, immutable assessment và vận hành.
- [DATABASE.md](DATABASE.md): schema đề xuất của core; không phải toàn bộ migration đã triển khai.
- [DEVELOPMENT.md](DEVELOPMENT.md): hiện trạng scaffold và cách kiểm chứng.
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md): tài liệu kế hoạch triển khai dự kiến/liên quan; các mốc ở đây cần được đồng bộ khi kế hoạch được chốt.
- [EXAM_BLUEPRINTS.md](EXAM_BLUEPRINTS.md): tài liệu thiết kế cấu trúc đề dự kiến/liên quan; blueprint là nguồn quy tắc cấu trúc, không để planner tự thay đổi.

Các tài liệu liên kết mô tả thiết kế, không chứng minh tính năng đã implement. Kế hoạch triển khai M0–M7/L0–L4 là nguồn thứ tự giao hàng thống nhất. Tài liệu này chỉ đề xuất ranh giới cho student-learning, không chuyển core hiện tại thành microservices ngay.

### 1.1 Giá trị cần chứng minh

Học sinh phải trả lời được: hôm nay học gì, vì sao, mất khoảng bao lâu, cần làm gì tiếp theo và bằng chứng nào cho thấy mình tiến bộ. Sản phẩm không chỉ là chatbot sinh một danh sách chương học.

Vòng học: chọn chương trình/mục tiêu → chẩn đoán → kế hoạch tuần → học/luyện tập → checkpoint hoặc thi thử → cập nhật bằng chứng → điều chỉnh kế hoạch.

### 1.2 Không thuộc bản đầu

Không cam kết điểm thi; không tự gắn nhãn năng lực cố định; không tự chấm tự luận bằng LLM thành điểm chính thức; không triển khai adaptive testing/IRT ngay; không cần native app, offline submission hay school-wide analytics. AI tutor mở rộng chỉ được xem xét sau khi có nội dung và đánh giá đủ tin cậy.

## 2. Ba chế độ học

| Chế độ | Nhu cầu | Đầu vào riêng | Hoạt động chính | Kết quả mong đợi |
|---|---|---|---|---|
| Bám sát trên lớp | Hiểu bài và theo kịp tiến độ | Lớp, môn, bộ sách/phiên bản, bài đang học, lịch kiểm tra | Chuẩn bị trước bài, ôn sau bài, bổ sung prerequisite | Hoàn thành mục tiêu của bài hiện tại |
| Củng cố kiến thức | Lấp khoảng trống kỹ năng | Nhóm kiến thức muốn củng cố, chẩn đoán, lịch sử có quyền dùng | Kiểm tra kỹ năng nền, bài nhỏ, luyện lỗi, kiểm tra bằng câu mới | Có thêm bằng chứng hiểu và vận dụng |
| Ôn thi theo mục tiêu | Chuẩn bị kỳ kiểm tra/kỳ thi | Blueprint có phiên bản, phạm vi, ngày mục tiêu, thời lượng học | Thi thử, phân tích theo phần/kỹ năng, phân bổ thời gian ôn | Tiến bộ theo mục tiêu nhưng không hứa điểm số |

Chọn bộ sách không đủ để suy ra trường đang học đến đâu. Học sinh xác nhận bài hiện tại; tiến độ từ lớp chỉ được sử dụng qua liên kết được phép. Khi đổi chế độ, không xóa bằng chứng cũ nhưng phải đánh giá lại tính phù hợp với mục tiêu mới.

Ví dụ minh họa: một học sinh chọn Toán lớp 9, muốn theo kịp lớp và chuẩn bị kỳ thi mục tiêu. Hệ thống cần xác minh chương trình, địa phương/năm và blueprint phù hợp trước khi mô phỏng kỳ thi. Ví dụ này không tuyên bố một định dạng đề chính thức.

## 3. Quyền sở hữu: học sinh độc lập trước, liên kết trường sau

Một học sinh có thể sử dụng sản phẩm mà không tham gia bất kỳ workspace giáo viên nào. Không tạo membership giả vào workspace của giáo viên hoặc trường chỉ để lưu lộ trình cá nhân.

- Core sở hữu danh tính đăng nhập toàn cục; student-learning sở hữu hồ sơ học tập cá nhân gắn với subject đã xác minh.
- Student record trong workspace trường/giáo viên tiếp tục thuộc phạm vi dữ liệu giáo dục của workspace đó.
- Mục tiêu, lịch tự học, điểm yếu và bằng chứng luyện cá nhân không mặc nhiên thuộc trường, giáo viên hoặc bên trả tiền.
- Tham gia/rời lớp không chuyển quyền sở hữu hồ sơ cá nhân; trường không tự động đọc được lịch sử tự học.
- Một tài khoản có thể có nhiều student record ở core, nhưng chỉ liên kết các record hợp lệ theo quyền và mục đích đã duyệt. Không ghép hồ sơ bằng email đơn thuần.
- Quyền dùng điểm lớp để cá nhân hóa và quyền chia sẻ báo cáo tự học với giáo viên là hai quyền khác nhau, có thể thu hồi riêng.
- Trả tiền bằng gói trường không tự động cấp quyền xem dữ liệu tự học. Phân tách entitlement, quan hệ lớp và quyền đọc dữ liệu.

Luồng độc lập: đăng nhập → tạo personal learner profile idempotently → khai báo mục tiêu/thời gian → chọn nội dung hợp lệ → chẩn đoán. Không yêu cầu class code.

## 4. Chương trình, kỹ năng và prerequisite

### 4.1 Ba lớp mô hình

1. **Curriculum:** cấp học → lớp → môn → bộ sách/phiên bản → chương → bài.
2. **Skill/objective:** việc học sinh cần làm được, có tiêu chí và định danh ổn định.
3. **Question/task form:** cách kiểm tra kỹ năng, ví dụ câu trực tiếp hoặc bài toán có lời văn.

Một skill có thể xuất hiện ở nhiều bài/bộ sách; một câu có thể đánh giá nhiều skill. Mappings là nhiều-nhiều, có trọng số diễn giải nếu cần; không cộng nhiều lần điểm câu vào tổng bài.

### 4.2 Đồ thị kiến thức tiên quyết

Ví dụ minh họa: phép tính phân số → biến đổi biểu thức → giải phương trình → lập phương trình từ tình huống. Khi học sinh sai bài cuối, chẩn đoán có thể kiểm tra kiến thức nền thay vì kết luận toàn chương chưa đạt.

Core quản lý catalog, skill definitions, prerequisite edges và mappings đã duyệt. AI chỉ đề xuất; chuyên môn duyệt và version hóa. Kiểm tra chu trình, cạnh không hợp lệ, skill bị ngừng sử dụng và đường chuyển phiên bản. Không để mỗi generation tự dựng lại graph.

Student service giữ projection tối thiểu, bất biến theo phiên bản hoặc được cập nhật có kiểm soát. Kế hoạch lưu catalog/mapping version để giải thích quyết định trong quá khứ. Khi skill thay đổi ngữ nghĩa, tạo version/ID mới và quy tắc migration; không âm thầm diễn giải bằng chứng cũ theo nghĩa mới.

## 5. Đánh giá điểm yếu dựa trên bằng chứng

### 5.1 Bằng chứng khác với kết luận

Bằng chứng gồm câu/version, kỹ năng mapping, đáp án đã chấm, thời điểm, loại phiên làm bài, mức hỗ trợ, mức độ mới của câu và provenance của scoring. Mastery là projection có thể tính lại, không phải điểm chính thức hoặc bản chất cố định của học sinh.

Tín hiệu sử dụng:

- Kết quả đúng/sai hoặc điểm theo rubric được core hỗ trợ.
- Độ đa dạng câu và phạm vi skill được kiểm tra.
- Câu mới, lặp lại hoặc gần trùng; tránh tăng confidence chỉ vì học thuộc câu.
- Gợi ý đã dùng; assisted practice không tương đương unassisted assessment.
- Tuổi của bằng chứng và các lần kiểm tra gần đây.
- Độ khó dự kiến so với độ khó thực nghiệm, ghi rõ nguồn ước tính.
- Thời gian trả lời là tín hiệu phụ, không tự suy ra năng lực, chăm chỉ hoặc gian lận.

Đáp án nhiễu có thể gợi ý misconception nhưng chỉ tạo giả thuyết. Hệ thống nên hỏi câu xác nhận; không khẳng định nguyên nhân chỉ từ một lần chọn sai.

### 5.2 Trạng thái và độ bất định

Giao diện dùng các trạng thái: chưa đủ dữ liệu; cần củng cố; đang tiến bộ; tương đối vững; cần ôn lại. Mỗi trạng thái đi cùng lượng bằng chứng, thời điểm và giải thích ngắn. Các ngưỡng là cấu hình có phiên bản, cần hiệu chỉnh chuyên môn/pilot, không phải chuẩn khoa học mặc định.

Không hiển thị một phần trăm thành thạo có vẻ chính xác nếu mô hình chưa được hiệu chuẩn. Phân biệt rõ “quan sát được” với “ước tính”. Bằng chứng mâu thuẫn làm tăng nhu cầu kiểm tra thêm, không bị bỏ đi để tạo báo cáo đẹp.

Ví dụ phản hồi: “Em làm tốt câu biến đổi trực tiếp. Hai câu gần đây có lỗi dấu; mình sẽ kiểm tra thêm bằng câu mới. Chưa đủ dữ liệu về bài toán có lời văn.”

### 5.3 Scoring và projections

Core trả canonical scoring result/version. Student service không tự ghi một tổng điểm thứ hai làm nguồn sự thật. Service lưu tham chiếu cùng snapshot tối thiểu được phép dùng và tạo mastery projection. Khi core regrade, projection phải supersede ảnh hưởng cũ hoặc rebuild, không tính hai lần. Pending grading hiển thị pending, không thành 0 điểm. Bài bị void hoặc bằng chứng bị thu hồi không tiếp tục đóng góp.

## 6. Planner tuần dựa trên quy tắc

### 6.1 Đầu vào và đầu ra

Đầu vào: mục tiêu đang active, thời gian khả dụng, tiến độ học trên lớp do người dùng xác nhận, skill graph version, evidence/mastery version, blueprint version nếu ôn thi, nội dung có quyền truy cập và lịch ôn.

Đầu ra: kế hoạch tuần có version, các learning step, ngân sách phút dự kiến, lý do lựa chọn, checkpoint, điều kiện chuyển tiếp và phương án khi thiếu nội dung. AI có thể diễn đạt hoặc đề xuất bài giảng; rules và constraints quyết định cấu trúc kế hoạch.

### 6.2 Quy tắc ưu tiên ban đầu

1. Prerequisite đang chặn bài hiện tại hoặc mục tiêu gần nhất.
2. Nội dung sắp học/sắp kiểm tra.
3. Skill cần củng cố có trọng số quan trọng trong blueprint mục tiêu.
4. Kiến thức đến hạn ôn theo lịch và bằng chứng gần nhất.
5. Nội dung mở rộng phù hợp thời gian còn lại.

Không chỉ ưu tiên phần có điểm thấp nhất. Ưu tiên có thể cân bằng tính cấp thiết, nền tảng, độ chắc của kết luận, trọng số mục tiêu và tải học. Công thức, thresholds và tie-breakers phải version hóa, có test xác định được kết quả.

### 6.3 Quy trình mỗi tuần

1. Kiểm tra mục tiêu, thời gian và consent/quyền nội dung hiện tại.
2. Xác định skill cần khảo sát thêm vì thiếu dữ liệu.
3. Chọn các bước có prerequisite phù hợp, phân bố học mới/luyện/ôn/checkpoint.
4. Không vượt ngân sách thời gian; hiển thị phần chưa thể bao phủ.
5. Lưu plan version và decision reasons; người học xác nhận hoặc chỉnh lịch.
6. Ghi nhận hoàn thành và đánh giá lại ở checkpoint.

Điều chỉnh nhỏ sau mỗi buổi; replan chính theo tuần hoặc sau thay đổi mục tiêu lớn. Không đổi toàn bộ kế hoạch sau mỗi câu sai. Cho phép nghỉ, giảm tải, đổi ngày; không dùng streak để gây áp lực.

Nếu deadline/mục tiêu không phù hợp thời gian còn lại, trình bày tradeoff và nội dung ưu tiên, không hứa đạt điểm. Nếu catalog/provider không khả dụng, dùng kế hoạch đã lưu và nội dung được phép; không bịa bài thay thế.

## 7. Blueprint và ba loại đánh giá

Blueprint thuộc core: phạm vi chương trình, phần thi, loại câu, số lượng, điểm, ma trận chủ đề/mức độ nhận thức, thời gian, scoring policy, nguồn, người duyệt và phiên bản. Mức độ nhận thức không đồng nghĩa độ khó thực nghiệm.

| Loại | Mục đích | Có thể cá nhân hóa? | Ràng buộc |
|---|---|---|---|
| Diagnostic | Tìm vùng cần khảo sát | Có, trong giới hạn công cụ được duyệt | Báo coverage và uncertainty, không giả làm điểm thi đại diện |
| Practice | Củng cố skill/lỗi cụ thể | Có | Lưu gợi ý, repetition và context; có thể phản hồi từng câu |
| Mock exam | Mô phỏng mục tiêu | Chọn form phù hợp nhưng không tự đổi cấu trúc | Tuân thủ blueprint/version, timing và release policies |

Lộ trình có thể tăng bài luyện điểm yếu; đề mock không được âm thầm tăng tỷ trọng điểm yếu làm mất tính đại diện của blueprint. Nếu thiếu câu hoặc có loại câu chưa hỗ trợ, core trả lỗi thiếu coverage/unsupported format; không tự đổi sang single-choice và vẫn gọi là đúng cấu trúc.

Ưu tiên câu đã duyệt. Sinh câu mới cần validation và chính sách review trước khi phục vụ học sinh. Một file đề mẫu chỉ cho phép AI đề xuất cấu trúc; không đủ xác nhận cấu trúc chính thức. Mẫu được gắn “chính thức” chỉ khi có quy trình xác minh nguồn, phạm vi và hiệu lực phù hợp; tài liệu này chưa xác nhận mẫu nào.

## 8. UX học sinh

### 8.1 Onboarding

Chọn lớp/môn/chương trình, bài đang học, chế độ, mục tiêu và thời gian. Thu thập tối thiểu; không mặc định yêu cầu ngày sinh đầy đủ, địa chỉ hoặc thông tin trường không cần thiết. Cách xác định nhóm tuổi, người giám hộ và cơ sở xử lý phải được review trước pilot có trẻ vị thành niên.

### 8.2 Navigation đề xuất

- **Hôm nay:** nhiệm vụ tiếp theo, thời gian dự kiến, lý do, tiếp tục buổi dở dang.
- **Lộ trình:** tuần hiện tại, mục tiêu, checkpoint, thay đổi và lý do.
- **Bản đồ kiến thức:** coverage, trạng thái, confidence dễ hiểu.
- **Luyện tập:** theo bài/skill/nhóm lỗi, hỗ trợ từng bước.
- **Thi thử:** blueprint/version, phạm vi, thời lượng, quy định và trạng thái chấm.
- **Tiến bộ:** bằng chứng theo thời gian, không chỉ tổng điểm.
- **Lớp của tôi:** liên kết tùy chọn với core, không phải điều kiện dùng self-study.
- **Quyền riêng tư:** dữ liệu được dùng/chia sẻ, revoke consent, export/delete request.

Ví dụ “Hôm nay khoảng 25 phút”: ôn quy tắc dấu → luyện 5 câu → checkpoint ngắn. Hiển thị lý do prerequisite và khả năng điều chỉnh thời lượng.

### 8.3 Trạng thái bắt buộc

Chưa đủ dữ liệu, kết quả pending, nội dung bị thu hồi, quyền chia sẻ đã hết hạn, mất mạng khi đang làm, autosave đang chờ/đã lưu/xung đột, planner unavailable và scoring delayed. Không báo “đã nộp” khi core chưa xác nhận durable submission. Mobile-first, keyboard navigation, độ tương phản, ngôn ngữ phù hợp tuổi; trợ giúp không che mất trạng thái bài thi.

## 9. Kiến trúc student-learning có thể deploy riêng

### 9.1 Bounded contexts và source of truth

| Năng lực/dữ liệu | Owner | Ghi chú |
|---|---|---|
| Identity, sessions, account lifecycle | Core/identity integration | Student service xác minh token, không có kho password riêng |
| Workspaces, membership, teacher/student records trong lớp | Core | Không tự sao chép thành membership cá nhân |
| Curriculum, skills, prerequisites, question bank, blueprint | Core | Student nhận DTO/projection tối thiểu có version |
| Published exam snapshots, attempt delivery, canonical scoring | Core assessment | Key/rubric bí mật ở core; scoring policy có version |
| Personal learner profile, goals, availability, plans | Student-learning | Owner scope là learner, không ép workspace_id của giáo viên |
| Practice evidence, mastery và progress projections | Student-learning | Evidence tham chiếu kết quả canonical; projection rebuildable |
| Consent chia sẻ/dùng dữ liệu cá nhân trong student domain | Student-learning, phối hợp authority tương ứng | Consent không ghi đè quyền truy cập core hoặc legal requirements |

Core cung cấp assessment cho independent learner bằng quyền cá nhân/capability thích hợp; không gắn giả vào workspace giáo viên. Thiết kế bảng attempt cá nhân cần được quyết định riêng khi implement core; không bỏ nullable workspace_id vào các tenant tables hiện tại để trộn scope. Có thể dùng personal-assessment aggregate riêng với owner type rõ ràng. Nếu chưa có owner scope đó, chặn rollout independent assessment thay vì bypass RLS.

### 9.2 Triển khai mục tiêu

Student service là API/worker deployment riêng, database riêng, migrations và runtime roles riêng; có thể mở rộng planner/projector độc lập. Core và student cùng dùng identity authority nhưng không chia sẻ database credentials. Có thể dùng cùng cụm PostgreSQL vật lý trong pilot nếu logical databases/roles và boundaries thực sự tách biệt; đó không phải cross-service table access.

Browser → gateway/BFF hoặc API đã cấu hình → student API cho plans/profiles; core assessment API cho attempt delivery/submission. Student worker gọi core bằng service credential và capability phù hợp, không giữ token browser dài hạn.

**Không direct cross-service DB reads/writes, không SQL join hay FK xuyên service.** External IDs là opaque references được xác minh qua API/events; local FK chỉ trong database của owner. Một service down không được “tạm” truy cập DB của service khác.

### 9.3 Optional modular phase trước extraction

Có thể bắt đầu bằng module student-learning trong modular monolith để giảm chi phí vận hành, nhưng giữ ownership, DTO, application ports và no-direct-cross-domain-repository rule. Các đường tích hợp phải có adapter để chuyển từ in-process API sang network API. Nếu dùng schema riêng trong cùng database ở giai đoạn này, không tạo cross-boundary FK/joins sẽ phải phá khi tách.

Extraction gate: workflow đã ổn định, contract/versioning có tests, identity cá nhân rõ ràng, outbox/inbox/recovery chạy được, deletion/consent propagation kiểm chứng, load hoặc release cadence cho thấy lợi ích, và có owner vận hành/monitoring/rollback. Không tách chỉ vì tên tính năng lớn.

Khi extraction, export/import theo snapshot + event watermark, backfill projection, so sánh kết quả và cutover có rollback. Không dual-write tùy tiện hai nguồn sự thật; đóng hoặc chuyển hướng writer theo từng aggregate trong cutover. Cần diễn tập migration trước dữ liệu thật.

## 10. Auth và privacy xuyên service

- Token có issuer, audience, expiry, subject và scopes được kiểm tra; không tin user_id/workspace_id từ client body/header.
- Student access dùng learner owner scope. Service token không tự chứng minh quyền xem mọi học sinh.
- Delegation token ngắn hạn hoặc capability ràng buộc actor, learner, operation, resource/purpose; không chuyển nguyên browser token tới mọi service.
- Core tự kiểm tra quyền nội dung, license, account state và assessment policy; student service không thể cấp vượt quyền core.
- Worker dùng service identity và job đã lưu, không dựa vào request claims chưa kiểm chứng. Chấm submission đã commit có capability hệ thống hẹp; không cấp lại quyền đọc cho user đã bị thu hồi.
- Cookie browser cần CSRF và SameSite/HttpOnly phù hợp; nếu bearer flow được chọn phải có threat model và lưu token an toàn. Không đưa service secrets vào frontend.
- Revoke consent/account suspension cần invalidation event và kiểm tra authoritative state cho thao tác nhạy cảm. TTL ngắn là lớp bổ sung, không thay cho kiểm tra thu hồi.
- Mỗi API đọc learner dữ liệu kiểm tra own-record hoặc grant rõ ràng; giáo viên không được enumerate learner profiles.

Consent ghi purpose, data categories, recipient, policy version, thời gian và người/cơ sở chấp thuận thích hợp. Không coi mọi xử lý đều chỉ dựa consent; legal basis, quy định trẻ em và quyền guardian cần review chuyên môn. UI phải tách dùng kết quả lớp để cá nhân hóa với chia sẻ báo cáo tự học cho lớp.

Provider AI chỉ nhận nội dung tối thiểu; không gửi tên, email hoặc điểm học sinh nếu không cần. Không dùng private data để training mặc định. Audit không chép toàn bộ đáp án, prompts hoặc signed URLs.

## 11. Contract API khái niệm

Các route/payload dưới đây là đề xuất, không phải OpenAPI đang chạy. Contract cần versioning, DTO allowlist, pagination, request bounds, UTC timestamps và integration tests.

### 11.1 Student-owned API

- `GET /student/v1/me/profile`: hồ sơ cá nhân đã xác thực.
- `POST /student/v1/me/goals`: tạo mục tiêu với curriculum/blueprint reference.
- `PUT /student/v1/me/availability`: cập nhật lịch với expected revision.
- `POST /student/v1/me/plans:generate`: trả durable job ID; không giữ HTTP chờ LLM.
- `GET /student/v1/me/plans/{plan_id}`: plan version và decision reasons.
- `POST /student/v1/me/practice-sessions`: tạo orchestration session, yêu cầu core cấp assessment phù hợp.
- `GET /student/v1/me/mastery`: projection, evidence coverage, as_of và lag.
- `POST /student/v1/me/consent-grants` và revoke endpoint: mục đích/recipient rõ ràng.
- `POST /student/v1/me/deletion-requests`: workflow xóa có trạng thái.

Ví dụ tạo mục tiêu:

```json
{
  "mode": "exam_preparation",
  "curriculum_ref": {"id": "opaque-curriculum-id", "version": 3},
  "blueprint_ref": {"id": "opaque-blueprint-id", "version": 2},
  "target_date": "2027-05-15",
  "weekly_minutes": 150,
  "preferences": {"session_minutes": 25}
}
```

Các ID/ngày là minh họa. API derive learner ID từ session, kiểm tra reference qua core và trả conflict nếu version không phù hợp. Mutation idempotency key scoped actor/operation + request hash; key cũ với body khác trả conflict.

### 11.2 Core integration APIs

- Catalog/version lookup và changed-since cursor, chỉ trả metadata được phép.
- Assessment request theo purpose `diagnostic | practice | mock`, skill scope hoặc blueprint version.
- Attempt start/delivery/autosave/submit theo owner capability.
- Scoring result/version lookup, trả summary/evidence DTO tối thiểu theo purpose và release rules.
- Consent-aware class result import bằng authorization hai phía; không có generic export mọi điểm của một user.
- Event snapshot/reconciliation endpoint để consumer phục hồi khi mất lịch sử event.

Core kiểm tra blueprint constraints và nội dung được phép ở lúc tạo/delivery; không tin planner đã kiểm tra đủ. Snapshot/pinned version có provenance và hash khi cần, không chứa key ở DTO browser.

## 12. Delivery và canonical scoring boundary

1. Student service xác nhận profile, goal và quyền dùng nội dung; gọi core tạo assessment request bằng idempotency key ổn định của practice session.
2. Core resolve owner cá nhân, purpose, scope/blueprint, chọn published question/exam snapshot và lưu authoritative attempt state.
3. Browser nhận student-safe questions/options và deadline. Keys, đáp án đúng, private rubric/teacher notes không đi vào browser, SSR payload, preload hoặc student logs.
4. Browser lưu/nộp qua core endpoint hoặc proxy minh bạch chuyển tới core; proxy không tự xác nhận durable save hoặc tính điểm. Core enforce ownership, state, revision, deadline và idempotency.
5. Core submit/scoring theo transaction/outbox; pending được hiển thị đúng. Practice có thể dùng per-item feedback policy, mock không được bật gợi ý chỉ vì planner yêu cầu.
6. Core phát result event; student inbox nhận tham chiếu và lấy result DTO được phép. Mastery cập nhật khi có bằng chứng canonical, không dùng score do browser gửi.
7. Core regrade/void/release/revoke tạo version mới; student projector cập nhật tương ứng. Student không dùng event nội bộ để lộ lời giải trước release.

Grade trong lớp vẫn do core quản lý và không bị planner sửa. Nếu chấm tự luận chưa hỗ trợ đáng tin cậy, hiển thị chờ chấm hoặc giới hạn scope; không lấy lời nhận xét LLM làm official grade.

Nếu gọi core timeout sau create/submit, truy vấn lại bằng idempotency key để biết trạng thái, không tạo attempt khác. Core down thì không xác nhận nộp thành công; dữ liệu local chỉ là pending cache theo chính sách, không mở offline submission ngoài scope.

## 13. Events, ordering, recovery và consistency

### 13.1 Outbox/inbox

Owner ghi domain change và outbox cùng transaction. Publisher gửi at-least-once. Consumer ghi inbox deduplication và projection/job update cùng local transaction rồi ack. Không hứa exactly-once transport hay distributed transaction.

Envelope khái niệm:

```json
{
  "event_id": "opaque-event-id",
  "event_type": "assessment.result.updated",
  "schema_version": 1,
  "aggregate_type": "assessment_attempt",
  "aggregate_id": "opaque-attempt-id",
  "aggregate_version": 4,
  "occurred_at": "2026-10-20T16:00:00Z",
  "correlation_id": "opaque-correlation-id",
  "payload": {
    "learner_ref": "opaque-authorized-subject-ref",
    "result_ref": "opaque-result-id",
    "result_version": 2,
    "change_kind": "regraded"
  }
}
```

Không đưa key, raw answers hoặc tên học sinh lên broad event bus. Topic/subscription có ACL; learner ref vẫn là dữ liệu nhạy cảm cần bảo vệ. Envelope identity là provenance, không thay thế authorization khi fetch resource.

### 13.2 Ordering và version

Không giả định global ordering. Partition theo aggregate khi transport hỗ trợ; consumer vẫn kiểm tra version. Event trùng dedup bằng event_id; event cũ không ghi đè state mới. Nếu gặp gap, giữ pending và fetch snapshot hoặc replay từ cursor; không âm thầm áp dụng cộng dồn thiếu bước.

Phân biệt event schema version, aggregate version, scoring result version, curriculum version và mastery model version. Unknown schema vào quarantine/dead-letter với alert. Khi cần tính mọi observation, dùng event history đầy đủ; snapshot latest chỉ phù hợp rebuild state/projection, không được giả là đã nhận đủ mọi sự kiện lịch sử.

### 13.3 Events đề xuất

- Core → student: catalog/blueprint version published hoặc withdrawn; assessment submitted/result updated/voided; account suspended/deleted; consent-related class-data access revoked nếu core là authority.
- Student → core theo nhu cầu: integration consent changed, personal data deletion requested/completed, entitlement usage events đã định nghĩa rõ. Không phát toàn bộ mastery cho giáo viên theo mặc định.

Planner/job nội bộ student cũng dùng durable jobs/outbox, retry có giới hạn, cancellation và idempotency. Một event có thể kích hoạt replan nhưng phải debounce/coalesce, không tạo nhiều plan chỉ vì replay.

### 13.4 Recovery

Có reconciliation định kỳ theo watermark/version và missing references; inbox/outbox backlog, projection lag và stale plan được đo. Replay không double-count evidence. Rebuild mastery từ evidence được phép, có model version; so sánh trước cutover. Deleted/tombstoned learner không được resurrect khi replay hoặc restore.

Core mất kết nối: đọc plan đã lưu có nhãn freshness, dừng hành động cần quyền mới. Student mất kết nối: core vẫn có thể phục vụ attempt hợp lệ; khi phục hồi, reconcile attempt/result từ core. Không chấm lại riêng ở student để che failure.

## 14. Catalog dữ liệu student-learning đề xuất

Bảng dưới thuộc database student service. UUID external là opaque reference, **không FK sang core**. Các bảng cá nhân có `learner_profile_id` bắt buộc và local ownership authorization/RLS phù hợp. Không dùng `workspace_id` giáo viên làm owner mặc định.

| Entity | Trường/ý nghĩa chính | Invariant |
|---|---|---|
| learner_profiles | identity issuer/subject reference, locale, status, created_at | Một profile active cho identity theo chính sách; không key bằng email |
| learner_preferences | session preferences, accessibility settings, revision | Thu thập tối thiểu, optimistic locking |
| learning_goals | mode, curriculum/blueprint refs+versions, target_date, status | Reference được core xác thực; không đồng nhất mục tiêu với cam kết điểm |
| availability_versions | tuần/ngày khả dụng, timezone, minute budget | Lưu version, không ghi đè lịch đã dùng để giải thích plan cũ |
| learning_plans | goal_id, week_start, planner_version, input_watermark, status | Một active version theo goal/tuần; replan tạo version mới |
| learning_steps | plan_id, sequence, skill refs, activity kind, estimated_minutes, reasons, status | Local FK; bounded duration; giữ decision provenance |
| practice_sessions | purpose, core assessment/attempt refs, state, idempotency key, request hash | Không lưu canonical grade riêng; tạo core attempt có retry an toàn |
| practice_evidence | session_id, result/item refs, result_version, skill mapping version, assistance, validity | Dedup theo source/version/item; supersede/revoke có dấu vết |
| mastery_projections | skill ref/version, model_version, status, confidence band, evidence_count, as_of | Rebuildable; unique learner/skill/model; không official score |
| misconception_hypotheses | skill/error refs, supporting evidence refs, status | Giả thuyết có uncertainty, có thể bác bỏ |
| review_schedule | skill refs, next_review_at, rule_version, basis | Không coi thời gian trôi qua là bằng chứng chắc chắn đã quên |
| consent_grants | purpose, categories, recipient, policy version, status, expiry, authority | Revocation cụ thể; không mở rộng quyền core |
| class_record_links | external record refs, scope, authorization/consent refs, state | Không local FK tới core; không tự import tất cả kết quả |
| catalog_projections | external IDs/versions, safe metadata, sync watermark | Không copy keys hoặc raw licensed corpus không được phép |
| background_jobs / outbox_events / inbox_events | durable execution, delivery, consumer dedup | Transactional local updates, retry/lease, bounded payload |
| audit_events / deletion_requests / deletion_tombstones | access changes, erasure status, retention basis | Append-only audit tối thiểu; tombstone chống phục hồi dữ liệu đã xóa |

Raw student answers ưu tiên ở core assessment owner; student chỉ lưu phần bằng chứng cần thiết và được phép. Retention của evidence/projections, integration links và audit phải được chốt trước pilot. Foreign references mất hiệu lực cần trạng thái tombstone/withdrawn và UI phù hợp, không crash hoặc tự cascade xóa mất provenance được phép giữ.

## 15. Xóa dữ liệu, thu hồi quyền và khôi phục

Xóa profile cá nhân khác với xóa account toàn cục hoặc hồ sơ lớp. UI giải thích phạm vi và các dữ liệu phải giữ theo policy hợp lệ; không hứa xóa điểm lớp nếu trường/core có nghĩa vụ lưu giữ khác.

Workflow: chặn truy cập theo phạm vi → ghi deletion request/outbox → dừng jobs, revoke integration access → xóa/pseudonymize profile, plans, evidence, projections, caches, artifacts theo policy → phối hợp core xóa personal assessment data khi thuộc scope → nhận ack/reconcile → ghi completion có exceptions cụ thể.

Account deletion từ identity/core phải được xử lý idempotently ở student. Consumer deletion event có priority phù hợp nhưng vẫn version-safe. Core lưu tombstone hoặc lifecycle version để late result không tái tạo profile. Consent withdrawal đối với class data phải dừng import và xử lý evidence/projection đã dẫn xuất theo policy; không chỉ xóa token rồi tiếp tục giữ mọi kết luận.

Backups hết hạn theo policy; restore replay deletion tombstones và reconcile với authoritative lifecycle trước khi mở traffic. Giữ audit tối thiểu theo retention, không giữ raw evidence vô hạn dưới tên audit. Deletion bị lỗi giữa hai service có retry, status và alert; không báo hoàn tất chỉ vì gửi event.

## 16. Phased delivery và acceptance gates

| Phase | Scope | Điều kiện nghiệm thu |
|---|---|---|
| S0 — Chuẩn bị nền trong core | Skill mappings, prerequisite catalog, blueprint versions, immutable exams, per-item results | Mapping/version có review; student-safe DTO không key; unsupported blueprint bị từ chối rõ |
| S1 — Self-study tối thiểu | Một môn/khối/chương trình; independent profile, mục tiêu, chẩn đoán, planner rules, question bank đã duyệt | Không cần teacher workspace; hoàn thành onboarding → diagnostic → tuần học → checkpoint; quyền cá nhân được test |
| S2 — Luyện tập và tiến bộ | Evidence, uncertainty, assisted/unassisted distinction, review schedule, replan | Replay/regrade không double-count; ít dữ liệu hiện chưa đủ dữ liệu; plan không vượt budget và có lý do |
| S3 — Ôn thi theo cấu trúc | Blueprint đã kiểm chứng phù hợp scope, mock, báo cáo phần/kỹ năng | Mock tuân thủ blueprint; thiếu coverage không âm thầm thay cấu trúc; không lộ giải trước release |
| S4 — Extraction nếu đủ gate | Deploy student API/worker/DB riêng, API/events, migration và recovery | Không cross-DB credentials/joins/FKs; contract auth, replay, deletion và cutover/rollback được diễn tập |
| S5 — Cá nhân hóa nâng cao | Difficulty calibration, adaptive diagnostics, tutor có giới hạn | Có tập đánh giá và dữ liệu đủ chất lượng; đo lợi ích so baseline rules, kiểm soát uncertainty và harm |

Mapping với roadmap thống nhất trong [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md): S0 tương ứng L0 và nền M4; S1–S2 tương ứng L1–L2; S3 tương ứng L3; S5 tương ứng L4. S4 là gate deployment tùy chọn, có thể thực hiện tại L1 hoặc sau đó, không phải một mốc sản phẩm bắt buộc nằm sau S3. Không bắt buộc tách nếu modular phase còn đáp ứng. Các phase là đề xuất, không cam kết lịch hoặc tuyên bố implemented.

### 16.1 Bộ acceptance tests quan trọng

- Học sinh A không đọc/sửa plans, evidence hoặc mastery của B; giáo viên không tự đọc hồ sơ self-study của học sinh lớp mình.
- Account độc lập tạo assessment không sinh workspace giả hoặc bỏ qua tenant policy.
- Token sai audience/scope, revoked grant, suspended account đều bị từ chối đúng boundary.
- Event duplicate/out-of-order/gap, schema unknown, result regrade/void và replay sau outage đều có kết quả xác định.
- Planner không dùng source bị thu hồi; version cũ được giải thích hoặc replan rõ ràng.
- Mock không bị planner đổi phân bố; câu có hỗ trợ không bị tính tương đương câu thi không hỗ trợ.
- Autosave/submit/deadline do core enforce; core timeout không tạo submission thành công giả.
- Inspect API/HTML/SSR/cache/export/log để phát hiện key hoặc unreleased solution.
- Delete/revoke giữa lúc worker chạy và restore/replay không tái tạo dữ liệu hoặc quyền đã thu hồi.
- Rebuild mastery từ evidence hợp lệ khớp expected fixtures và có watermark/model version.
- Đánh giá chuyên môn xác nhận lộ trình hợp lý, prerequisite đúng và ngôn ngữ không gắn nhãn học sinh.

## 17. Chỉ số và quyết định còn mở

Theo dõi completion của kế hoạch với tải học thực tế, quay lại học, chất lượng giải thích bước tiếp theo, kết quả câu mới tại checkpoint, tỷ lệ insufficient evidence, teacher/expert review của mapping, blueprint compliance, core scoring delay, event lag và deletion completion. Không tối ưu thời gian online hoặc số câu làm bằng mọi giá. So sánh điểm cần xét form/độ khó/hỗ trợ, không dùng tăng raw score làm bằng chứng chắc chắn của tiến bộ.

Cần chốt trước implement: môn/khối pilot; nội dung hợp lệ; ownership model của personal assessment trong core; identity và age/guardian flow; policy dùng/chia sẻ điểm lớp; retention/deletion; loại câu và scoring được hỗ trợ; blueprint validation process; giới hạn AI cost; rules/confidence thresholds và bộ fixtures; lựa chọn modular trước hay deploy riêng theo nguồn lực.

**Ưu tiên gần nhất:** chuẩn bị skill mapping và Exam Blueprint trong core, sau đó thực hiện một vòng self-study hẹp dựa trên ngân hàng câu hỏi đã duyệt. Chỉ tăng độ phức tạp cá nhân hóa hoặc tách deployment khi đã có bằng chứng sản phẩm và vận hành đủ mạnh.
