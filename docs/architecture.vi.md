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
      | Bearer token + Idempotency-Key (không bắt buộc)
      v
+--------------------------------------------------------------------+
| Modal App: gateway CPU và BỐN worker L40S scale độc lập             |
|                                                                    |
| FastAPI Gateway CPU --------------------------- GET /health         |
|       |                                                            |
|       | Modal RPC theo model sau khi lưu job bền vững               |
|       +--> Worker Hy-MT2     [L40S] <--> [Volume GGUF Hy-MT2]      |
|       +--> Worker Index      [L40S] <--> [Volume GGUF Index]       |
|       +--> Worker Gemma      [L40S] <--> [Volume GGUF Gemma]       |
|       +--> Worker Qwen       [L40S] <--> [Volume GGUF Qwen]        |
|           (mỗi model dùng llama.cpp loopback riêng tư)             |
+--------------------------------------------------------------------+
       | jobs, attempts, quota, idempotency và kết quả
       v
PostgreSQL bên ngoài (lưu trạng thái bền vững)
       |
       +--> GET /v1/jobs/{job_id} có xác thực qua gateway CPU
```

Bốn GPU class được định nghĩa trong [`modal_app.py`](../modal_app.py).
Vòng đời load model dùng chung nằm trong
[`gpu_runtime.py`](../src/multilingual_translation_ai_inference/gpu_runtime.py).
Hệ thống chỉ có một Modal App; không công khai endpoint HTTP cho từng GPU.

## Vòng đời tài nguyên

| Tài nguyên | Trách nhiệm |
|---|---|
| CPU gateway | Xác thực, kiểm tra đầu vào, lưu job và điều phối |
| PostgreSQL | Nguồn dữ liệu chính cho jobs, attempts, quotas, kết quả |
| Bốn L40S class | Mỗi class có một GGUF và Volume đã khóa nguồn |
| GPU worker | Load một model cho mỗi container; `min_containers=0` |
| Model server | `llama-server` chỉ bind `127.0.0.1` |
| CPU monitor | Kiểm tra PostgreSQL mỗi giờ khi bật; mặc định tắt, không gọi GPU |

Cấu hình worker hỗ trợ scale-to-zero độc lập và phân tách tài nguyên theo model.

## Job bền vững

API lưu job và model-run trong PostgreSQL, điều phối xử lý bất đồng bộ.
Mỗi model-run có trạng thái và kết quả riêng; client truy vấn qua API
polling có xác thực. Idempotency key hỗ trợ gửi lại request nhất quán.

## Truy cập API

Các endpoint `/v1` sử dụng xác thực Bearer. Hướng dẫn cấu hình
health check, biến môi trường và mạng có tại
[tài liệu triển khai](deployment.vi.md).

Xem [triển khai](deployment.vi.md), [cấu hình](configuration.vi.md),
[độ tin cậy](reliability.vi.md) và [quyết định kiến trúc](design-decisions.vi.md).
