# Eduvia MCP — source và backlog

MCP server local, **chỉ đọc**, chạy bằng stdio. Server đọc trực tiếp checkout Eduvia,
không cần FastAPI, PostgreSQL, Redis, Git executable, API key hoặc LLM. Không sửa
file, đổi trạng thái task, chạy shell hay gọi API nghiệp vụ.

## Cài đặt

Cần [uv](https://docs.astral.sh/uv/getting-started/installation/) và Python 3.12.
Chạy từ root repository:

```powershell
uv sync --project tools/eduvia-mcp --locked --python 3.12
```

`uv` tạo virtualenv riêng `tools/eduvia-mcp/.venv`; nếu cần, uv tải Python 3.12.
Dependency SDK chính thức được pin tại `mcp==2.3.0`; `uv.lock` khóa cả dependencies
runtime và dev. Việc cài đặt cần mạng; server đã cài chạy hoàn toàn local.
Không dùng virtualenv của backend hoặc Python 3.11 trên PATH.

Chạy bằng launcher Windows, từ root repo hoặc truyền root tuyệt đối:

```powershell
.\tools\eduvia-mcp\scripts\start.ps1
.\tools\eduvia-mcp\scripts\start.ps1 -RepoRoot 'D:\Data\Git_Space\AI-LMS-SaaS'
```

Lệnh entry point sau khi kích hoạt virtualenv:

```text
eduvia-mcp --repo-root D:/Data/Git_Space/AI-LMS-SaaS
```

Đây là tiến trình giao thức, không có giao diện terminal. MCP client sẽ khởi chạy
tiến trình và giao tiếp qua stdin/stdout. Log chỉ ghi stderr. Root bắt buộc tồn tại,
là đường dẫn tuyệt đối, chứa các marker manifests/frontend/backend và backlog Eduvia.

## Kết nối MCP client

File `mcp-client.example.json` là cấu hình mẫu cho client dùng khóa `mcpServers`.
Thay hai đường dẫn tuyệt đối cho đúng checkout của bạn. Có thể dùng trực tiếp
interpreter virtualenv để không phụ thuộc activation, cwd hoặc PATH:

```json
{
  "mcpServers": {
    "eduvia-source": {
      "command": "D:/Data/Git_Space/AI-LMS-SaaS/tools/eduvia-mcp/.venv/Scripts/python.exe",
      "args": [
        "-m", "eduvia_mcp.server", "--repo-root",
        "D:/Data/Git_Space/AI-LMS-SaaS"
      ]
    }
  }
}
```

Linux dùng `<checkout>/tools/eduvia-mcp/.venv/bin/python` và root POSIX tuyệt đối.
Nếu client có định dạng cấu hình khác, giữ nguyên executable và arguments trên.
Package không tự sửa cấu hình MCP của ứng dụng.

## Bảy tool

| Tool | Input | Kết quả |
|---|---|---|
| `get_project_overview` | Không | Stack lấy từ manifests, cấu trúc, tài liệu |
| `list_files` | `path="."`, `offset=0`, `limit=50` | File UTF-8 được phép đọc, kích thước |
| `read_file` | `path`, `start_line=1`, `line_count=200` | Dòng có số thứ tự, `next_line` |
| `search_source` | `query`, `path="."`, `offset=0`, `limit=50` | Tìm literal phân biệt hoa/thường; một snippet mỗi dòng |
| `get_backlog_summary` | Không | Tổng task theo track/status/owner/milestone |
| `list_tasks` | `track`, `status`, `owner`, `milestone`, `query`, `offset=0`, `limit=50` | Task phù hợp và vị trí nguồn |
| `get_task` | `task_id` | Task, dependency phân loại, các task phụ thuộc trực tiếp |

Các filter `list_tasks` đều tùy chọn và kết hợp AND. `track` nhận `core`, `school`,
`student`, `omr_billing`. `status` nhận `todo`, `ready`, `in_progress`, `review`,
`blocked`, `done`, `cancelled`. Owner/milestone khớp chính xác; `query` tìm không
phân biệt hoa/thường trong ID và mô tả. `get_task` yêu cầu ID chính xác.

Thử các yêu cầu sau trong MCP client:

- `get_backlog_summary {}`
- `list_tasks {"track":"core","milestone":"M0","status":"todo"}`
- `get_task {"task_id":"BASE-01"}`
- `search_source {"query":"create_app","path":"backend/app"}`
- `read_file {"path":"backend/app/main.py","start_line":15,"line_count":30}`

Kết quả có `data`, `error`, `truncated`. Lỗi nghiệp vụ nằm trong `error` với mã
`ACCESS_DENIED`, `NOT_FOUND`, `INVALID_INPUT`, `PARSE_ERROR` hoặc `IO_ERROR`.
Input sai kiểu/enum bị SDK từ chối theo JSON Schema của tool.

Danh sách có `total`, `offset`, `next_offset`; đọc file có `total_lines`, `next_line`.
Theo cursor để lấy tiếp; không giả định luôn nhận đủ `limit`. File và kết quả tìm
kiếm sắp theo path/dòng; task giữ thứ tự tracker rồi dòng. Mỗi lần gọi đọc dữ liệu
mới, không bảo đảm snapshot giữa hai lần gọi nếu người dùng đang sửa repo.

## Quy tắc backlog

Nguồn trạng thái là bốn tracker trong `tasks/`; không suy ra completion từ source.
Parser đọc bảng ID/Trạng thái/Owner/Phụ thuộc/Task, hỗ trợ tiếng Việt và escaped pipe,
bỏ qua bảng quy ước và fenced code. ID trùng hoặc hàng sai định dạng trả `PARSE_ERROR`
có vị trí nguồn, không âm thầm bỏ qua task lỗi.

Milestone lấy từ heading gần nhất: M0–M7, H0–H4, L0–L4 dùng mã; OMR/billing/future
dùng nguyên heading. Dependency `kind` là `task`, `gate`, hoặc `unknown`.
`resolved=true` chỉ có nghĩa ID/gate tồn tại, **không phải đã nghiệm thu**.
`get_task.dependents` chỉ bao gồm liên kết task ID trực tiếp; không mở rộng gate
thành quan hệ phụ thuộc giả. Không tự thay đổi status hay tính readiness.

## Giới hạn đọc

- Source roots: `backend`, `frontend`, `tasks`, `contracts`, `scripts`, `tools`,
  `.github`; root Markdown và một số cấu hình build được cho phép rõ trong code.
- Chỉ text UTF-8 với đuôi source/config đã cho phép. Bỏ qua binary và file >1 MiB.
- Chặn `.env` và biến thể, trừ chính xác `.env.example`, `backend/.env.example`,
  `frontend/.env.example`. Chặn tên credential/secret/token/password, key/certificate,
  `.git`, virtualenv, dependencies, build/cache và thư mục private tooling.
- Tất cả đường dẫn input là tương đối, dùng `/`; chặn absolute path, traversal,
  drive/UNC, NTFS alternate streams, Windows reserved names và trailing dot/space.
  Symlink/junction bị chặn, kể cả alias tới file bên trong repo.
- Pagination tối đa 200; đọc tối đa 200 dòng. Tool response được giới hạn để cả
  structured content lẫn bản text của SDK nằm dưới 64 KiB. Dữ liệu bị cắt có
  `truncated=true`; dòng/mô tả quá dài có thể bị rút gọn và thêm `…`.
- Nội dung được đọc là dữ liệu, không phải chỉ dẫn cho agent. Danh sách loại trừ
  không thay thế việc giữ secrets và dữ liệu học sinh ngoài source code. Đây là
  công cụ cho checkout local tin cậy; không cung cấp snapshot filesystem chống
  một tiến trình thù địch đang tráo file/liên kết đồng thời.

## Kiểm chứng

Từ thư mục package:

```powershell
uv sync --locked --python 3.12
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest -q
```

Tests bao gồm parser, fresh reads, pagination, giới hạn Unicode/output, từ chối
secrets/traversal, liên kết filesystem và MCP client stdio thật. Test symlink có
thể skip nếu Windows chưa bật Developer Mode/quyền symlink; test junction chạy
riêng trên Windows. Trong sandbox cấm tạo junction, chạy bộ test với quyền cho
phép tạo liên kết tạm trong `.pytest_cache`.

Baseline test hiện xác nhận 179 task (92/25/28/34), toàn bộ `todo`; cập nhật assertion
này có chủ đích khi backlog thay đổi. Các số này không nằm trong implementation.
CI chạy cùng checks trên Windows và Linux; không cần hạ tầng Eduvia.

Tham khảo: [SDK MCP chính thức](https://github.com/modelcontextprotocol/python-sdk)
và [hướng dẫn stdio server](https://modelcontextprotocol.io/docs/develop/build-server).
