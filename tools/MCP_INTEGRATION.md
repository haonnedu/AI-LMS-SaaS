# Tích hợp MCP (Model Context Protocol) cho Eduvia

> Ngày: 2026-10-21. Trạng thái: Hướng dẫn cấu hình đề xuất.

## 1. Mục đích tích hợp MCP vào Eduvia
Mặc dù các tool gốc của DeepSeek Harness (`read`, `write`, `edit`, `pwsh`, `grep`, `glob`) đã rất mạnh mẽ để quản lý file và chạy lệnh, việc tích hợp các **MCP Server** chuẩn cung cấp các lợi ích chuyên sâu:
1. **Database MCP Server (PostgreSQL):** Cho phép AI truy vấn trực tiếp cấu trúc bảng, kiểm tra dữ liệu test, chạy câu lệnh SQL phân tích mà không cần qua thủ tục viết script Python rườm rà.
2. **Filesystem MCP Server / Memory MCP:** Giúp agent ghi nhớ ngữ cảnh dài hạn giữa các phiên hoặc thao tác file nâng cao.

---

## 2. Các MCP Server đề xuất cho Eduvia

### A. Postgres MCP Server (Truy vấn cơ sở dữ liệu trực tiếp)
- **Tác dụng:** Giúp AI kiểm tra trạng thái migration, dữ liệu tenant, RLS policies, các bảng `users`, `workspaces`, `workspace_members` ngay trong phiên chat.
- **Cấu hình mẫu (`mcp.json` hoặc trong profile DSH):**
  ```json
  {
    "mcpServers": {
      "eduvia-postgres": {
        "command": "npx",
        "args": [
          "-y",
          "@modelcontextprotocol/server-postgres",
          "postgresql://postgres:postgres@localhost:5432/eduvia"
        ]
      }
    }
  }
  ```

### B. Filesystem MCP Server (Quản lý workspace mở rộng)
- **Tác dụng:** Cho phép các thao tác đọc/ghi file đồng bộ an toàn qua giao thức chuẩn MCP khi làm việc với các file tài liệu lớn hoặc thư mục phức tạp.

---

## 3. Cách kích hoạt trong DSH
Theo tài liệu subsystem MCP của DSH (`docs/subsystems/mcp.md`), các MCP server được cấu hình theo từng profile hoặc qua file config client tương ứng của DSH. 

Khi đã cấu hình, agent có thể gọi các tool có tiền tố tương ứng với server (ví dụ: `mcp__eduvia-postgres__query` hoặc tương tự) để thực thi các tác vụ chuyên biệt về dữ liệu.

Bạn có muốn mình bổ sung file cấu hình mẫu cho Postgres MCP vào thư mục `tools/` hoặc cấu hình chi tiết hơn không?
