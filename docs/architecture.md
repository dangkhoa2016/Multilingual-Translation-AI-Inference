# Architecture — Translation AI Inference (Modal + PostgreSQL)

**Trạng thái:** P0, thiết kế đã thống nhất theo handoff 2026-11-06; chưa deploy.

## Mục tiêu / phạm vi

- Text-only, mỗi input 1–1.000 ký tự Unicode (`len` của Python trên chuỗi đã parse, tài liệu hóa ý nghĩa này).
- EN↔VI, DE↔VI, JA↔VI, KO↔VI là các cặp benchmark mục tiêu; xác nhận khả năng thật với từng model.
- Ít traffic, chấp nhận cold start; benchmark tối đa 4 model độc lập.
- Một repo, một Modal App: FastAPI gateway CPU + 4 inference functions GPU L40S.
- PostgreSQL (Neon ban đầu, có thể thay thế) là source of truth cho jobs và results; Modal FunctionCall chỉ là định danh/cơ chế chạy.

## Luồng kiến trúc

```text
Rails/client --Bearer--> Modal FastAPI CPU Gateway
                             |         |
                             |         +------> PostgreSQL (jobs, runs, results)
                             |
                             +-- spawn(Hy) -----> L40S 48 GB / Hy-MT2 / Volume-Hy
                             +-- spawn(Index) --> L40S 48 GB / Index / Volume-Index
                             +-- spawn(Gemma) --> L40S 48 GB / Gemma / Volume-Gemma
                             +-- spawn(Qwen) ---> L40S 48 GB / Qwen / Volume-Qwen
                                                     |
                                                     +--> PostgreSQL: update individual runs
Client <-- GET /v1/jobs/{id} ---------------------- PostgreSQL only (no GPU wake-up)
```

## Autoscaling và cost

- Mỗi GPU Function: `gpu="L40S"`, `min_containers=0`, `buffer_containers=0`, `max_containers=1`, concurrency 1 cho v1.
- Khởi đầu thử `scaledown_window=60` và function timeout=1800s; đo và chỉnh sau benchmark.
- 4 models / 4 pools: mọi worker tách biệt scale-to-zero; không cần 4 HTTP subdomains.
- P0 chưa xác minh quota Modal ở tài khoản, nên **không đảm bảo 4 L40S có thể chạy cùng lúc**.
- Modal L40S list price 2026-11-06: **$0.000542 / GPU-second**; một worker 300 s ≈ $0.1626 GPU (chưa gồm CPU, RAM, Volume, network, Neon); 4 workers 300 s mỗi worker ≈ $0.6504 GPU.
- Giữ weights trên 4 Modal Volumes riêng; download once, pin SHA/revision, mount readonly khi inference. Dung lượng volume/storage và mức miễn phí thực tế phải xem ở dashboard billing.

## API v1

| Method | Route | Chức năng |
|---|---|---|
| GET | `/v1/models` | Lấy registry mà không wake GPU |
| POST | `/v1/jobs/translations` | Submit một model, HTTP 202 |
| POST | `/v1/jobs/benchmarks` | Submit tập model con/đủ 4, HTTP 202 |
| GET | `/v1/jobs/{job_id}` | Poll trạng thái + partial results, chỉ dùng PostgreSQL |
| GET | `/health` | Health gateway CPU |

`POST /v1/translate` sync và cancel được giữ **ngoài phạm vi MVP đầu tiên** cho đến khi xác minh timeout/cancel semantics.

## Độ bền dữ liệu / chống trùng

1. Client gửi `Idempotency-Key`. Uniqueness theo `(owner_id, key)` kèm request payload hash; cùng key nhưng payload khác trả lỗi 409.
2. Trong một transaction Postgres tạo `jobs`, `job_runs` cần thiết, và ghi trạng thái yêu cầu dispatch. Chỉ sau commit mới gọi `spawn()`.
3. API crash **sau commit nhưng trước spawn** hoặc **sau spawn trước cập nhật call ID** là hai failure modes đã được ghi nhận trong handoff. Không tuyên bố exactly-once.
4. Worker `run_id`/`attempt_no` cố định, ghi kết quả idempotently trong Postgres; CAS hoặc row locks ngăn replay ghi trùng và ngăn late attempt ghi đè completed result.
5. `GET` đọc database, không chờ Modal call result; benchmark luôn trả partial results.
6. Reconciliation các jobs `queued`, `dispatching`, `running`, `retrying` mắc kẹt. Ưu tiên lazy reconciliation khi có request, cron CPU tần suất thấp nếu cần tự khôi phục không có traffic.
7. Không giữ Postgres transaction đang mở trong lúc load weights hoặc inference. Nếu workers bị kill, retry có limit và backoff.

**Đề xuất bổ sung cho P2 (chưa phải thay đổi quyết định):** một bảng transactional outbox/dispatch leases có thể khép kín lỗ hổng commit→spawn, nhưng vẫn phải chấp nhận *at-least-once dispatch* và kết quả idempotent. Chốt chi tiết trong P2 trước khi viết dispatcher.

## Dữ liệu và privacy

- PostgreSQL pooled URL cho short-lived requests (nếu hỗ trợ), direct URL cho migrations.
- Tránh session `SET`, session advisory lock, `LISTEN/NOTIFY` khi kết nối qua transaction-pooling (ví dụ PgBouncer trên Neon); mỗi provider có quy tắc pooling riêng.
- Lưu raw source/output theo retention có cấu hình; không log raw text/token/API key; có lựa chọn không lưu sensitive text trước khi production.
- Bảo mật token trong Modal Secrets; không commit thông tin kết nối PostgreSQL.

## Bằng chứng hiện có / đang thiếu

- Nguồn công khai xác nhận Modal Function scale-to-zero và `spawn`, pooling trên Neon (provider đầu tiên), giá Modal và Neon free plan.
- Chưa có thực thi API, migrations, smoke trên GPU, ngân sách/quota của tài khoản hay số đo chất lượng. Các điều này **không thể được đánh dấu hoàn tất** ở P0.

## References

- https://modal.com/docs/guide/scale
- https://modal.com/docs/guide/trigger-deployed-functions
- https://modal.com/docs/guide/volumes
- https://modal.com/pricing
- https://neon.com/docs/connect/connection-pooling
- https://neon.com/blog/neon-free-plan-1-gb-per-project
