# Multilingual Translation AI Inference

> 🌐 Language / Ngôn ngữ: [English](README.md) | **Tiếng Việt**

[![Python CI](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/actions/workflows/python-validation.yml/badge.svg?branch=main)](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/actions/workflows/python-validation.yml)
[![Repository Audit](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/actions/workflows/repository-audit.yml/badge.svg?branch=main)](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/actions/workflows/repository-audit.yml)
[![License: MIT](https://img.shields.io/badge/Source%20License-MIT-yellow.svg)](LICENSE)
[![Model License: Apache 2.0](https://img.shields.io/badge/Model%20License-Apache--2.0-blue.svg)](MODEL_LICENSE.vi.md)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Modal](https://img.shields.io/badge/Modal-L40S%20%C3%97%204-76B900)](https://modal.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Status](https://img.shields.io/badge/Status-Validated%20Preview-blue)](docs/roadmap.vi.md)

**API dịch thuật đa ngôn ngữ bất đồng bộ có xác thực, dùng bốn model
AI riêng biệt trên bốn GPU NVIDIA L40S độc lập, lưu job trong PostgreSQL
và khóa nguồn gốc các file GGUF để dễ kiểm chứng.**

Dự án tập trung vào kỹ thuật triển khai model thật: chọn một model
hoặc so sánh bốn model qua cùng API, dùng CPU cho gateway, chỉ bật GPU
khi cần dịch, và lưu kết quả bền vững kể cả khi một model gặp lỗi
hoặc request bị ngắt kết nối.

> **Bản preview đã nghiệm thu khả năng vận hành, chưa chứng nhận chất lượng
> dịch.** Cả bốn model đã trả kết quả thật qua API, nhưng vẫn cần
> kiểm duyệt độc lập về ngữ nghĩa và an toàn vận hành production.

## Dự án cung cấp những gì?

- **Bốn GPU worker NVIDIA L40S độc lập**, mỗi worker có GGUF đã khóa
  revision, Volume bền vững và tham số decoding theo từng model.
- **Một FastAPI Gateway** xác thực Bearer, kiểm tra đầu vào, chống
  gửi trùng, tạo job bất đồng bộ và cho phép polling có xác thực.
- **PostgreSQL bền vững** lưu job, attempt, kết quả, quota và dự trù
  ngân sách GPU ước tính khi người vận hành bật tùy chọn.
- **Xử lý lỗi có kiểm soát:** cô lập model lỗi, không tự retry GPU
  khi kết quả thực thi còn chưa chắc chắn.
- **Monitor chạy CPU mỗi giờ** theo dõi job quá hạn, uncertain
  và công cụ đọc billing từ Modal CLI.
- **Bằng chứng GPU thật, unit test chỉ dùng CPU và tài liệu EN/VI**
  để người khác kiểm chứng được khả năng và giới hạn hệ thống.

## Bốn model được hỗ trợ

| API model key | Tên model gốc | GPU | Quantization |
|---|---|---|---|
| `hy_mt2_30b` | Tencent Hy-MT2-30B-A3B | L40S 48 GB | GGUF Q8_0 |
| `index_35b` | IndexTeam Index-Translate-35B-A3B-preview | L40S 48 GB | GGUF Q8_0 |
| `gemma4_31b_it` | Google Gemma 4 31B IT | L40S 48 GB | GGUF Q8_0 |
| `qwen35_35b` | Qwen3.5-35B-A3B | L40S 48 GB | GGUF Q8_0 |

API nhận `en` (Anh), `vi` (Việt), `de` (Đức), `ja` (Nhật),
`ko` (Hàn), yêu cầu ngôn ngữ nguồn khác đích và tối đa
**1.000 Unicode code point**. API chấp nhận hướng dịch không có
nghĩa chất lượng của mọi bản dịch đã được bảo đảm.

Nguồn, revision, SHA256 và giấy phép được trình bày tại
[model catalog](docs/models.vi.md) và
[giấy phép model](MODEL_LICENSE.vi.md).
Repository Git **không chứa trọng số model**.

## Bằng chứng nghiệm thu

| Nội dung | Kết quả quan sát |
|---|---|
| Nạp bốn model thật | PASS trên bốn GPU L40S khác nhau |
| Bốn model chạy đồng thời | PASS, bốn GPU UUID riêng |
| HTTP job dịch một model | Hoàn thành, kết quả không mock |
| HTTP benchmark bốn model | 4/4 hoàn thành và lưu PostgreSQL |
| Giới hạn 1.000 ký tự | 4/4 hoàn thành, 1.001 ký tự bị HTTP 422 |
| Hai job gửi vào một model | Cả hai hoàn thành, không retry trùng |
| Tái sử dụng container | Hai readiness RPC dùng cùng GPU UUID |
| Monitor | CPU mỗi giờ, không khởi động GPU, không retry |

Đây là **kiểm thử chức năng có giới hạn**, không phải SLA hay bảng
xếp hạng độ chính xác. Diagnostic Hy-MT2 đã phát hiện lỗi thay đổi
vật liệu/thuật ngữ trong bản dịch. Xem
[benchmark](docs/benchmarking.vi.md) và [độ tin cậy](docs/reliability.vi.md).

## Bắt đầu — không cần GPU

```bash
git clone https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference.git
cd Multilingual-Translation-AI-Inference

python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

cp .env.example .env
# Thay Bearer token mẫu trong .env bằng token ngẫu nhiên dùng local.
python scripts/local_demo.py

python -m pytest -q
python -m ruff check .
python scripts/audit_public_repository.py
```

Demo local dùng kết quả giả lập để kiểm tra API và database,
**không tải hoặc chạy các model GPU**. Triển khai thật cần tài
khoản Modal và PostgreSQL riêng, theo
[hướng dẫn triển khai](docs/deployment.vi.md).

## Ví dụ gọi API

Chỉ gửi yêu cầu dịch thật sau khi triển khai server và bật
dispatcher `modal-gpu` trong Modal Secret riêng:

```bash
export BASE_URL="https://YOUR_DEPLOYED_GATEWAY.modal.run"
# Nạp TRANSLATION_API_BEARER_TOKEN từ nơi lưu trữ riêng tư.

curl -fsS -X POST "$BASE_URL/v1/jobs/translations" \
  -H "Authorization: Bearer $TRANSLATION_API_BEARER_TOKEN" \
  -H "Idempotency-Key: example-translation-001" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hy_mt2_30b",
    "source_language": "en",
    "target_language": "vi",
    "text": "The little fox crossed the bridge at sunrise.",
    "options": {"preserve_formatting": true}
  }'
```

API trả HTTP 202, `job_id` và `status_url`. Gọi
`GET /v1/jobs/{job_id}` với cùng Bearer token để xem trạng thái.
Muốn so sánh nhiều model thì gọi `POST /v1/jobs/benchmarks` với
danh sách `models` thay cho một `model`.
Xem [tài liệu API/developer](docs/development.vi.md).

## Tài liệu

| Chủ đề | English | Tiếng Việt |
|---|---|---|
| Kiến trúc | [Architecture](docs/architecture.md) | [Kiến trúc](docs/architecture.vi.md) |
| Cài đặt | [Deployment](docs/deployment.md) | [Triển khai](docs/deployment.vi.md) |
| Biến môi trường | [Configuration](docs/configuration.md) | [Cấu hình](docs/configuration.vi.md) |
| Danh sách model | [Models](docs/models.md) | [Model](docs/models.vi.md) |
| Chất lượng bản dịch | [Benchmarking](docs/benchmarking.md) | [Đánh giá](docs/benchmarking.vi.md) |
| Độ tin cậy | [Reliability](docs/reliability.md) | [Độ tin cậy](docs/reliability.vi.md) |
| Giám sát và ngân sách | [Operations](docs/operations.md) | [Vận hành](docs/operations.vi.md) |
| Phát triển local | [Development](docs/development.md) | [Phát triển](docs/development.vi.md) |
| Quyết định kỹ thuật | [Decisions](docs/design-decisions.md) | [Quyết định](docs/design-decisions.vi.md) |
| Việc còn lại | [Roadmap](docs/roadmap.md) | [Lộ trình](docs/roadmap.vi.md) |
| Giấy phép model | [Model licenses](MODEL_LICENSE.md) | [Giấy phép model](MODEL_LICENSE.vi.md) |

Báo cáo thử nghiệm máy được giữ trong [`reports/`](reports).
Xem [đóng góp](.github/CONTRIBUTING.vi.md),
[bảo mật](.github/SECURITY.vi.md),
[hỗ trợ](.github/SUPPORT.vi.md) và [changelog](CHANGELOG.vi.md).

## Bản quyền và ghi công

**Mã nguồn riêng của dự án:** MIT © 2026
**Đăng Khoa <i.am@dangkhoa.dev>** — xem [LICENSE](LICENSE).

Bốn model và các bản GGUF là **trọng số bên thứ ba**, có metadata
giấy phép Apache-2.0 từ upstream và bản quyền thuộc tác giả gốc.
MIT **không** cấp phép lại các trọng số đó.
Xem [MODEL_LICENSE.vi.md](MODEL_LICENSE.vi.md) và
[thông báo bên thứ ba](NOTICE.vi.md) trước khi phân phối hoặc dùng thương mại.

Đây là dự án kỹ thuật độc lập, không phải sản phẩm chính thức của Tencent,
IndexTeam, Google, Unsloth, Qwen hoặc Modal.
