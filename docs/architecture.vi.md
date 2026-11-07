# Kiến trúc — dịch thuật đa ngôn ngữ bất đồng bộ

> 🌐 Language / Ngôn ngữ: [English](architecture.md) | **Tiếng Việt**

## Mục tiêu thiết kế

Phục vụ bốn model dịch thuật lớn trên bốn nhóm GPU NVIDIA L40S có thể
scale độc lập, tránh giữ GPU chạy liên tục khi ít request. API hoạt động
bất đồng bộ; PostgreSQL giữ bền vững trạng thái, kết quả và cơ chế
chống xử lý trùng.

## Luồng xử lý

```text
API client đã xác thực
        |
        | Bearer token + Idempotency-Key (không bắt buộc)
        v
FastAPI Gateway chạy CPU trên Modal ---------- GET /health
        |
        | Transaction PostgreSQL, quota, tạo job + model runs
        v
PostgreSQL (không phụ thuộc nhà cung cấp)
        |
        | claim token + Modal RPC spawn theo model
        v
+----------------------+  +----------------------+  +----------------------+
| Hy-MT2 / L40S        |  | Index / L40S         |  | Gemma / Qwen / L40S  |
| GGUF Volume riêng    |  | GGUF Volume riêng    |  | GGUF Volume riêng    |
| llama.cpp loopback   |  | llama.cpp loopback   |  | llama.cpp loopback   |
+----------------------+  +----------------------+  +----------------------+
        |                         |                         |
        +-------------------------+-------------------------+
                                  |
                          Kết quả trong PostgreSQL
                                  |
                        API GET job có xác thực
```

Bốn GPU class được định nghĩa trong [`modal_app.py`](../modal_app.py).
Vòng đời load model dùng chung nằm trong
[`gpu_runtime.py`](../src/translation_ai_inference/gpu_runtime.py).
Hệ thống chỉ có một Modal App; không công khai endpoint HTTP cho từng GPU.

## Vòng đời tài nguyên

| Tài nguyên | Trách nhiệm |
|---|---|
| CPU gateway | Xác thực, kiểm tra đầu vào, lưu job và điều phối |
| PostgreSQL | Nguồn dữ liệu chính cho jobs, attempts, quotas, kết quả |
| Bốn L40S class | Mỗi class có một GGUF và Volume đã khóa nguồn |
| GPU worker | Load một model cho mỗi container; `min_containers=0` |
| Model server | `llama-server` chỉ bind `127.0.0.1` |
| CPU monitor | Kiểm tra dữ liệu tổng hợp mỗi giờ, không gọi GPU |

Mỗi nhóm model có `max_containers=1`, `scaledown_window=5` giây.
Điều này giảm tiền GPU lúc rảnh, không phải cam kết thời gian cold start.

## Tính nhất quán và xử lý lỗi

PostgreSQL có thể lưu job trước khi Modal xác nhận `spawn()`. Claim
token chặn dispatcher chạy trùng cùng model-run. Khi đã gửi lệnh tới
engine nhưng không nhận được phản hồi, hệ thống dùng trạng thái không
chắc chắn và **không tự retry** để tránh chạy lặp.

API `GET /v1/jobs/{job_id}` không khởi động GPU. Kết quả từng model
trong benchmark độc lập; lỗi một model không làm mất kết quả model khác.

## Bảo mật và giới hạn

Các endpoint `/v1` cần Bearer token; `/health` công khai và chỉ trả
trạng thái cấu hình process, không kiểm tra sâu GPU/database. Hệ thống
hiện theo mô hình single-tenant, chưa có kiểm thử xâm nhập độc lập
hoặc SLA thời gian phản hồi.

Xem [triển khai](deployment.vi.md), [cấu hình](configuration.vi.md),
[độ tin cậy](reliability.vi.md) và [quyết định kiến trúc](design-decisions.vi.md).
