# Triển khai — Modal GPU inference và PostgreSQL

> 🌐 Language / Ngôn ngữ: [English](deployment.md) | **Tiếng Việt**

Hướng dẫn triển khai một **API Gateway chạy CPU** và bốn model worker
NVIDIA L40S độc lập trong cùng một Modal App. Bạn cần tự quản lý
workspace Modal và database PostgreSQL; tác vụ GPU có tính phí.

## Điều kiện chuẩn bị

- Python 3.12, `pip` và tài khoản Modal riêng; cách đăng nhập CLI có ở bên dưới.
- PostgreSQL có thể truy cập, ưu tiên TLS và pooled connection cho
  runtime; direct connection dành cho Alembic migration.
- Hai Modal Secret riêng cho database URL và Bearer token.
- Trước khi **inference GPU thật**, cần bốn Modal Volume chứa GGUF
  đúng revision và đã xác minh SHA256. Nếu **triển khai mới**, có thể tạo
  và nạp các Volume theo hướng dẫn ở phần bên dưới; xem
  [manifest](../models/four_l40s_workers_q8_0_manifest.json).
- Hạn mức chi phí do người vận hành chấp thuận. **Không mặc định
  workspace có ngân sách hoặc quyền GPU.**

## Chuẩn bị môi trường dự án trên máy local

Clone repository (hoặc mở thư mục đã clone) và cài package mã nguồn
**trước khi** chạy script staging, migration hay deploy. Lệnh bên dưới
dùng Bash và Python 3.12 trở lên; không cần Jupyter hay GPU để chuẩn bị.

```bash
git clone https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference.git
cd Multilingual-Translation-AI-Inference
git checkout v1.0.0
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Nếu đã clone repository, bắt đầu từ lệnh `python3.12 -m venv` trong thư mục
gốc. Môi trường đã kích hoạt cung cấp package
`multilingual_translation_ai_inference` mà script staging cần import.
Bước cài local này không tải trọng số hoặc khởi chạy GPU.

## Đăng nhập Modal và chọn environment

Tạo tài khoản tại [Modal](https://modal.com), rồi dùng CLI đã cài trong
virtualenv đang kích hoạt. Chọn tên profile local và đăng nhập bằng trình
duyệt; token đăng nhập Modal khác Bearer token của API dịch thuật.

```bash
export MODAL_PROFILE=translation-demo
modal token new --profile "$MODAL_PROFILE"
modal profile current --profile "$MODAL_PROFILE"
modal environment list --profile "$MODAL_PROFILE"
export MODAL_ENVIRONMENT=main
```

Chọn environment hiện có thuộc quyền bạn, hoặc tạo một environment mới một lần:

```bash
# Tùy chọn: dùng environment mới thay cho main.
# modal environment create translation-demo --profile "$MODAL_PROFILE"
# export MODAL_ENVIRONMENT=translation-demo
```

Giữ hai biến đã export trong cùng terminal khi tạo tài nguyên, staging,
deploy và chuyển mode. Lệnh không có option riêng sẽ dùng `MODAL_PROFILE`
và `MODAL_ENVIRONMENT`. Secret, Volume và App phải cùng workspace/environment.
Không dùng profile của maintainer để làm theo hướng dẫn.

## Chuẩn bị thông tin xác thực và Secret (chỉ khi triển khai mới)

Sử dụng **profile/environment Modal và PostgreSQL của chính bạn**.
Không dùng Secret hoặc Volume production có sẵn để thử theo tài liệu.
Đối với migration trên máy local, tạo `.env` không theo dõi bằng Git từ
[`.env.example`](../.env.example), thay URL SQLite mẫu bằng PostgreSQL
của bạn. Runtime có thể dùng pooled connection;
`TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL` phải là kết nối PostgreSQL
**trực tiếp**. Không ghi thông tin xác thực vào file đã theo dõi bằng Git.

Repository không tự tạo PostgreSQL. Bạn cần tạo database và role có quyền
tạo schema, cho phép kết nối từ máy chạy migration và container Modal.
Lấy URL runtime và URL migration trực tiếp từ nhà cung cấp; hai URL phải
trỏ tới **cùng database**. Percent-encode ký tự đặc biệt trong username/password
của URL và dùng cấu hình TLS theo nhà cung cấp. Ví dụ `.env` riêng tư:

```dotenv
TRANSLATION_INFERENCE_DATABASE_URL='postgresql+psycopg://DB_USER:URL_ENCODED_PASSWORD@RUNTIME_HOST:5432/DB_NAME?sslmode=require'
TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL='postgresql+psycopg://DB_USER:URL_ENCODED_PASSWORD@DIRECT_HOST:5432/DB_NAME?sslmode=require'
TRANSLATION_API_BEARER_TOKEN='YOUR_OWN_LONG_RANDOM_TOKEN'
```

Thay mọi placeholder. Modal Secret database phải dùng đúng URL runtime này;
Secret API và client phải dùng cùng Bearer token. Chỉ lệnh migration cần
URL trực tiếp. Giữ `.env` kín; notebook không tự đọc file này.

Trước khi chạy các lệnh bên dưới, tạo **hai file JSON riêng biệt ngoài Git**,
giới hạn quyền truy cập `0600`:

`/secure/translation-postgresql.json` (thay bằng URL runtime từ `.env`
riêng tư, không lấy dấu nháy đơn bao ngoài của shell):

```json
{
  "TRANSLATION_INFERENCE_DATABASE_URL": "YOUR_OWN_RUNTIME_POSTGRES_URL"
}
```

`/secure/translation-api.json` (thay token; chỉ thêm quota khi cần):

```json
{
  "TRANSLATION_API_BEARER_TOKEN": "YOUR_OWN_LONG_RANDOM_TOKEN",
  "TRANSLATION_DISPATCHER_MODE": "modal-cpu-mock"
}
```

Hãy thay hai đường dẫn `/secure/...` bằng đường dẫn file riêng trên máy.
Tạo Bearer token ngẫu nhiên bằng trình quản lý secret an toàn;
các chuỗi placeholder ở trên **không phải thông tin đăng nhập thật**.

```bash
modal profile current
modal secret list --env "$MODAL_ENVIRONMENT"

# CHỈ KHI TRIỂN KHAI MỚI; không dùng --force để tránh ghi đè Secret.
modal secret create --env "$MODAL_ENVIRONMENT" \
  multilingual-translation-ai-inference-postgresql-connection \
  --from-json /secure/translation-postgresql.json
modal secret create --env "$MODAL_ENVIRONMENT" \
  multilingual-translation-ai-inference-api-authentication \
  --from-json /secure/translation-api.json

# Chỉ xác nhận tên Secret; không in giá trị bí mật.
modal secret list --env "$MODAL_ENVIRONMENT"
```

Giữ file JSON riêng tư, quản lý quyền truy cập và không đưa vào
bản sao lưu dự định công bố. Với deployment đã tồn tại, **bỏ qua bước tạo
Secret**; xem [cấu hình](configuration.vi.md) và mục đổi dispatcher
bằng cách cập nhật một biến phía dưới. Tạo Secret hoặc Volume không
tự khởi chạy inference GPU.

## Chuẩn bị GGUF Volume (chỉ khi triển khai mới)

Bốn Volume **không đi kèm repository**. Nếu Volume production đã tồn tại
và được xác minh, **bỏ qua toàn bộ mục này**; không xóa, tạo lại hay
stage lại chỉ để làm theo tài liệu.

1. Đọc bốn model, revision, dung lượng và SHA256 trong
   [manifest](../models/four_l40s_workers_q8_0_manifest.json).
   Kiểm tra quyền Modal, dung lượng lưu trữ và ngân sách đã được duyệt.
2. Kiểm tra **đúng profile/environment** bằng `modal volume list`.
   Với workspace mới, [`create_volumes.sh`](../scripts/deployment/create_volumes.sh)
   chỉ tạo bốn Volume rỗng khi có
   `CONFIRM_TRANSLATION_GPU_VOLUME_CREATION=YES`; script **không**
   tải trọng số. Không chạy khi Volume đã tồn tại.
3. [`stage_model_weights.py`](../scripts/models/stage_model_weights.py)
   nạp **từng model riêng** bằng tác vụ Modal **CPU**. Không có
   `--stage` thì chỉ xem thông tin; khi bật `--stage`, script tải GGUF
   khóa revision, kiểm tra số byte và SHA256 toàn file, ghi marker xác
   minh rồi commit Volume. CPU, tải dữ liệu và lưu trữ có thể tính phí.
4. Xác nhận cả bốn GGUF và marker trước khi deploy. Không sửa manifest
   để bỏ qua lỗi kiểm tra; marker không thay thế việc kiểm tra checksum.

```bash
# Kiểm tra profile/environment đã chọn phía trên.
modal profile current
modal volume list --env "$MODAL_ENVIRONMENT"

# CHỈ TRIỂN KHAI MỚI: tạo bốn Volume rỗng trong environment đã chọn.
CONFIRM_TRANSLATION_GPU_VOLUME_CREATION=YES bash scripts/deployment/create_volumes.sh

# Xem trước một model, không tải khi chưa có --stage:
modal run scripts/models/stage_model_weights.py --model hy_mt2_30b

# Có phí CPU/lưu trữ: tải lần lượt cả bốn model.
for model in hy_mt2_30b index_35b gemma4_31b_it qwen35_35b; do
  modal run --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" \
    scripts/models/stage_model_weights.py --model "$model" --stage || break
done
```

Chỉ chạy vòng tải sau khi chấp thuận phí CPU/lưu trữ cho khoảng 139,33 GB
trọng số GGUF. Tải trực tiếp bằng tác vụ CPU trên Modal, không tải qua máy
cá nhân. Mỗi lần phải trả `verified_and_committed` hoặc `already_verified`;
dừng khi có lỗi. Chạy lại cùng model với `--stage` sẽ tính lại SHA256 toàn
file trước khi trả `already_verified`. Chưa xác minh đủ bốn model thì không
chuyển sang deploy.

Kiểm tra file đã lưu, không cấp phát GPU:

```bash
python - <<'PYTHON'
import json
import os
import subprocess
from pathlib import Path

models = json.loads(Path("models/four_l40s_workers_q8_0_manifest.json").read_text())["models"]
for key, spec in models.items():
    print(key, spec["gguf_filename"], spec["gguf_size_bytes"], "bytes", flush=True)
    subprocess.run(["modal", "volume", "ls", "--env", os.environ["MODAL_ENVIRONMENT"],
                    spec["modal_volume_name"], "/"], check=True)
PYTHON
```

Mỗi Volume phải có đúng `gguf_filename`, `gguf_size_bytes` trong manifest
và marker `hy_mt2_q8_0_verified.json` cho Hy-MT2 hoặc
`verified_gguf_q8_0.json` cho ba model còn lại. Listing chỉ chứng minh file
tồn tại, không xác nhận checksum; kết quả staging thành công mới là kiểm tra
checksum. Triển khai mới cần đủ bốn Volume vì App tham chiếu cả bốn.

## Chuẩn bị schema database

Sau khi cài package và kích hoạt virtualenv ở bước đầu:

```bash
# Dùng lại .env đã chuẩn bị trong mục "Chuẩn bị thông tin xác thực và Secret".
# Phải có TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL (PostgreSQL trực tiếp).
# Không sao chép đè từ .env.example hoặc dùng URL SQLite mẫu.
set -a; source .env; set +a
alembic -c db/alembic.ini upgrade head
alembic -c db/alembic.ini current
```

Kết quả mong đợi là revision `0005_pending_admission` ở head. Xử lý lỗi
migration trước deploy: kiểm tra URL trực tiếp, TLS, mạng và quyền schema;
không công bố credential. Sao lưu database đang dùng và migrate trước khi
rollout API. Revision 0003 mở rộng nhãn ngôn ngữ, 0004 bổ sung cột telemetry
nullable còn thiếu, 0005 tạo bảng khóa nhận job; giữ nguyên job/kết quả.
Có thể xuất SQL PostgreSQL để xem trước, không kết nối database:

```bash
alembic -c db/alembic.ini upgrade head --sql > /secure/translation-schema.sql
```

Đây là script cài mới; database hiện có cần đúng revision xuất phát, ví dụ
`upgrade 0004_run_metrics:head --sql`. Upgrade online kiểm tra cột telemetry
đã tồn tại; SQL PostgreSQL offline dùng `ADD COLUMN IF NOT EXISTS`.
Xuất SQL triển khai offline chỉ hỗ trợ PostgreSQL.

API Secret chứa `TRANSLATION_API_BEARER_TOKEN`; database Secret
chứa `TRANSLATION_INFERENCE_DATABASE_URL`. Xem [cấu hình](configuration.vi.md)
để biết tên tài nguyên và các quota tùy chọn. Không ghi token thật vào Git.

## Deploy một Modal App

Khi deploy, **CPU monitor mặc định không có lịch tự động**. Muốn kiểm
tra PostgreSQL mỗi giờ, đặt biến môi trường `hourly` ngay trên máy
thực hiện deploy. Đây không phải Modal Secret hay tùy chọn bật GPU:

```bash
# Mặc định: không chạy monitor theo lịch.
modal deploy --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" modal_app.py

# Tùy chọn: bật kiểm tra CPU mỗi giờ.
TRANSLATION_OPERATIONS_MONITOR_SCHEDULE=hourly modal deploy --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" modal_app.py

modal app list --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT"
```

Chỉ chấp nhận `off` (mặc định) hoặc `hourly`; giá trị khác khiến bước
import/deploy báo lỗi. Để tắt lịch đang chạy, redeploy với
`TRANSLATION_OPERATIONS_MONITOR_SCHEDULE=off`, rồi kiểm tra trang
**Details** của function trong Modal. Chỉ push Git không thay đổi
deployment. Function vẫn có thể chạy thủ công bằng **Run now**.
Lịch CPU và truy vấn PostgreSQL vẫn có thể phát sinh phí khi GPU sleep.

App bao gồm:
- `translation_inference_fastapi_cpu_gateway` — FastAPI CPU.
- `translation_inference_cpu_mock_job_worker` — mock để kiểm thử/rollback.
- `HyMT2L40SWorker`, `IndexTranslateL40SWorker`,
  `Gemma4L40SWorker`, `Qwen35L40SWorker` — mỗi class một GPU, tự sleep.
- `translation_inference_cpu_operations_safety_monitor` —
  kiểm tra PostgreSQL chỉ CPU; mặc định không bật lịch tự động.

Deploy mã nguồn không đồng nghĩa Secret hiện hành tự chuyển sang GPU.
`TRANSLATION_DISPATCHER_MODE=modal-gpu` dùng bản dịch thật;
`modal-cpu-mock` trả kết quả giả lập có đánh dấu rõ ràng.

## Kiểm thử API có xác thực

Dùng URL HTTPS do chính Modal deployment trả về:

```bash
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_GATEWAY.modal.run"
curl -fsS "$TRANSLATION_GATEWAY_BASE_URL/health"

# Nạp TRANSLATION_API_BEARER_TOKEN từ nơi lưu riêng tư trước khi gọi.
curl -fsS "$TRANSLATION_GATEWAY_BASE_URL/v1/models" \
  -H "Authorization: Bearer $TRANSLATION_API_BEARER_TOKEN"
```

Các lệnh trên chỉ xác minh gateway và xác thực; ở chế độ khởi tạo
`modal-cpu-mock`, chúng **không** chứng minh GPU đã sẵn sàng.
Phải hoàn tất bước chuyển mode bên dưới **trước** khi chạy GPU smoke.

## Chuyển chế độ và rollback an toàn

Helper dùng `Secret.update()` của Modal SDK để chỉ đổi
`TRANSLATION_DISPATCHER_MODE`, **giữ nguyên mọi biến khác** trong Secret.
Yêu cầu Modal Python SDK từ **1.3.5**, gateway hoạt động và
profile/environment đúng. Mặc định lệnh chỉ xem trước.
`--apply` do người vận hành quyết định và thực hiện **recreate rollover**,
có thể gián đoạn job đang xử lý. Chọn thời điểm bảo trì, kiểm tra job
và ngân sách; không tự retry GPU khi trạng thái chưa xác định.

```bash
# Chỉ xem trước, không thay đổi gì:
PYTHONPATH=src python scripts/deployment/set_dispatch_mode.py --to-mock

# Chỉ khi được chấp thuận, có thể gián đoạn container đang chạy:
# PYTHONPATH=src python scripts/deployment/set_dispatch_mode.py \
#   --to-mock --apply --profile YOUR_MODAL_PROFILE \
#   --environment YOUR_MODAL_ENVIRONMENT \
#   --base-url https://YOUR_GATEWAY.modal.run
```

Chỉ bật `--to-gpu` sau khi xác nhận gateway ở mock mode,
trọng số model, tài nguyên và hạn mức đã được phê duyệt.
Nếu cập nhật lỗi, helper **thử** khôi phục mode cũ và rollover lại;
không thể bảo đảm phục hồi khi dịch vụ cloud mất kết nối. Cần xác minh
gateway health và đối soát job đang chạy. Helper không deploy mã nguồn
mới hoặc ghi đè toàn bộ Secret.

## Bật GPU mode và kiểm thử có chủ đích

Với **triển khai mới**, trước tiên hãy xác nhận đủ bốn Volume GGUF,
giấy phép model, quyền GPU, ngân sách và không có job đang chạy.
Việc chuyển mode cập nhật Secret hiện hữu và recreate container, có
thể gián đoạn job. Kiểm tra gateway đang ở mock mode trước khi chuyển.
Các lệnh dưới đây chỉ dùng profile/environment và URL HTTPS của **bạn**;
nạp Bearer token riêng tư trước khi thực hiện.

```bash
# 1. Xem trước, không thay đổi cloud:
PYTHONPATH=src python scripts/deployment/set_dispatch_mode.py --to-gpu \
  --profile "$MODAL_PROFILE" --environment "$MODAL_ENVIRONMENT" \
  --base-url "$TRANSLATION_GATEWAY_BASE_URL"

# 2. CHỈ khi người vận hành chấp thuận; có thể gián đoạn job:
PYTHONPATH=src python scripts/deployment/set_dispatch_mode.py --to-gpu --apply \
  --profile "$MODAL_PROFILE" --environment "$MODAL_ENVIRONMENT" \
  --base-url "$TRANSLATION_GATEWAY_BASE_URL"

# 3. Kiểm tra response có inference_enabled=true và phase="gpu":
curl -fsS "$TRANSLATION_GATEWAY_BASE_URL/health"

# 4. Kiểm thử một model — có tính phí GPU:
PYTHONPATH=src python scripts/api/smoke_gpu.py --run

# Tùy chọn, kiểm thử cả bốn model — có tính phí:
# PYTHONPATH=src python scripts/api/smoke_gpu.py --run --all-models
```

Chỉ chạy bước 4 khi helper đã xác nhận GPU mode và bước 3 trả về
**cả hai trường** như trên; script smoke cũng tự kiểm tra lại.
Script ghi báo cáo đã lược bỏ dữ liệu riêng vào thư mục tạm có giới
hạn quyền **ngoài repository**, không lưu job ID thật vào `reports/`
đã được Git theo dõi. Kiểm duyệt output trước khi chia sẻ công khai.

POST thành công trả HTTP 202, `job_id` và `status_url`; dùng cùng token
để polling. `is_mock_result=false` nghĩa là inference không giả lập,
**không bảo đảm chất lượng dịch**. Muốn rollback, dùng hướng dẫn
`--to-mock` ở phần trước.

## Sau khi triển khai

Khi có lỗi, bắt đầu từ chặng cuối đã thành công:

| Lỗi | Kiểm tra trước khi tiếp tục |
|---|---|
| Không tìm thấy profile/environment | Đăng nhập CLI, workspace đã chọn và bước tạo environment |
| Không tìm thấy Secret/Volume | Đúng tên và cùng environment trong mọi lệnh |
| Tải trọng số hoặc SHA256 lỗi | Artifact/revision đã pin, kết nối mạng và log staging; không sửa hash để bỏ qua lỗi |
| Kết nối database hoặc migration lỗi | URL trỏ cùng database, TLS, kết nối mạng và quyền của role |
| HTTP 401 | Token client khớp Modal Secret API |
| HTTP 429 do nhập Bearer token sai | Khóa tạm sau ba lần sai tại process; tôn trọng `Retry-After` và xem [bảo mật gateway](security.vi.md) |
| Health vẫn `mock-only` | Hoàn thành chuyển mode và xác minh trước GPU smoke |
| Job GPU lỗi hoặc uncertain | Kiểm tra log Modal và trạng thái lưu trong database; giữ UUID/key, đối soát trước retry |

Lấy URL HTTPS gateway từ output của `modal deploy`, không dùng URL mẫu hoặc
endpoint worker riêng. Lần build image và cold start model đầu có thể lâu;
deploy thành công hoặc `/health` thành công chưa chứng minh GPU sẵn sàng.

Xem [vận hành](operations.vi.md), [bằng chứng độ tin cậy](reliability.vi.md)
và [giấy phép model](../MODEL_LICENSE.vi.md).
Runbook không tạo hoặc công bố bất kỳ token/trọng số nào.
