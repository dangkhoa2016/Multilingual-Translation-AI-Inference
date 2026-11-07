# Triển khai — Modal GPU inference và PostgreSQL

> 🌐 Language / Ngôn ngữ: [English](deployment.md) | **Tiếng Việt**

Hướng dẫn triển khai một **API Gateway chạy CPU** và bốn model worker
NVIDIA L40S độc lập trong cùng một Modal App. Bạn cần tự quản lý
workspace Modal và database PostgreSQL; tác vụ GPU có tính phí.

## Điều kiện chuẩn bị

- Python 3.12, `pip` và Modal CLI đã đăng nhập.
- PostgreSQL có thể truy cập, ưu tiên TLS và pooled connection cho
  runtime; direct connection dành cho Alembic migration.
- Hai Modal Secret riêng cho database URL và Bearer token.
- Bốn Modal Volume đã chứa file GGUF đúng revision và xác minh SHA256
  theo [manifest](../models/four_l40s_workers_q8_0_manifest.json).
- Hạn mức chi phí do người vận hành chấp thuận. **Không mặc định
  workspace có ngân sách hoặc quyền GPU.**

## Cài đặt và tạo schema

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

# Nạp .env không theo dõi bằng Git.
set -a; source .env; set +a
alembic -c db/alembic.ini upgrade head
```

API Secret chứa `TRANSLATION_API_BEARER_TOKEN`; database Secret
chứa `TRANSLATION_INFERENCE_DATABASE_URL`. Xem [cấu hình](configuration.vi.md)
để biết tên tài nguyên và các quota tùy chọn. Không ghi token thật vào Git.

## Deploy một Modal App

```bash
modal deploy --profile YOUR_MODAL_PROFILE modal_app.py
modal app list --profile YOUR_MODAL_PROFILE
```

App bao gồm:
- `translation_inference_fastapi_cpu_gateway` — FastAPI CPU.
- `translation_inference_cpu_mock_job_worker` — mock để kiểm thử/rollback.
- `HyMT2L40SWorker`, `IndexTranslateL40SWorker`,
  `Gemma4L40SWorker`, `Qwen35L40SWorker` — mỗi class một GPU, tự sleep.
- `translation_inference_cpu_operations_safety_monitor` —
  giám sát PostgreSQL hàng giờ, chỉ CPU.

Deploy mã nguồn không đồng nghĩa Secret hiện hành tự chuyển sang GPU.
`TRANSLATION_DISPATCHER_MODE=modal-gpu` dùng bản dịch thật;
`modal-cpu-mock` trả kết quả giả lập có đánh dấu rõ ràng.

## Kiểm thử API có xác thực

Dùng URL HTTPS do chính Modal deployment trả về:

```bash
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_GATEWAY.modal.run"
curl -fsS "$TRANSLATION_GATEWAY_BASE_URL/health"

curl -fsS "$TRANSLATION_GATEWAY_BASE_URL/v1/models" \
  -H "Authorization: Bearer $TRANSLATION_API_BEARER_TOKEN"

# Kiểm thử một model — có tính phí GPU:
PYTHONPATH=src python scripts/smoke_modal_gpu_api.py --run

# Kiểm thử bốn model — có tính phí GPU:
PYTHONPATH=src python scripts/smoke_modal_gpu_api.py --run --all-models
```

Tạo job trả HTTP 202 cùng `job_id` và `status_url`. Dùng Bearer
token cũ khi polling. `is_mock_result=false` nghĩa là inference
thật, **không bảo đảm bản dịch đúng ngữ nghĩa**.

## Chuyển chế độ và rollback an toàn

Helper đã có kiểm tra token, dùng file Secret tạm riêng tư và
refresh container sau khi Secret thay đổi:

```bash
PYTHONPATH=src python scripts/set_modal_dispatch_mode.py --to-mock
PYTHONPATH=src python scripts/set_modal_dispatch_mode.py \
  --to-mock --apply --profile YOUR_MODAL_PROFILE

# Bật GPU thật khi được phép:
PYTHONPATH=src python scripts/set_modal_dispatch_mode.py \
  --to-gpu --apply --profile YOUR_MODAL_PROFILE
```

Kiểm tra job đang chạy trước khi rollover. Container mới có thể
cần tải từ Volume hàng chục GB trọng số. Không tự retry khi trạng thái
thực thi chưa chắc chắn; cần đối soát thủ công.

## Sau khi triển khai

Xem [vận hành](operations.vi.md), [bằng chứng độ tin cậy](reliability.vi.md)
và [giấy phép model](../MODEL_LICENSE.vi.md).
Runbook không tạo hoặc công bố bất kỳ token/trọng số nào.
