# Backlog học sinh tự học — L0–L4

> Kế hoạch chưa triển khai; mọi task khởi tạo `todo`, Owner `—` (chưa phân công). Đây không phải xác nhận tính năng đã có.

Nguồn: [Student learning](../STUDENT_LEARNING.md), [kế hoạch triển khai](../IMPLEMENTATION_PLAN.md), [Exam blueprints](../EXAM_BLUEPRINTS.md). Quy ước nhận việc và **gates M1, M2, M4, M5, M6, M7** xem [backlog tổng](BACKLOG.md); dependency là điều kiện có bằng chứng nghiệm thu, không phải lịch cố định. Nhánh [school](SCHOOL.md) không là prerequisite của học sinh độc lập.

Core giữ identity/catalog/rights và authoritative attempts/submissions/scoring; learner domain giữ profile/goals/plans/evidence projections. Bắt đầu bằng diagnostic cố định, rule-based planner và pool đã duyệt. Có thể module-first qua application ports; extraction/deploy riêng chỉ khi đủ gate, không phải yêu cầu để hoàn thành self-study MVP. L4 là nhánh nghiên cứu có điều kiện, không chặn L2/L3 nếu chưa đủ dữ liệu.

## L0 — Curriculum, skills và nội dung được duyệt

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| L0-01 | todo | — | M4 | Chốt một môn/khối/chương trình và use case pilot; lập inventory nguồn/câu hỏi có quyền dùng, curriculum version và expert reviewer; thiếu nội dung hoặc quyền phải được ghi rõ, không tự gắn nhãn đề chính thức. |
| L0-02 | todo | — | L0-01 | Migration core skill/prerequisite catalog và question-skill mappings có version/provenance; tests cycle, missing prerequisite, reference version và immutable published mapping; cognitive demand tách empirical difficulty. |
| L0-03 | todo | — | L0-02 | Làm API catalog/version lookup cùng UI nội bộ review mapping/coverage; chỉ trả metadata theo rights, có withdrawn/version-conflict states và audit reviewer, không copy answer keys sang learner catalog. |
| L0-04 | todo | — | L0-03; M6 | Chuẩn hóa DTO per-item result/skill evidence từ canonical scoring và release policy; fixtures cho correctness/assistance/result version, test không lộ key/unreleased rubric trong API/SSR/cache/log. |
| L0-05 | todo | — | L0-04 | Expert review pool diagnostic/practice và checkpoint câu chưa gặp; kiểm tra coverage theo skill/blueprint, định nghĩa shortage behavior rõ, lưu fixtures và kết quả validation trước dùng cho learner. |

## L1 — Learner ownership và hợp đồng core

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| L1-01 | todo | — | M1; M2; M6 | Chốt ADR personal learner identity/ownership, minimal data, age/guardian/legal review và module-first hoặc extraction có điều kiện; core vẫn là scoring authority, không tạo class/workspace giáo viên giả hoặc nullable tenant bypass. |
| L1-02 | todo | — | L1-01 | Migration learner profile/preferences/goals/availability/consent với owner scope và runtime-role isolation; identity dựa issuer/subject không email, test concurrent bootstrap, learner A/B và teacher không enumerate profile. |
| L1-03 | todo | — | L1-02; L0-05 | Mở rộng core standalone personal-assessment aggregate/capabilities, migrations và API start/save/submit/result lookup; kiểm tra entitlement/rights/deadline/idempotency, retry timeout không tạo attempt trùng; không tạo grade authority ở student. |
| L1-04 | todo | — | L1-03 | Implement learner API contracts qua application ports/adapters và OpenAPI/types; verified subject/audience/scope, purpose-bound delegation, optimistic revision và request hash conflict; tests revoked grant/account, không direct core repository/SQL joins hoặc FK xuyên boundary. |
| L1-05 | todo | — | L1-04 | Migration local outbox/inbox và versioned event contracts; projector nhận authorized result references tối thiểu, dedupe/order/gap/quarantine/reconcile có tests; bus không chứa raw answers/keys, event không thay authorization lúc fetch. |
| L1-06 | todo | — | L1-05 | Làm consent/revoke/deletion API và UI phạm vi rõ; chặn jobs/import, xử lý derived evidence theo policy, phối hợp core personal assessment, tombstones/ack/retry; tests replay/restore không resurrect và không hứa xóa classroom records ngoài authority. |
| L1-07 | todo | — | L1-06 | Lập và review extraction readiness checklist: auth/recovery/deletion/contracts, workload/release benefit, owner vận hành, quota, backup/rollback; nếu chưa đạt giữ module-first; chỉ khi được duyệt mới tách DB/roles/workers, diễn tập snapshot+watermark+single-writer cutover và rollback không dual-write. |

## L2 — Self-study MVP dựa trên rules

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| L2-01 | todo | — | L0-05; L1-07 | API/UI onboarding mục tiêu và lịch học cho một use case pilot; xác thực curriculum refs, timezone/minute budget và current lesson, không suy ra tiến độ trường từ bộ sách; loading/empty/conflict/consent states được test. |
| L2-02 | todo | — | L2-01 | Implement diagnostic cố định từ pool đã duyệt qua core assessment, không adaptive trước; UI làm bài/submit/pending result, timeout query idempotency thay báo thành công giả; chỉ canonical released evidence được dùng. |
| L2-03 | todo | — | L2-02 | Migration evidence/mastery projections và rule-based projector versioned; phân biệt assisted/unassisted, insufficient evidence/confidence/as_of; fixtures regrade/void/revoke/replay không double-count, không gắn nhãn năng lực từ một quiz. |
| L2-04 | todo | — | L2-03 | Implement weekly rule planner với goals, prerequisites, availability và authorized evidence; lưu plan/input watermark/rule version/reasons, budget không vượt thời gian, đổi lịch tạo version mới; tests thiếu dữ liệu, source withdrawn và replan debounce. |
| L2-05 | todo | — | L2-04 | UI Hôm nay/Kế hoạch/Tiến bộ và practice orchestration qua core; giải thích vì sao task, ước lượng thời lượng, freshness/lag/pending; checkpoint dùng câu mới, không tăng mastery chỉ từ điểm browser hoặc câu lặp có trợ giúp. |
| L2-06 | todo | — | L2-05; M7 | E2E learner độc lập onboarding → diagnostic → tuần học → practice → checkpoint; test A/B, teacher/school không tự xem self-study, core/student outage và learner quotas; expert review lộ trình/ngôn ngữ, ghi pilot go/no-go với privacy/recovery evidence. |

## L3 — Mock exam theo cấu trúc

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| L3-01 | todo | — | L2-06; M4; M6 | Review blueprint catalog/version/provenance/effective year và content coverage theo kỳ thi mục tiêu; API/UI chọn blueprint hiển thị rõ verified scope hoặc practice-only, không gọi đề chính thức khi chưa có bằng chứng. |
| L3-02 | todo | — | L3-01 | Implement request mock bám immutable blueprint trong core; fixtures section/count/points/matrix và supported item types, shortage/unsupported fail rõ; planner không tự đổi phân bố hoặc thay loại câu để đủ đề. |
| L3-03 | todo | — | L3-02 | UI timed mock/autosave/reconnect/submit qua core authoritative deadline/state; test duplicate submit, hết giờ, network timeout và student-safe rendering; không gợi ý/lộ giải trước release hoặc tự chấm ở frontend. |
| L3-04 | todo | — | L3-03 | API/UI phân tích kết quả theo phần/skill với result version, coverage và uncertainty; planner điều chỉnh tuần theo deadline/trọng số nhưng không sửa đề đã phát; pending/unsupported essay không biến thành điểm LLM chính thức. |
| L3-05 | todo | — | L3-04 | Chạy golden blueprint/scoring fixtures và E2E mock → release → regrade → replan; kiểm tra exports/logs/cache không rò key, quyền nguồn bị thu hồi được xử lý, chuyên môn xác nhận báo cáo không hứa điểm thi. |

## L4 — Cá nhân hóa nâng cao có điều kiện

| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |
|---|---|---|---|---|
| L4-01 | todo | — | L3-05 | Đánh giá chất lượng/cỡ dữ liệu, consent/retention và benchmark so rule baseline; chuyên môn chốt metrics và harm thresholds; nếu không đủ ghi no-go và tiếp tục rules, không bắt buộc bật adaptive. |
| L4-02 | todo | — | L4-01 | Chỉ sau go: dựng pipeline empirical item-difficulty calibration trên dữ liệu được phép, version model/fixtures và migration artifact metadata khi cần; phân biệt difficulty với cognitive demand, loại leakage/assisted bias và báo uncertainty. |
| L4-03 | todo | — | L4-02 | Thử adaptive diagnostic/knowledge tracing/spaced review sau feature flag, giới hạn rules fallback; offline tests và controlled evaluation so baseline, không đổi mock blueprint hoặc canonical scoring, có rollback model version. |
| L4-04 | todo | — | L4-03 | API/UI giải thích recommendation nâng cao và tùy chọn tutor giới hạn nếu được duyệt scope; không gửi PII không cần tới provider, không lộ key, không official grading bằng LLM; red-team harmful labeling, prompt injection và privacy leakage. |
| L4-05 | todo | — | L4-04 | Review lợi ích/harm/cost theo cohort và evidence đủ điều kiện; ghi go/no-go, monitoring/drift alerts/rollback và deletion cho derived model artifacts theo policy; giữ rules nếu chưa chứng minh cải thiện, không dùng raw score hoặc time-online làm bằng chứng duy nhất. |

**Tổng: 28 task; L0-01–L0-05, L1-01–L1-07, L2-01–L2-06, L3-01–L3-05, L4-01–L4-05.**
