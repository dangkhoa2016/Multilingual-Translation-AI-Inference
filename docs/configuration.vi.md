# Cấu hình và thông tin bí mật

> 🌐 Language / Ngôn ngữ: [English](configuration.md) | **Tiếng Việt**

## Phát triển local

Sao chép [`.env.example`](../.env.example) thành `.env`, tự tạo Bearer
token ngẫu nhiên. Cấu hình mẫu dùng SQLite và `inline-mock`; **không
chạy dịch thuật bằng AI thật**. Không commit `.env`, database URL
thực tế hoặc thông tin đăng nhập cloud.

| Biến | Ý nghĩa |
|---|---|
| `TRANSLATION_INFERENCE_DATABASE_URL` | Chuỗi kết nối PostgreSQL/SQLite |
| `TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL` | Kết nối PostgreSQL trực tiếp cho Alembic |
| `TRANSLATION_API_BEARER_TOKEN` | Secret dùng để xác thực API client |
| `TRANSLATION_DISPATCHER_MODE` | `record-only`, `inline-mock`, `modal-cpu-mock`, `modal-gpu` |
| `TRANSLATION_MAX_JOBS_PER_MINUTE` | Quota tạo job theo phút |
| `TRANSLATION_MAX_JOBS_PER_DAY` | Quota tạo job theo ngày |
| `TRANSLATION_MAX_MODEL_RUNS_PER_DAY` | Quota model-run theo ngày |
| `TRANSLATION_MAX_ATTEMPTS_PER_MODEL` | Giới hạn retry khi lỗi đã xác nhận |
| `TRANSLATION_ESTIMATED_GPU_USD_PER_RUN` | Chi phí ước tính mỗi model-run (tùy chọn) |
| `TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY` | Hạn mức ước tính theo ngày (tùy chọn) |

Hai biến ngân sách ước tính phải được cấu hình **cùng nhau**. Hệ thống
dùng PostgreSQL để giữ trước lượng micro-USD ước tính khi nhận một run.
**Đây không phải giới hạn hóa đơn Modal thực tế.** Không tự đặt hạn
mức nếu người vận hành chưa quyết định.

## Tài nguyên Modal

Tên tài nguyên có ý nghĩa rõ ràng:

- App: `translation-ai-inference-api-and-model-workers`
- PostgreSQL Secret: `translation-ai-inference-postgresql-connection`
- API authentication Secret: `translation-ai-inference-api-authentication`

Mỗi model có Modal Volume riêng đã khóa nguồn trong
[manifest](../models/four_l40s_workers_q8_0_manifest.json). GPU
không tải lại trọng số theo từng request.

Chế độ GPU thật do **Modal API Secret đã deploy** quyết định; sửa
`.env` local không thay đổi server. Sau khi sửa Secret, có thể phải
rollover Modal App để các container mới nạp biến cấu hình mới.
Xem [hướng dẫn triển khai](deployment.vi.md).

## An toàn PostgreSQL

Nên dùng pooled connection cho runtime serverless nếu nhà cung cấp hỗ
trợ và direct connection để chạy migration. TLS, backup, max connections
và khả năng tương thích phụ thuộc từng dịch vụ. Dự án không buộc dùng
Neon; PostgreSQL tương thích khác đều có thể thay thế.

Xem [vận hành](operations.vi.md) để giám sát billing và đối soát job quá hạn.
