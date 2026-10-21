# Staging deployment — 2026-10-21

Người thực hiện: coding agent theo yêu cầu trực tiếp của Hao. Không phải nghiệm thu toàn bộ M0/M1.

## Kết quả thực tế

- Commit đầu: `9e13af01adc07c4ffbfda0c58969b1e818f1e659`.
- [Foundation CI pass](https://github.com/haonnedu/AI-LMS-SaaS/actions/runs/39562088760).
- [GitHub auto deploy pass](https://github.com/haonnedu/AI-LMS-SaaS/actions/runs/39562226901).
- Server Ubuntu 26.04, Docker 29.9, Compose 5.6; shared staging tại `/home/nnh/eduvia-staging`.
- Frontend loopback port 3100 HTTP 200. API readiness: PostgreSQL và Redis `ok`. Frontend/API/worker/DB/Redis healthy.
- Alembic revision thật: `0002_identity_and_workspaces`; ba bảng users/workspaces/workspace_members do `eduvia_migrator` sở hữu.
- PostgreSQL xác nhận migrator/runtime đều không superuser, CREATEDB, CREATEROLE, BYPASSRLS. Runtime không CREATE trên schema edu hoặc database.
- Network riêng: `eduvia-staging_data` internal, subnet 172.22.0.0/16; `eduvia-staging_app` subnet 172.23.0.0/16. Không dùng shared proxy network. DB/Redis không publish port; frontend chỉ 127.0.0.1:3100.
- Các container wedding/n8n/cloudflared/portainer giữ nguyên uptime, không sửa stack khác.
- GitHub Environment staging giới hạn main; SSH key riêng và pinned known-host được lưu bằng encrypted secrets. Không đưa private key/password vào repo.

## Auto deploy

[Workflow](../.github/workflows/deploy-staging.yml) chỉ chạy sau Foundation checks thành công cho push main của chính repo; deploy SHA đã kiểm tra, không deploy PR. Build trên server, flock serialize rollout, migrate một lần rồi health checks. Có maintenance window; không tự downgrade hoặc xóa volume.

Lượt đầu phát hiện Docker đọc stdin của SSH heredoc khiến lệnh ghi current-release sau deploy bị nuốt dù services đã healthy. Bản sửa redirect stdin deploy sang /dev/null; cần kiểm chứng lần chạy kế tiếp và marker.

## Hai người truy cập

Chạy trên máy cá nhân (giữ terminal mở):

```sh
ssh -N -L 3100:127.0.0.1:3100 -p 2222 nnh@171.239.245.121
```

Sau đó mở http://localhost:3100. Nếu cổng local bận, đổi số 3100 đầu tiên sang 3101 và mở localhost:3101. Nên cấp SSH key/tài khoản riêng cho mỗi người; hiện chưa cấu hình danh tính cá nhân thứ hai.

## Giới hạn còn lại

- Đây là scaffold staging, không phải sản phẩm đã có auth/tenant RLS/nghiệp vụ. Không dùng dữ liệu thật và không public Internet.
- Object storage chưa cấu hình. Backup/restore tự động chưa triển khai; cần bổ sung trước dữ liệu quan trọng/migration rủi ro.
- Runtime DML grants chưa thay thế tenant isolation; chưa nghiệm thu DB-02..05.
- SSH CI key có restrict (không forwarding/PTY), nhưng user thuộc Docker group vẫn có quyền tương đương root. Nên harden tài khoản deploy chuyên dụng về sau.
- Mật khẩu SSH đã được chia sẻ trong chat và quá yếu: cần đổi và thiết lập SSH key cá nhân trước khi tắt password login; không tự đổi để tránh khóa truy cập.
