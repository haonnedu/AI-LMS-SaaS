# BASE-01 / BASE-05 — ổn định tooling và CI

Người thực hiện: Codex theo yêu cầu người dùng, 2026-10-21. Branch `fix/tooling-ci`, base `302762ba81a545f993728b268b639e571bd6ad36` cộng diff chưa commit. Owner task hiện có không thay đổi; chưa có reviewer con người xác nhận nghiệm thu.

## Thay đổi

- Setup: Python version probe không chứa quote bị PowerShell 5.1 loại bỏ; interpreter không chạy được/sai phiên bản trả lỗi rõ. Giữ nguyên các tham số, kiểm tra virtualenv hiện có và không tự xóa/thay thế môi trường.
- Verifier: kiểm tra bootstrap riêng, lấy single head từ Alembic trong backend image, xác nhận ba bảng identity ở head, upgrade lặp, downgrade/base và upgrade khôi phục. Các bảng kỳ vọng vẫn explicit để thay đổi schema mới phải được review.
- Tiếp tục kiểm tra 11 trang production, direct health/readiness/proxy, outage/recovery từng dependency. Timeout build 900s, Compose còn lại 180s, Git 15s; lỗi vẫn thử cleanup. Report/log ghi failed step và che credential của lượt chạy; cleanup fail không thể báo passed.
- Regression tests: setup trên PowerShell 5.1/7, check-only không ghi file, path/version sai, virtualenv hỏng được giữ nguyên; verifier bảo vệ project/environment, phát hiện sai revision/tables, timeout, redaction, failure/cleanup lifecycle.
- Foundation workflow: thêm job scripts Windows/Linux từ lock backend hiện có; job containers Ubuntu chạy verifier đầy đủ thay cho build-only. Upload riêng result.json/commands.log; không upload compose.env. Không đổi workflow MCP.
- Development guide cập nhật hiện trạng UI/schema và hướng dẫn scripts; tracker ghi ngoại lệ không cần evidence máy thứ hai theo yêu cầu người dùng. Không sửa task status.

## Evidence kiểm chứng

Python local và Linux: 3.12.15; Ruff 0.17.1. Windows chạy cả `powershell.exe` 5.1 và `pwsh.exe` 7. Linux unit tests chạy trong image Python dùng digest của backend, cài `backend/requirements-dev.lock`, không dựa vào môi trường MCP.

| Kiểm tra | Kết quả |
|---|---|
| `python -m ruff check --config backend/pyproject.toml scripts` | Exit 0, Windows và Linux |
| `python -m ruff format --check --config backend/pyproject.toml scripts` | Exit 0, Windows và Linux |
| `python -m pytest -c backend/pyproject.toml scripts/tests -q` trên Windows | Exit 0, 35 passed; có cả hai PowerShell |
| Cùng bộ tests trên Linux | Exit 0, 19 passed, 16 skipped (setup Windows) |
| Backend `ruff check .`, `ruff format --check .`, `pytest -q` | Exit 0, 16 passed; 1 deprecation warning TestClient/httpx, không thay dependency |
| Export OpenAPI ra tmp và so sánh contract committed | Exit 0, giống sau chuẩn hóa newline |

### Integration thật bằng verifier cập nhật

Lệnh từ repo root: `backend/.venv/Scripts/python.exe scripts/verify-m0.py`. Docker Desktop chạy Linux containers; Python orchestration trên Windows. Đây không phải run trên GitHub Ubuntu runner.

- Project riêng: `eduvia-m0-20261021t072432z-50bbfb34`.
- Cổng loopback: PostgreSQL 50288, Redis 50289, API 50290, frontend 50291.
- Source image build từ base cộng diff scripts lúc chạy; không thay code backend/frontend/schema hoặc dependency lock.
- Bootstrap: revision `0001_bootstrap`, có `edu`/`vector`, chưa có bảng nghiệp vụ.
- Head lấy từ Alembic: `0002_identity_and_workspaces`; tables xác nhận `users`, `workspace_members`, `workspaces`.
- Upgrade head hai lượt pass. Downgrade base gỡ `edu`, giữ `vector`; upgrade khôi phục đúng head/tables.
- 11 route production đều HTTP 200, render Eduvia; API live/ready/proxy đúng contract.
- Mất PostgreSQL hoặc Redis: live 200, ready 503 chỉ đúng dependency mất; proxy live vẫn 200. Start lại phục hồi ready/proxy 200.
- Mất API: proxy 503 mã `backend_unavailable`, phản hồi sau 4.031s; API phục hồi trả 200.
- Result `passed`; cleanup project containers/network/volumes/images `passed`; env file đã xóa.
- Kết thúc 2026-10-21 **14:25:34 +07:00**. Raw artifacts local: `tmp/eduvia-m0-20261021t072432z-50bbfb34/result.json` và `commands.log`; kết quả cần chia sẻ đã tóm tắt tại đây vì tmp không commit.

Git blob của source script đã kiểm chứng:

- `scripts/setup.ps1`: `b2ddc80106a85fe2463d0bb0518251cc0da79a72`.
- `scripts/verify-m0.py`: `108db8da83e90015f7309c12544d35d1ec3ea904`.

## Review và giới hạn

- CI xanh của base [302762b](https://github.com/haonnedu/AI-LMS-SaaS/actions/runs/39560321514) khép lỗi lint migration D-01; không thay kết quả CI cho branch tooling mới.
- Chưa commit/push; cần reviewer xem diff theo SHA mới và xác nhận scripts jobs Windows/Linux cùng containers/backend/frontend pass sau push. Cập nhật [REVIEW.md](REVIEW.md) với link run và SHA khi có.
- Không triển khai DB roles/RLS, auth, provisioning, pilot hay hosting. Các findings D-02..D-06 giữ nguyên; D-07 mới đồng bộ development guide, chưa đồng bộ database design document.
- Không đòi evidence máy thứ hai: người dùng đã miễn, không phải tuyên bố chạy trên hai máy.
- Bàn giao cùng các file scripts/tests, Foundation workflow, development guide, discuss và execution record BASE-01. Không stage file tmp hoặc secrets; không tự ghi reviewer approval hay task done.
