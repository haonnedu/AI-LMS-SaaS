# Thiết kế cấu trúc đề và sinh đề — Exam Blueprints

> Trạng thái: **đề xuất thiết kế, chưa implement**. Tài liệu này không chứng nhận cấu trúc của bất kỳ kỳ thi thực tế nào. Tên bảng, schema và API bên dưới là hợp đồng đề xuất, phải được đối chiếu với migration và chính sách quyền khi triển khai.

## 1. Mục đích và tài liệu liên quan

Blueprint là bản đặc tả có phiên bản của một đề kiểm tra: phạm vi kiến thức, các phần, số câu, thang điểm, ma trận và ràng buộc xuất bản. Blueprint không phải đề đã sinh, không phải ngân hàng câu hỏi và không phải lời nhắc tự do gửi cho LLM.

Mục tiêu:

- Giáo viên tạo đề có thể kiểm tra được cấu trúc và truy nguyên nguồn.
- Học sinh thi thử đúng cấu trúc mục tiêu, không bị hệ thống âm thầm tăng tỷ trọng phần yếu rồi gọi đó là đề chuẩn.
- Bài chẩn đoán và bài luyện có khả năng cá nhân hóa nhưng được phân loại rõ.
- Kết quả từng câu tạo bằng chứng học tập, không biến một bài ngắn thành kết luận chắc chắn về năng lực.

Đọc cùng:

- [Thiết kế học sinh tự học](<STUDENT_LEARNING.md>): hồ sơ kỹ năng, lộ trình và service học tập tiêu thụ assessment.
- [Kế hoạch triển khai](<IMPLEMENTATION_PLAN.md>): thứ tự milestone và điều kiện bàn giao.
- [Kiến trúc](<ARCHITECTURE.md>): tenant isolation, jobs, xuất bản bất biến, submission và grading.
- [Database](<DATABASE.md>): tên thực thể cốt lõi, composite tenant FK, exam snapshots và quyền đáp án.

Các mở rộng ở đây bổ sung thiết kế hiện có, không ngụ ý các bảng và endpoint đã tồn tại. Khi có xung đột, phải ghi quyết định và cập nhật hợp đồng trước implementation; không tự tạo hai nguồn dữ liệu authoritative cho điểm hoặc đề đã xuất bản.

## 2. Phân biệt sản phẩm đánh giá

| Chế độ | Mục đích | Quy tắc cấu trúc | Sử dụng kết quả |
|---|---|---|---|
| `diagnostic` — chẩn đoán | Tìm kỹ năng cần kiểm tra thêm | Có thể chọn nhánh thích ứng theo policy đã version hóa; lưu đường đi thực tế | Bằng chứng có độ tin cậy, không mặc nhiên là điểm thi dự báo |
| `practice` — luyện tập | Củng cố kỹ năng, lỗi hoặc kiến thức đến hạn ôn | Cá nhân hóa phạm vi, độ dài và gợi ý; ghi rõ bài luyện | Tách câu mới/cũ, có/không gợi ý; không đồng nhất với thi thử |
| `mock` — thi thử | Mô phỏng kỳ kiểm tra/kỳ thi mục tiêu | Tuân thủ blueprint cố định, thời gian và chính sách trợ giúp | Báo cáo theo phần/chủ đề; không khẳng định tương đương điểm kỳ thi thật |
| `class_assessment` — bài kiểm tra lớp | Giáo viên đánh giá học sinh | Cấu trúc do giáo viên duyệt, gắn assignment | Điểm chính thức theo scoring/release policy của core |

Một lượt thi thử không đổi độ khó hoặc phân bổ sau mỗi câu sai. Nếu cho phép biến thể, mỗi biến thể phải được blueprint cho phép và lưu rõ trong manifest. Bài chẩn đoán thích ứng là scope sau MVP; phiên bản đầu có thể dùng bài chẩn đoán cố định.

## 3. Nguồn, thẩm quyền và trạng thái xác minh

### 3.1 Ba loại blueprint

1. **`official_reference` — mẫu tham chiếu nguồn chính thức đã xác minh:** nền tảng đã kiểm tra nguồn ban hành, phạm vi và hiệu lực. Nhãn đúng là “mẫu bám theo nguồn chính thức đã xác minh”, không phải “đề chính thức” hoặc chứng nhận của đơn vị ban hành. Phải có bằng chứng và người duyệt.
2. **`teacher_defined` — mẫu giáo viên/trường:** thuộc workspace, người có quyền biên soạn và duyệt. Không được tự mang nhãn chính thức vì giống một đề mẫu.
3. **`personalized` — mẫu luyện tập/chẩn đoán cá nhân:** phục vụ mục tiêu học cụ thể, có chính sách chọn kỹ năng. Không dùng nhãn thi thử chuẩn nếu đã thay đổi các ràng buộc của cấu trúc mục tiêu.

`origin_kind`, `verification_status` và `lifecycle_status` là ba chiều độc lập. Một mẫu đã publish vẫn có thể là teacher-defined; một nguồn đã xác minh vẫn cần validation kỹ thuật trước publish.

### 3.2 Metadata bắt buộc hoặc có điều kiện

- ID ổn định, version number, `schema_version`, content hash, ngôn ngữ, tiêu đề và mô tả.
- Owner scope: catalog được quản trị hoặc workspace riêng; không dùng `workspace_id = NULL` để trộn catalog vào bảng tenant.
- Môn, khối/lớp, cấp học, curriculum edition, địa phương/đơn vị áp dụng nếu có, loại kiểm tra và năm/kỳ áp dụng.
- Phạm vi được phép: chương, bài, kỹ năng; danh sách loại trừ; chương trình và bản sách được tham chiếu riêng.
- Thời lượng, tổng điểm, số câu; quy tắc làm tròn, hiển thị điểm và chính sách tính điểm phiên bản hóa.
- `effective_from`, `effective_until` nếu có; ngày xác minh gần nhất; nguồn bị thay thế bởi phiên bản nào.
- Cơ quan ban hành được tuyên bố, URL/tài liệu tham chiếu, ngày truy cập, mã văn bản, checksum và phạm vi phần được dùng; quyền lưu/trích dẫn nguồn.
- Người biên soạn, người xác minh, reviewer, thời điểm review/publish và ghi chú sai khác với nguồn.
- Điều kiện sử dụng: kỳ thi nào, đối tượng nào, nơi nào; được phép tạo derivative, export hay phân phối không.

Thời điểm hiệu lực của mẫu khác với thời gian mở/đóng assignment. Một tài liệu công khai không mặc nhiên có quyền sao chép toàn văn. Thiếu bằng chứng xác minh phải hiển thị `unverified` hoặc `needs_review`, không suy diễn từ tên file.

### 3.3 Quản lý thay đổi

- Nguồn chính thức thay đổi: tạo version mới, đánh dấu version cũ `superseded` hoặc `withdrawn` tùy nguyên nhân.
- Chặn tạo đề mới theo mẫu hết hiệu lực ngoài policy lịch sử được cho phép; không âm thầm nâng version.
- Đề đã publish giữ nguyên snapshot để tái lập kết quả. Nếu phát hiện lỗi nghiêm trọng, thu hồi việc phân phối mới và xử lý các attempt đã tồn tại qua workflow audit riêng, không sửa key trực tiếp.
- Thu hồi giấy phép có thể chặn phân phối ngay cả khi version bất biến. Bất biến không có nghĩa quyền đọc tồn tại mãi mãi.

## 4. Mô hình ma trận: chủ đề, kỹ năng, nhận thức và độ khó

Blueprint biểu diễn các ô phân bổ: `topic × skill/objective × cognitive_level`, với số câu, điểm hoặc phạm vi cho phép được khai báo rõ. Có thể dùng số chính xác cho MVP; min/max và tối ưu nhiều chiều là mở rộng sau.

Phải phân biệt:

- **Chủ đề/chương:** vị trí trong chương trình.
- **Kỹ năng/mục tiêu:** học sinh cần làm được điều gì; một kỹ năng có thể xuất hiện trong nhiều bài/sách.
- **Mức độ nhận thức:** yêu cầu tư duy theo taxonomy có tên và phiên bản, ví dụ nhận biết, thông hiểu, vận dụng.
- **Độ khó dự kiến:** đánh giá chuyên môn trước triển khai, có người đánh giá và thời điểm.
- **Độ khó thực nghiệm:** thống kê từ cohort có điều kiện xác định, số mẫu và thời gian; không thể suy ra chỉ từ nhãn nhận thức.

Câu vận dụng không mặc nhiên khó với mọi cohort. Dữ liệu có gợi ý, làm lại hoặc đã thấy câu không được gộp vô điều kiện với dữ liệu thi thử. Chưa đủ mẫu thì báo chưa hiệu chỉnh, không gắn nhãn “độ khó chuẩn hóa”.

Một câu có thể liên quan nhiều kỹ năng. Để tổng ma trận không đếm trùng, blueprint phải chọn quy ước:

- MVP: mỗi slot có đúng một `primary_matrix_cell`; các kỹ năng phụ là annotations.
- Báo cáo kỹ năng có thể đếm một câu ở nhiều nhóm, nhưng phải ghi rõ nhóm chồng lấn và không cộng chúng thành tổng điểm đề thứ hai.

Nếu dùng tỷ lệ, phải xác định mẫu số là **số câu hay số điểm**. Không làm tròn tỷ lệ rồi vô tình thay tổng; slot expansion phải trả về các số nguyên và tổng điểm hợp lệ.

## 5. Các phần, nhóm câu và giới hạn

### 5.1 Section/part

Mỗi phần có ID ổn định trong version, vị trí, tiêu đề, hướng dẫn, loại câu được phép, số câu, điểm, scope và quy tắc điều hướng. Hướng dẫn cho thí sinh tách khỏi ghi chú giáo viên.

### 5.2 Item group và passage

Một nhóm có thể chứa đoạn văn, hình, bảng số liệu hoặc ngữ liệu chung:

- Nhóm có version, quyền sử dụng và nguồn; mọi câu phải khớp ngữ liệu.
- Ràng buộc số câu trong nhóm, thứ tự, có được tách nhóm hoặc shuffle không.
- Không shuffle câu phụ thuộc câu trước hoặc tách passage khỏi item.
- Kiểm tra câu này không tiết lộ đáp án câu khác.
- Snapshot ngữ liệu và mapping item/group khi publish; không đọc ngữ liệu đang sửa từ question bank lúc học sinh làm bài.
- Kiểm tra khả năng hiển thị công thức, hình và văn bản thay thế; không tự loại hình bắt buộc để đủ quota.

### 5.3 Điểm và rubric

- Single-choice MVP: ít nhất hai option, đúng một đáp án đúng, điểm dương, không điểm âm và không partial credit.
- Tổng điểm đề bằng tổng điểm item; tổng section/cell phải nhất quán theo quy ước đếm.
- Dùng decimal hoặc đơn vị điểm nguyên nội bộ, không dùng phép cộng float thiếu kiểm soát.
- Key, rubric chấm và giải thích chưa release không nằm trong student DTO hoặc frontend preload.
- Short-answer/tự luận sau này phải có rubric version, quy tắc nhận dạng đáp án tương đương và review. AI chỉ đề xuất; không tự động biến điểm LLM thành điểm chính thức.

### 5.4 Thời gian và quyền áp dụng

MVP chỉ cần tổng thời gian đề và assignment window. Deadline attempt là mốc sớm hơn giữa assignment close và start + time limit, theo core assessment.

Timer theo phần, cấm quay lại, cho nghỉ, accommodation hoặc timer từng item cần capability riêng. Chưa hỗ trợ thì validation từ chối cấu hình, không mô phỏng bằng đồng hồ UI. Không tự giảm thời gian của học sinh vì mô hình dự đoán làm nhanh.

Blueprint mô tả cấu trúc, không tự cấp quyền xem kho nguồn hoặc làm assignment. Runtime vẫn kiểm tra membership, entitlement, enrollment, quyền xuất bản và quyền phân phối.

## 6. Ví dụ phi chính thức: đề single-choice MVP

**Mẫu minh họa, không phải cấu trúc kỳ thi chính thức.** Môn Toán, phạm vi giả định gồm phân số, biến đổi biểu thức và phương trình. Mọi mapping tới chương trình thật phải được bổ sung và duyệt trước dùng.

- Origin: `teacher_defined`; version `1`; mode `mock` nội bộ.
- Thời lượng: 30 phút; 20 câu single-choice; mỗi câu 0,5 điểm; tổng 10 điểm.
- Một phần, không passage phụ thuộc, không timer từng phần.
- Blueprint này không chứa tuyên bố đã được đơn vị thi nào xác nhận.

| Chủ đề / kỹ năng chính | Nhận biết | Thông hiểu | Vận dụng | Tổng câu | Tổng điểm |
|---|---:|---:|---:|---:|---:|
| Phân số / thực hiện phép tính | 3 | 2 | 1 | 6 | 3,0 |
| Biểu thức / biến đổi tương đương | 2 | 3 | 1 | 6 | 3,0 |
| Phương trình / giải và lập phương trình | 3 | 3 | 2 | 8 | 4,0 |
| **Tổng** | **8** | **8** | **4** | **20** | **10,0** |

Tỷ lệ theo số câu: 40% / 40% / 20%. Vì điểm mỗi câu bằng nhau, tỷ lệ theo điểm cũng trùng; điều này không đúng cho mọi blueprint. Không gán các cột trên thành dễ/trung bình/khó thực nghiệm.

Schema minh họa rút gọn, không phải API đã triển khai:

```json
{
  "schema_version": "1.0",
  "origin_kind": "teacher_defined",
  "verification_status": "not_official",
  "mode": "mock",
  "version_no": 1,
  "title": "Mẫu minh họa Toán — không chính thức",
  "duration_seconds": 1800,
  "total_items": 20,
  "total_points": "10.00",
  "matrix_counting": "one_primary_cell_per_item",
  "cognitive_taxonomy_version": "illustrative-v1",
  "sections": [
    {
      "key": "single-choice",
      "position": 1,
      "allowed_item_types": ["single_choice"],
      "item_count": 20,
      "points_per_item": "0.50",
      "total_points": "10.00"
    }
  ],
  "capabilities_required": ["single_choice", "global_timer"],
  "allow_constraint_relaxation": false
}
```

JSON trên chỉ minh họa envelope. Bản publish phải có matrix cell IDs, curriculum/skill references, quyền nguồn, đầy đủ constraints và reviewer; không được publish chỉ với JSON rút gọn này.

## 7. Pipeline tạo đề

### Bước 1 — Resolve và authorize

Chọn exact blueprint version, mode, workspace và purpose. Core xác minh actor, scope, trạng thái/hiệu lực, catalog entitlement và quyền nguồn. Client không được truyền actor hoặc workspace giả làm quyền.

### Bước 2 — Validate blueprint và capability

Kiểm tra schema version hỗ trợ, tổng số câu/điểm, matrix coverage, ràng buộc section/group, timing và quyền export. Nếu có `short_answer`, `essay` hoặc timer chưa hỗ trợ trong MVP, trả lỗi rõ `UNSUPPORTED_CAPABILITY`; không bỏ câu, đổi type hoặc dùng single-choice thay thế.

### Bước 3 — Expand slots

Tạo manifest slot xác định: section, primary cell, kỹ năng phụ, item type, points, group membership, source restrictions và tiêu chí chọn. Validation phát hiện cấu trúc không thỏa ngay trước khi tốn phí AI.

### Bước 4 — Chọn ngân hàng đã duyệt

Lọc SQL trong scope được phép trước khi nội dung rời database. Ưu tiên published question revisions hợp lệ; tránh trùng và quá gần trùng, kiểm soát exposure phù hợp. Lưu seed/selection policy nếu dùng random để truy nguyên; seed không thay cho exact snapshot IDs.

### Bước 5 — Sinh phần thiếu có giới hạn

Nếu policy cho phép, AI tạo candidate cho slot còn thiếu trên nguồn được phép. Giới hạn số lần gọi, tokens, repair attempts và ngân sách. Provider output là dữ liệu không đáng tin, không phải lệnh. Candidate chưa phải câu đã duyệt.

### Bước 6 — Validation nhiều lớp

- Deterministic: schema, type, option/key, điểm, matrix, trùng ID, quyền nguồn và nhóm câu.
- Chuyên môn/hỗ trợ AI: dữ kiện, tính rõ ràng, đáp án, lời giải, phù hợp chương trình và tính hợp lý thời gian.
- Kiểm tra công thức bằng công cụ xác định nơi phù hợp; không coi một LLM khác đồng ý là bằng chứng chắc chắn.

AI checks có giới hạn, **không đảm bảo độ chính xác nội dung**. Lỗi hoặc nghi ngờ được giữ trong report và chuyển review.

### Bước 7 — Draft và review

Tạo draft kèm manifest, nguồn/provenance, kết quả validation, các slot thiếu và cảnh báo. Giáo viên hoặc reviewer được phân quyền sửa/thay câu. Mỗi thay đổi làm chạy lại các validation bị ảnh hưởng.

### Bước 8 — Publish atomic

Chỉ publish khi tất cả hard constraints và review policy được đáp ứng. Freeze exam version, items, options, keys, rubric, passage, objective mappings, blueprint version/hash và manifest. Assignment tham chiếu exact exam version. Sửa sau publish tạo version mới, không thay đề đã giao.

### Không âm thầm nới cấu trúc

Nếu thiếu 2 câu vận dụng thuộc một kỹ năng, trả shortage report theo slot/cell. Các lựa chọn hợp lệ:

- Bổ sung câu đã duyệt.
- Cho AI tạo draft để review.
- Chọn blueprint khác.
- Người có quyền tạo revision blueprint mới với thay đổi rõ ràng, rồi validate lại.

Không tự chuyển sang chủ đề gần giống, giảm số câu, đổi tổng điểm hoặc lấy câu từ workspace khác. Một đề còn thiếu không được gắn trạng thái ready-to-publish.

## 8. Chính sách luyện tập cá nhân và nội dung AI

Để tránh vòng lặp “AI sinh câu → AI tự tin chấm → hệ thống kết luận học sinh yếu”, tách hai luồng:

### A. Pool đã xác minh và publish

Core quản lý câu, key, publication và scoring. Student-learning service yêu cầu tạo practice session từ pool có entitlement, nhận student-safe items và kết quả được release. Pool này dùng làm bằng chứng chính cho checkpoint và hồ sơ kỹ năng, theo policy chất lượng đã version hóa.

### B. AI exercises có nhãn

Có thể cung cấp bài giải thích/luyện bổ sung với nhãn rõ: “Bài luyện do AI tạo, chưa được chuyên môn duyệt”.

- Không gọi là đề thi chính thức hoặc mock chuẩn.
- Không tự đưa vào verified pool.
- Không cấp điểm chính thức từ LLM; phản hồi chỉ mang tính hỗ trợ.
- Không dùng trực tiếp làm bằng chứng mastery có trọng số tương đương verified assessment. MVP có thể loại hoàn toàn khỏi cập nhật mastery; thay đổi sau cần evaluation và policy riêng.
- Có báo lỗi nội dung, lưu model/prompt/source version và giới hạn chi phí.
- Muốn chuyển sang bài có điểm authoritative: đi qua core candidate → validation → review → publish, không sửa nhãn ở client.

## 9. Versioned schemas và logical data model

### 9.1 Nguyên tắc schema

`schema_version` mô tả cấu trúc payload; `version_no` mô tả nội dung blueprint. Đây là hai version khác nhau. Unsupported major schema bị từ chối rõ ràng. Migration giữa schema tạo bản chuyển đổi có validation và provenance; không rewrite lịch sử đã publish.

Dữ liệu relational giữ quan hệ/authority; JSONB chỉ chứa payload có schema và giới hạn kích thước. Tenant-owned tables có non-null workspace ID, RLS và composite tenant FK theo database design hiện tại.

### 9.2 Bảng logical đề xuất

| Nhóm | Thực thể | Vai trò |
|---|---|---|
| Tenant core | `exam_blueprints` | ID ổn định, workspace owner, loại nguồn, tên, trạng thái |
| Tenant core | `exam_blueprint_versions` | Version, schema version, hiệu lực, metadata snapshot, hash, reviewer/published timestamps |
| Tenant core | `exam_blueprint_sections` | Section versioned, type/count/points/timing constraints |
| Tenant core | `exam_blueprint_cells` | Topic/skill/cognitive mapping và quota của ma trận |
| Tenant core | `exam_blueprint_group_rules` | Passage/group size, ordering, dependency và distribution constraints |
| Tenant core | `exam_blueprint_evidence` | Nguồn tham chiếu, quyền, xác minh và nội dung sai khác |
| Catalog riêng | `catalog_exam_blueprints`, `catalog_exam_blueprint_versions` | Mẫu do control plane quản trị, không phải public tenant rows |
| Catalog riêng | Các bảng section/cell/group/evidence catalog | Quan hệ cùng catalog version, giữ chính sách truy cập độc lập |
| Entitlement | `workspace_blueprint_entitlements` | Workspace được phép dùng catalog version/phạm vi nào, operations, khoảng hiệu lực |
| Assembly core | `exam_assembly_jobs`, `exam_assembly_slots` | Job durable, manifest, slot demand/candidate, shortage và validation report |
| Publication core | `exam_blueprint_bindings` | Exam version gắn đúng một private hoặc catalog blueprint version cùng hash |
| Existing assessment | `exam_versions`, `exam_items`, `answer_keys`, `quiz_attempts`, `grading_results`, `grades` | Giữ authority hiện có; không sao chép thành hệ điểm riêng |

Các bảng trên mô tả teacher/core blueprint foundation, chưa đủ cho self-study độc lập. Trước L1 bổ sung learner-scoped catalog entitlements và core-owned standalone assessment/publication references theo [DATABASE.md, mục 16](DATABASE.md#16-blueprint-skills-and-independent-learner-extensions-proposed). Không cấp workspace entitlement giả cho học sinh độc lập; không tái dùng assignment-centric quiz_attempts bằng cách bỏ workspace constraint. Ghi quyết định schema cụ thể trước mở API self-study.

Các bảng catalog không dùng policy “mọi authenticated user được SELECT”. Access qua core API hẹp có kiểm tra entitlement/operation và ngày hiệu lực. Tenant staff không tự tạo nhãn catalog verified.

Binding dùng hai FK có kiểu rõ, private version hoặc catalog version, với CHECK đúng một target. Private target có composite tenant FK. Catalog target cần cả FK và entitlement check khi assembly/publish/delivery/export; FK đơn thuần không chứng minh quyền. Không dùng cặp `resource_type/resource_id` không có integrity checks làm liên kết authoritative.

Question empirical statistics và learner skill estimates là dữ liệu khác nhau, có cohort/model versions; không nhét chung vào blueprint và không sửa blueprint mỗi khi một học sinh làm bài.

## 10. Ranh giới core và student-learning service

Core assessment là nguồn sự thật về câu đã publish, đề, key, attempt, scoring, release và grade. Student-learning service sở hữu mục tiêu, kế hoạch học và projection hồ sơ kỹ năng, **không sở hữu hệ chấm điểm thứ hai**.

- Student-learning gọi API publication/delivery/scoring của core qua danh tính service hẹp và context người học đã xác thực.
- Không đọc/ghi trực tiếp bảng core, không nhận đáp án thô, private key, rubric bí mật hoặc teacher export.
- Mọi attempt start/save/submit và deadline đều do core kiểm tra; service không gửi score hoặc `is_correct` để core tin.
- Core trả DTO learner-safe và evaluation evidence đã được phép release. Trước release, kết quả chi tiết có thể là pending; không dùng learner analytics API để vượt chính sách giấu lời giải.
- Phần giải thích được release do core cung cấp theo policy; việc đã release cho học sinh không mở quyền đọc key tables.
- Evidence event có event ID, attempt/result revision và policy version để idempotent projection. Regrade/void/revocation phải tạo sự kiện điều chỉnh; learner projection có thể rebuild từ API/event contract được cho phép.
- Lịch sử lớp thuộc workspace không tự nhập vào hồ sơ tự học toàn cục. Cần scope/consent và policy chia sẻ phù hợp.

Ở giai đoạn modular monolith có thể hiện thực ranh giới bằng service interface nội bộ. Nếu tách process sau này, giữ hợp đồng API/event tương đương; không dùng shared database access làm shortcut.

## 11. API đề xuất — chưa implement

Các đường dẫn dưới đây minh họa hợp đồng, không phải cam kết endpoint đang hoạt động.

| API | Mục đích |
|---|---|
| `POST /v1/workspaces/{w}/exam-blueprints` | Tạo blueprint private draft |
| `POST /v1/workspaces/{w}/exam-blueprints/{id}/versions` | Tạo revision mới, dùng optimistic concurrency |
| `POST /v1/workspaces/{w}/exam-blueprints/{id}/versions/{v}/validate` | Trả lỗi schema/capability/matrix/rights |
| `POST /v1/workspaces/{w}/exam-blueprints/{id}/versions/{v}/publish` | Kiểm tra reviewer, freeze blueprint version |
| `GET /v1/workspaces/{w}/available-blueprints` | Liệt kê private + catalog entitled qua DTO, phân biệt owner/source |
| `POST /v1/workspaces/{w}/exam-assemblies` | Pin blueprint version, reserve quota, tạo job/outbox; trả 202 |
| `GET /v1/workspaces/{w}/exam-assemblies/{id}` | Progress, shortage/validation report được phân quyền |
| `POST /v1/workspaces/{w}/exams/{id}/publish` | Publish immutable exam version theo core hiện có |
| `POST /v1/learning-assessments/sessions` | Service-facing: tạo diagnostic/practice/mock từ publication được phép |
| `GET /v1/learning-assessments/sessions/{id}` | Student-safe delivery và trạng thái |
| `POST /v1/learning-assessments/sessions/{id}/submit` | Đi qua core attempt submission, không nhận điểm từ caller |
| `GET /v1/learning-assessments/sessions/{id}/evidence` | Evidence đã release và revision metadata, không raw answer keys |

Control-plane catalog verification/publish có API riêng, quyền riêng và audit; không tái sử dụng tenant admin authority.

Mutation quan trọng có idempotency key scoped actor/owner/operation và request hash: owner là workspace cho teacher routes, learner cho standalone self-study routes, không ép workspace giả. Reuse key khác payload trả conflict. Các lỗi cần mã ổn định: `UNSUPPORTED_SCHEMA`, `UNSUPPORTED_CAPABILITY`, `BLUEPRINT_INFEASIBLE`, `INSUFFICIENT_REVIEWED_ITEMS`, `ENTITLEMENT_REQUIRED`, `SOURCE_WITHDRAWN`, `VERSION_CONFLICT`. Response không tiết lộ dữ liệu/ID private của tenant khác qua shortage hoặc error diagnostics.

## 12. Roadmap thực hiện

### Giai đoạn 1 — Blueprint foundation trong MVP giáo viên

- Private blueprint, versioning, fixed count/points matrix, single-choice, global timer.
- Catalog metadata/entitlement contract được thiết kế nhưng chỉ mở catalog có quyền nguồn và quy trình duyệt thực tế.
- Manual authoring → validate → review → publish và binding exact exam version.
- Chưa có solver nhiều điều kiện mềm, adaptive diagnostic hoặc rubric tự luận.

### Giai đoạn 2 — Assembly và ngân hàng đã duyệt

- Slot expansion, authorized pool selection, shortage report, provenance.
- AI candidate generation có quota, bounded repair, review và evaluation set.
- DOCX/PDF teacher/student tách biệt; validation quyền nguồn trước export.

### Giai đoạn 3 — Student self-study integration

- Core service contract cho verified practice, diagnostic cố định và mock.
- Tách exercise AI có nhãn khỏi scored evidence.
- Evidence events có version/regrade, kiểm tra privacy và release.

### Giai đoạn 4 — Dạng câu và cấu trúc nâng cao

- Chỉ thêm short-answer/essay khi có UI, validation, rubric, scoring/review và tests end-to-end.
- Timer theo phần, passage phức tạp, randomized forms hoặc adaptive diagnosis có capability riêng.
- Hiệu chỉnh difficulty dựa trên cohort có đủ bằng chứng; không đặt ngưỡng phổ quát chưa đánh giá.

## 13. Acceptance tests và release gates

### Cấu trúc và toán học

- Mẫu minh họa trên expand đúng 20 slots, 10 điểm; hàng 6/6/8 và cột 8/8/4.
- Điểm từng section/cell không trùng đếm khi item có nhiều kỹ năng.
- Blueprint bất khả thi, quota âm, thiếu scope, passage bị tách hoặc tổng điểm sai bị từ chối.
- `essay`/`short_answer`/section timer chưa hỗ trợ trả lỗi explicit, không chuyển loại âm thầm.

### Sinh đề và chất lượng

- Thiếu reviewed candidates trả đủ shortage slots và không publish.
- Retry cùng assembly không tạo duplicate publication hoặc duplicate ledger cho cùng provider execution.
- AI output sai schema/không rõ đáp án hết repair budget thì failed/review, không tự duyệt.
- Bộ evaluation chuyên môn kiểm tra nguồn, đáp án, câu mơ hồ và consistency; ghi tỷ lệ lỗi theo corpus thay vì tuyên bố đảm bảo đúng.
- Mock giữ cấu trúc bất kể hồ sơ điểm yếu; personalized practice luôn mang nhãn đúng.

### Version và bất biến

- Sửa blueprint/question bank không đổi exam/attempt đã publish.
- Archive không biến published payload trở lại editable.
- Source withdrawal ngăn phân phối mới theo policy nhưng không sửa lịch sử điểm.
- Reviewer có quyền hiện tại; ghi hash/version/actor/time khi publish.

### Security và tích hợp

- Tenant A không dùng blueprint, candidate hoặc key của tenant B; test dưới runtime DB role thực.
- Catalog không có entitlement hoặc hết hiệu lực bị từ chối ở assembly, publish, delivery và export thích hợp.
- Student-learning credentials không SELECT core tables và không gọi teacher/key API.
- Student API, SSR, error payload, logs, exports không chứa unreleased key/solution.
- Duplicate evidence, out-of-order regrade và void không làm double-count mastery; projection giữ result revision.
- Không nhập điểm lớp vào hồ sơ tự học ngoài scope/consent cho phép.

### Timing, scoring và vận hành

- Deadline server-authoritative, submit/autosave race và late payload tuân theo core.
- AI outage không chặn đề đã publish hoặc chấm single-choice deterministic.
- Worker crash/broker loss recovery không đổi manifest đã publish.
- Audit đủ để giải thích đề sinh từ cấu trúc nào, câu/version nào, ai duyệt, model nào được dùng và có thay đổi gì.

## 14. Những quyết định cần chốt trước implementation

1. Một môn/khối/kỳ kiểm tra đầu tiên và nguồn cấu trúc được phép dùng.
2. Taxonomy nhận thức và quy ước primary matrix cell.
3. Ai đủ quyền xác minh catalog, ai duyệt câu và ai publish đề.
4. Blueprint hiệu lực theo địa phương/năm được cập nhật và thông báo như thế nào.
5. Rubric và scoring/release policy cho từng mode; MVP giữ single-choice.
6. Ngân hàng câu hỏi tối thiểu và evaluation corpus trước khi cho học sinh tự luyện.
7. Policy AI exercises: MVP không cập nhật mastery từ nội dung chưa duyệt.
8. Cơ chế entitlement và chia sẻ dữ liệu giữa lớp học và hồ sơ tự học.

**Nguyên tắc chốt:** cá nhân hóa kế hoạch học, nhưng không làm sai cấu trúc thi thử; AI hỗ trợ tạo và kiểm tra nội dung, nhưng authority về quyền, publication, thời gian và điểm nằm trong core xác định và có audit.
