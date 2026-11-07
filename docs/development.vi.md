# Tài liệu API và phát triển local

> 🌐 Language / Ngôn ngữ: [English](development.md) | **Tiếng Việt**

Dùng [API contract](#api-contract) để tích hợp ứng dụng, hoặc làm theo phần
thiết lập local bên dưới để tìm hiểu mã nguồn và đóng góp thay đổi.
Bạn có thể chạy demo và test tự động mà không cần GPU hay tài khoản cloud.

## Cấu trúc repository

Mã nguồn và các công cụ được nhóm theo chức năng:

| Thư mục | Mục đích |
|---|---|
| `src/multilingual_translation_ai_inference/` | Package API, database, job và GPU runtime |
| `scripts/api/` | Kiểm thử API và reliability |
| `scripts/deployment/` | Công cụ triển khai và cấu hình Modal |
| `scripts/models/` | Metadata, tải model, build CUDA và GPU probe dùng chung |
| `scripts/operations/` | Bảo trì database và kiểm tra vận hành |
| `scripts/examples/` | Demo local |
| `tests/api/`, `tests/database/`, `tests/inference/`, `tests/models/`, `tests/operations/` | Regression test API, lưu trữ, inference, model và vận hành |
| `tests/documentation/`, `tests/evidence/`, `tests/integration/`, `tests/notebook/`, `tests/security/` | Kiểm tra tài liệu, bằng chứng đã ghi nhận, tích hợp, notebook và an toàn công bố |

Kiểm tra metadata model mà không cấp phát GPU:

~~~bash
python -m scripts.models.verify_manifest
python -m scripts.models.verify_gguf
~~~


Dự án viết bằng Python, FastAPI, SQLAlchemy, PostgreSQL và Modal.
Có thể kiểm thử API cũng như state machine của job **không cần GPU
hoặc tài khoản cloud**.

## Chạy local

```bash
git clone https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference.git
cd Multilingual-Translation-AI-Inference
git checkout v1.0.0
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/examples/local_demo.py
```

Ví dụ tự tạo SQLite tạm và dùng Bearer token demo trong mã nguồn,
không đọc `.env`, không kết nối mạng hoặc dùng GPU. Kết quả mock được
đánh dấu rõ để bạn tìm hiểu luồng job trên máy cá nhân.
Chỉ tạo `.env` khi dùng công cụ cần credentials, chạy migration hoặc
triển khai thật; xem [cấu hình](configuration.vi.md).

## Kiểm thử

```bash
python -m pytest -q
python -m ruff check .
python -m compileall -q src modal_app.py scripts tests
python -m pytest -q tests/security/test_publication_safety.py
```

GitHub Actions chạy test CPU và kiểm tra an toàn xuất bản. Không đưa token,
database URL thật hoặc trọng số model vào fixture, log hay pull request.

### Bộ phụ thuộc của gateway triển khai

CI kiểm tra cả bộ phụ thuộc mặc định và bộ dùng cho gateway triển khai.
Để kiểm tra bộ thứ hai, tạo và kích hoạt một virtual environment riêng, rồi chạy:

```bash
python -m pip install -c constraints/deployed-gateway.txt -e '.[dev]'
python -m pip check
python -m pytest -q
```

Constraints khóa ba thư viện API chính; các phụ thuộc gián tiếp vẫn linh hoạt.
Trên Windows, dùng `.\.venv\Scripts\python.exe` thay cho `python` trong các lệnh trên.

CI cũng chạy kiểm thử transaction trên một dịch vụ PostgreSQL riêng biệt.
Để chạy local, đặt riêng `TRANSLATION_TEST_POSTGRESQL_URL` trỏ đến
**database dành riêng cho kiểm thử**, rồi chạy
`python -m pytest -q tests/database/test_postgresql_job_safety.py`.
Tài khoản kiểm thử cần quyền tạo và xóa schema: mỗi test dùng một schema
riêng và xóa sau khi chạy. Khi chưa đặt biến này, các kiểm thử PostgreSQL
được bỏ qua; những test CPU còn lại vẫn dùng SQLite.

## API contract

- `GET /health`: trạng thái process công khai, không kiểm tra GPU sâu.
- `GET /v1/models`: danh sách model có xác thực.
- `POST /v1/jobs/translations`: dịch một model, HTTP 202.
- `POST /v1/jobs/benchmarks`: benchmark 1–4 model, HTTP 202.
- `GET /v1/jobs/{job_id}`: polling có xác thực.
- `POST /v1/jobs/{job_id}/runs/{run_id}/retry`: chỉ retry
  lỗi đã xác nhận, theo quota.

Văn bản phải mã hóa được thành UTF-8 và không chứa ký tự NUL. Surrogate
Unicode đơn lẻ và NUL trả HTTP 422 trước khi nhận job. Unicode hợp lệ, emoji,
xuống dòng và tab được giữ nguyên tại đầu vào. Lỗi validation không trả lại
giá trị đã gửi, context của validator hoặc tên field JSON tùy ý; tên field
không được nhận diện hiển thị là `unknown_field`.

Bản dịch hoàn tất giữ nguyên khoảng trắng ở đầu/cuối do engine trả về.
`preserve_formatting` chỉ là hướng dẫn cho model theo khả năng của nó,
không cam kết bảo toàn chính xác mọi chi tiết bố cục.

Request một model cho `POST /v1/jobs/translations`:

```json
{
  "model": "hy_mt2_30b",
  "source_language": "en",
  "target_language": "vi",
  "text": "The little fox crossed the bridge at sunrise.",
  "options": {"preserve_formatting": true}
}
```

Với `POST /v1/jobs/benchmarks`, dùng `models` (số nhiều) thay cho `model`:

```json
{
  "models": ["hy_mt2_30b", "qwen35_35b"],
  "source_language": "en",
  "target_language": "vi",
  "text": "The little fox crossed the bridge at sunrise.",
  "options": {"preserve_formatting": true}
}
```

Ví dụ này yêu cầu chạy hai model. Chọn từ 1–4 model key khác nhau để xác
định backend. **Bỏ trường `models` sẽ chọn cả bốn model đã đăng ký**,
nên yêu cầu ở chế độ GPU có thể phát sinh phí cho cả bốn run. Ghi rõ
danh sách khi chỉ muốn so sánh ít model hơn. Mỗi yêu cầu mới nên dùng
một `Idempotency-Key` riêng.

Dùng `Authorization: Bearer YOUR_TOKEN`; nên có
`Idempotency-Key` để tránh tạo trùng. Văn bản phải có 1–1.000
Unicode code point không rỗng; nhãn nguồn và đích phải khác nhau khi so sánh
không phân biệt hoa/thường. Các alias như `en` và `English` không tự động được
chuẩn hóa. Có thể nhập bất kỳ mã hoặc tên ngôn ngữ in được (1–64 ký tự,
có chữ cái); việc nhận job không bảo đảm model dịch chính xác cặp ngôn ngữ đó.

### JobSubmitted và JobView — response và quy tắc polling

**HTTP 202** sau POST trả về `JobSubmitted`. Các UUID và JSON dưới đây là **ví dụ giả lập để giải thích hợp đồng**, không phải kết quả inference thật:

```json
{
  "job_id": "00000000-0000-0000-0000-000000000001",
  "status": "queued",
  "kind": "translation",
  "status_url": "/v1/jobs/00000000-0000-0000-0000-000000000001"
}
```

Gọi GET với đường dẫn **tương đối** `status_url` trên gateway riêng, dùng **cùng Bearer token**. Endpoint `GET /v1/jobs/{job_id}` có xác thực trả về `JobView`: `job.status` là trạng thái tổng hợp, kèm cặp ngôn ngữ và mảng `runs[]` chứa từng lần chạy model.

Ví dụ **benchmark bốn model giả lập** dưới đây cố ý có model hoàn tất (mock), model lỗi đã xác nhận, model chưa xác định kết quả thực thi và model còn đang chạy. **Không phải kết quả GPU thật hoặc điểm chất lượng dịch.**

```json
{
  "job_id": "00000000-0000-0000-0000-000000000010",
  "kind": "benchmark",
  "status": "execution_uncertain",
  "source_language": "en",
  "target_language": "vi",
  "runs": [
    {
      "run_id": "00000000-0000-0000-0000-000000000011",
      "model": "hy_mt2_30b",
      "attempt_no": 1,
      "status": "completed",
      "translation_text": "[MOCK ONLY — NOT A TRANSLATION]",
      "is_mock_result": true,
      "error_code": null
    },
    {
      "run_id": "00000000-0000-0000-0000-000000000012",
      "model": "index_35b",
      "attempt_no": 1,
      "status": "failed",
      "translation_text": null,
      "is_mock_result": false,
      "error_code": "SYNTHETIC_FAILURE"
    },
    {
      "run_id": "00000000-0000-0000-0000-000000000013",
      "model": "gemma4_31b_it",
      "attempt_no": 1,
      "status": "execution_uncertain",
      "translation_text": null,
      "is_mock_result": false,
      "error_code": "EXECUTION_STALE_UNVERIFIED"
    },
    {
      "run_id": "00000000-0000-0000-0000-000000000014",
      "model": "qwen35_35b",
      "attempt_no": 1,
      "status": "running",
      "translation_text": null,
      "is_mock_result": false,
      "error_code": null
    }
  ]
}
```

#### Telemetry hiệu năng tùy chọn theo từng lần chạy

`GET /v1/jobs/{job_id}` có xác thực trả thêm `usage`, `timings` và
`resources` **trong từng attempt** thuộc `runs[]`. API vẫn tương thích với
client cũ; đọc GET không khởi động GPU.

**Ví dụ minh họa cấu trúc response non-mock — toàn bộ văn bản và số liệu đều tự tạo, không phải kết quả đo GPU thật.** Trường `is_mock_result: false` minh họa giá trị mà *kết quả inference thật* sẽ sử dụng; không có nghĩa ví dụ này được model tạo ra.

```json
{
  "run_id": "00000000-0000-0000-0000-000000000002",
  "model": "hy_mt2_30b",
  "attempt_no": 1,
  "status": "completed",
  "translation_text": "Synthetic example only",
  "is_mock_result": false,
  "error_code": null,
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 80,
    "total_tokens": 200
  },
  "timings": {
    "queue_ms": 1450.0,
    "inference_ms": 2450.0,
    "total_ms": 4010.0,
    "prefill_ms": 350.0,
    "decode_ms": 2050.0,
    "tokens_per_second": 39.02
  },
  "resources": {
    "cpu_process_seconds": 0.36,
    "cpu_utilization_percent": 14.69,
    "sampled_vram_mib": 31200,
    "sampled_gpu_utilization_percent": 2
  }
}
```

| Trường | Ý nghĩa và đơn vị |
|---|---|
| `usage.prompt_tokens`, `completion_tokens`, `total_tokens` | Số token engine báo, không phải độ dài ký tự |
| `timings.queue_ms` | Từ tạo attempt tới khi worker bắt đầu; có thể gồm cold start |
| `timings.inference_ms` | Thời gian gọi engine tại worker, không gồm chờ |
| `timings.total_ms` | Từ tạo attempt tới khi lưu kết quả; không gồm thời gian polling của client |
| `timings.prefill_ms`, `decode_ms` | Thời gian từ engine khi có |
| `timings.prompt_per_second`, `tokens_per_second` | Tốc độ engine báo, không phải lúc nào cũng có |
| `resources.cpu_process_seconds`, `cpu_utilization_percent` | CPU của tiến trình llama.cpp khi suy luận; nhiều lõi có thể vượt 100% |
| `resources.sampled_vram_mib`, `sampled_gpu_utilization_percent` | **Một mẫu GPU sau inference**, không phải giá trị đỉnh, trung bình hay theo token |

Nhóm thiếu dữ liệu trả `null`; metric riêng lẻ không đo được sẽ bị lược bỏ.
Thiếu số đo **không có nghĩa là 0**. Token count tùy chọn không hợp lệ được bỏ
qua và không làm mất bản dịch; count hợp lệ khác trong cùng phản hồi vẫn được giữ.
Job cũ, attempt đang chờ, thất bại và
CPU mock có thể thiếu token/GPU. Mỗi lần retry có `run_id` và
`attempt_no` riêng. Telemetry không chứa raw log, credential, GPU UUID
hay đường dẫn file. Không thể suy ra hóa đơn GPU thực từ các số liệu này.

Với database cũ đã deploy, chạy migration theo
[tài liệu triển khai](deployment.vi.md) trước khi cập nhật gateway/worker.
Bản cài mới đã có cột nullable; migration `0004_run_metrics` chỉ bổ sung
cột còn thiếu trên database cũ. Không cần chạy GPU để migration.

#### Kết quả cặp ngôn ngữ không được hỗ trợ

API nhận mọi nhãn ngôn ngữ hợp lệ, không giới hạn theo whitelist. Nếu model
trả chính xác `UNSUPPORTED_LANGUAGE_PAIR`, GPU worker ghi nhận **lần chạy thất bại**
với `runs[].error_code = "UNSUPPORTED_LANGUAGE_PAIR"` và không có bản dịch.
Client cần giữ nguyên mã lỗi trong kết quả job, không đổi thành lỗi không xác định.
Đây chỉ là **tín hiệu do model tạo ra**, không phải cơ chế đáng tin cậy xác định
mọi ngôn ngữ được hỗ trợ: model vẫn có thể dịch sai hoặc tự tạo bản dịch.
Cần xem lần chạy mới nhất của từng model.

#### Ý nghĩa trạng thái

| Trạng thái | Cách hiểu và hành động an toàn |
|---|---|
| `queued` / `dispatching` / `running` | Đang chờ, đang điều phối hoặc đang thực thi; tiếp tục GET có xác thực với khoảng nghỉ giới hạn. |
| `completed` | Lần chạy model thành công; `translation_text` có thể chứa bản dịch. Phải xem `is_mock_result` trước khi kết luận đó là bản dịch thật. |
| `failed` | Lỗi model đã xác nhận, không có nghĩa mọi model đều lỗi. Chỉ retry từng lần chạy khi API và quota cho phép. |
| `partial_failed` | **Trạng thái tổng của job:** ít nhất một model thành công, một model lỗi, toàn bộ lần chạy mới nhất đều đã kết thúc với completed/failed. |
| `dispatch_uncertain` | Chưa xác minh được kết quả điều phối; cần đối soát bởi người vận hành. **Không tự POST tạo job GPU khác.** |
| `execution_uncertain` | Chưa xác minh được kết quả thực thi; cần đối soát bởi người vận hành. **Không tự POST tạo job GPU khác.** |

**Quan trọng: không được dùng riêng `job.status` để kết luận đã xong polling.** Đây là trạng thái tổng hợp từ **attempt mới nhất của mỗi model** (`attempt_no` lớn nhất), còn `runs[]` có thể chứa các attempt cũ. Đặc biệt, `job.status="execution_uncertain"` vẫn có thể xuất hiện khi **một model khác đang `running`** (như ví dụ trên). Nếu bất kỳ attempt mới nhất nào còn `queued`, `dispatching` hoặc `running`, hãy tiếp tục GET. Khi mọi attempt mới nhất đều thuộc `completed` hoặc `failed`, job đã giải quyết xong; trạng thái tổng là `completed`/`partial_failed`/`failed`. Nếu không còn run đang xử lý nhưng còn `dispatch_uncertain` hoặc `execution_uncertain`, đây **không phải kết quả cuối đã xác nhận**: giữ UUID, đối soát phía vận hành và GET lại khi phù hợp. Không tự retry run hoặc POST khi chưa rõ trạng thái.

**Thuật ngữ:** `attempt` là một lần thực thi model, xác định bởi `run_id` và `attempt_no`. `admission` là bước kiểm tra quota/đặt trước ngân sách ước lượng trong transaction trước khi điều phối; **không phải số tiền Modal thực tế**. `runtime_verified` là metadata đã ghi nhận về xác minh runtime, **không xác nhận GPU worker đang hoạt động hoặc chất lượng bản dịch**. Trường `enabled` cũ chỉ nói model có thể nhận job ở chế độ GPU, **không** nói GPU đang bật. `dispatch_enabled` thể hiện chế độ điều phối; `runtime_status="not_checked"` nghĩa là GET không kiểm tra GPU trực tiếp. Các lần xác thực sai được giới hạn theo từng process gateway; xem [bảo mật](security.vi.md).

## Đóng góp mã nguồn và tài liệu

Giữ logic inference đặc thù model trong runtime GPU. Bảo toàn
transaction PostgreSQL và claim token chống chạy trùng.
Tài liệu Markdown hướng tới người dùng phải có bản tiếng Anh/Việt
tương ứng và liên kết chuyển ngôn ngữ. Ưu tiên commit nhỏ, rõ mục
đích, có test phù hợp.

Xem [hướng dẫn đóng góp](../.github/CONTRIBUTING.vi.md),
[kiến trúc](architecture.vi.md) và [bảo mật](../.github/SECURITY.vi.md).
