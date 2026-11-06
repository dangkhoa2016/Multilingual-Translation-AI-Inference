# Cấu hình và thông tin bí mật

> 🌐 Language / Ngôn ngữ: [English](configuration.md) | **Tiếng Việt**

## Phát triển local

[Demo local](../scripts/examples/local_demo.py) tự tạo SQLite tạm thời,
dùng token mẫu có sẵn trong script, **không đọc `.env` và không chạy AI thật**.
Chỉ khi chạy migration, script API thật hoặc triển khai, hãy sao chép
[`.env.example`](../.env.example) thành `.env` không theo dõi bởi Git và
điền credentials riêng. Không commit `.env` hay thông tin đăng nhập.

| Biến | Ý nghĩa |
|---|---|
| `TRANSLATION_INFERENCE_DATABASE_URL` | Chuỗi kết nối PostgreSQL/SQLite |
| `TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL` | Kết nối PostgreSQL trực tiếp cho Alembic |
| `TRANSLATION_API_BEARER_TOKEN` | Secret API (16–4096 ký tự ASCII in được; không có khoảng trắng/ký tự điều khiển; nên dùng token ngẫu nhiên) |
| `TRANSLATION_AUTH_FAILURE_LIMIT` | Số lần Bearer sai trước khi khóa tạm tại một process (mặc định `3`) |
| `TRANSLATION_AUTH_FAILURE_WINDOW_SECONDS` | Cửa sổ trượt đếm lỗi (mặc định `300` giây) |
| `TRANSLATION_AUTH_LOCKOUT_SECONDS` | Thời gian khóa (mặc định `900` giây) |
| `TRANSLATION_AUTH_MAX_TRACKED_CLIENTS` | Giới hạn số địa chỉ lưu trong RAM mỗi process (`4096`) |
| `TRANSLATION_MAX_API_BODY_BYTES` | Giới hạn body trên các route bảo vệ (mặc định `65536` byte) |
| `TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PEER` | Trần request trước xác thực theo peer/process (`120`) |
| `TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PROCESS` | Trần request trước xác thực cho cả process (`600`) |
| `TRANSLATION_MAX_JOB_POLLS_PER_MINUTE` | Quota GET job theo owner, dùng chung PostgreSQL (`120`) |
| `TRANSLATION_MAX_PENDING_JOBS_PER_OWNER` | Số job chưa hoàn tất tối đa theo owner (`20`) |
| `TRANSLATION_MAX_PENDING_RUNS_PER_MODEL` | Số run chưa hoàn tất tối đa theo model, chung mọi owner (`20`) |
| `TRANSLATION_AUDIT_LOG_ENABLED` | Ghi metadata truy cập tùy chọn; chỉ nhận `true`/`false` (mặc định `false`) |
| `TRANSLATION_DISPATCHER_MODE` | `record-only`, `inline-mock`, `modal-cpu-mock`, `modal-gpu` |
| `TRANSLATION_MAX_JOBS_PER_MINUTE` | Quota tạo job theo phút |
| `TRANSLATION_MAX_JOBS_PER_DAY` | Quota tạo job theo ngày |
| `TRANSLATION_MAX_MODEL_RUNS_PER_DAY` | Quota model-run theo ngày |
| `TRANSLATION_MAX_ATTEMPTS_PER_MODEL` | Tổng số lần chạy tối đa cho mỗi model, **gồm lần đầu**; chỉ retry lỗi đã xác nhận (ví dụ 2 = 1 lần đầu + tối đa 1 lần retry) |
| `TRANSLATION_ESTIMATED_GPU_USD_PER_RUN` | Chi phí ước tính mỗi model-run (tùy chọn) |
| `TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY` | Hạn mức ước tính theo ngày (tùy chọn) |

Hai biến ngân sách ước tính phải được cấu hình **cùng nhau**. Hệ thống
dùng PostgreSQL để giữ trước lượng micro-USD ước tính khi nhận một run.
**Đây không phải giới hạn hóa đơn Modal thực tế.** Không tự đặt hạn
mức nếu người vận hành chưa quyết định.

## Phạm vi truy cập và credential dùng chung

Triển khai mặc định là **single-tenant**, không phải multi-tenant. API
dùng chung một `TRANSLATION_API_BEARER_TOKEN` và owner cố định
(`single-tenant-api`). Mọi client cung cấp token này đều thuộc
**cùng một phạm vi sở hữu**:

- Quota tạo job theo owner và hạn mức nhận model-run được dùng chung giữa
  các client, không phân tách theo từng người dùng cuối.
- Không gian idempotency thuộc cùng owner: cùng `Idempotency-Key` và
  cùng payload là cùng một logical job; dùng lại key với payload khác
  trả HTTP 409.
- Client đã xác thực và có UUID job hợp lệ có thể đọc job thuộc owner
  dùng chung. UUID không phải ranh giới phân quyền riêng cho mỗi người.
  Job ngoài owner cấu hình vẫn không thuộc phạm vi truy cập.

Lưu Bearer token trong secret phía server, chỉ cho các client đáng tin
cậy truy cập và thay token nếu bị lộ. Để hỗ trợ nhiều tenant/người dùng
độc lập cần thiết kế thêm: danh tính tenant xác thực riêng, ánh xạ
job-owner ổn định, phân quyền trên từng job, quota/idempotency theo
tenant, cô lập dữ liệu và phương án migration/bảo mật được rà soát.
**Chỉ thêm token cho các client không tự tạo ra multi-tenancy.**

## Bảo vệ CPU gateway

Gateway giới hạn request **trước khi so sánh token**: mặc định 120/peer/phút
và 600/process/phút. Ba lần sai trong năm phút kích hoạt phản hồi 429 cho
các lần sai tiếp theo trong 15 phút; token đúng xóa bộ đếm lỗi nhưng vẫn
chịu trần request. Body mặc định tối đa 64 KiB; Swagger/OpenAPI công khai bị tắt.
Giới hạn trước xác thực dùng RAM từng process. Quota GET job và giới hạn
job/run chưa hoàn tất dùng chung PostgreSQL giữa các replica. Cấu hình cùng
các ngưỡng trên mọi replica. Xem [bảo mật](security.vi.md) và
[vận hành](operations.vi.md) để hiểu cửa sổ thời gian, trạng thái uncertain
và logging tùy chọn.

Các ngưỡng request/poll nhận số nguyên 1–1.000.000; ngưỡng job/run chưa hoàn
tất nhận 1–100.000. Giới hạn này được kiểm tra khi khởi động.

## Tài nguyên Modal

Tên tài nguyên có ý nghĩa rõ ràng:

- App: `multilingual-translation-ai-inference-api-and-model-workers`
- PostgreSQL Secret: `multilingual-translation-ai-inference-postgresql-connection`
- API authentication Secret: `multilingual-translation-ai-inference-api-authentication`

Mỗi model có Modal Volume riêng đã khóa nguồn trong
[manifest](../models/four_l40s_workers_q8_0_manifest.json). GPU
không tải lại trọng số theo từng request.

Chế độ GPU thật do **Modal API Secret đã deploy** quyết định; sửa
`.env` local không thay đổi server. Sau khi sửa Secret, có thể phải
rollover Modal App để các container mới nạp biến cấu hình mới.
Xem [hướng dẫn triển khai](deployment.vi.md).

Khi triển khai lần đầu, xem [hướng dẫn tạo Secret](deployment.vi.md)
trước khi chuẩn bị GPU. Khi đổi dispatcher đã triển khai, dùng helper
`modal.Secret.update()` được tài liệu hóa để chỉ thay
`TRANSLATION_DISPATCHER_MODE`, không ghi đè các biến Secret khác.

## An toàn PostgreSQL

Nên dùng pooled connection cho runtime serverless nếu nhà cung cấp hỗ
trợ và direct connection để chạy migration. TLS, backup, max connections
và khả năng tương thích phụ thuộc từng dịch vụ. Dự án không buộc dùng
Neon; PostgreSQL tương thích khác đều có thể thay thế.

Xem [vận hành](operations.vi.md) để kiểm tra billing, sao lưu/khôi phục
PostgreSQL và đối soát job quá hạn.
