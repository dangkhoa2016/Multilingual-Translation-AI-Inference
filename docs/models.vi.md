# Danh sách model và nguồn có thể tái lập

> 🌐 Language / Ngôn ngữ: [English](models.md) | **Tiếng Việt**

Bốn backend dịch thuật thuộc **bốn dòng model khác nhau**, không phải
bốn bản sao cùng trọng số. Mỗi model dùng GGUF `Q8_0` và một GPU
**NVIDIA L40S 48 GB** độc lập, có thể scale-to-zero.

| API model key | Tên model đầy đủ | Nhà phân phối GGUF | Dung lượng | Giấy phép |
|---|---|---|---:|---|
| `hy_mt2_30b` | Tencent Hy-MT2-30B-A3B | Tencent | 31,99 GB | Apache-2.0 |
| `index_35b` | Index-Translate-35B-A3B-preview | IndexTeam | 37,80 GB | Apache-2.0 |
| `gemma4_31b_it` | Google Gemma 4 31B IT | Unsloth | 32,64 GB | Apache-2.0 |
| `qwen35_35b` | Qwen3.5-35B-A3B | Unsloth | 36,90 GB | Apache-2.0 |

**Truy vết nguồn:** [manifest bất biến](../models/four_l40s_workers_q8_0_manifest.json)
ghi rõ repo và revision checkpoint, repo và revision GGUF, file, dung
lượng, SHA256, Volume và kết quả xác minh runtime. Worker kiểm tra
marker đã xác minh SHA256 cùng kích thước file trước khi load.
GPU không tải trọng số mới mỗi request.

## Tương thích GPU đã đo thực tế

Cả bốn model đã load GGUF Q8_0 và trả bản dịch Anh → Việt không rỗng.
Lần thử đồng thời ghi nhận bốn GPU UUID riêng và các khoảng xử lý có giao nhau.

| Model | Thời gian load đến ready | VRAM cao nhất lấy mẫu |
|---|---:|---:|
| Tencent Hy-MT2 | 20,60 giây | 31.151 MiB |
| Index-Translate | 24,77 giây | 35.335 MiB |
| Gemma 4 IT | 16,27 giây | 32.973 MiB |
| Qwen3.5 | 27,16 giây | 35.336 MiB |

Số liệu từ [tổng hợp thực thi GPU](../reports/four_gpu_parallel_inference.json).
Runtime dùng revision CUDA `llama.cpp` đã xác minh, tham số decoding
theo model, context 4.096 token và một luồng inference mỗi container.

## Tùy chỉnh tham số riêng cho từng model

Hai endpoint `POST /v1/jobs/translations` và `POST /v1/jobs/benchmarks` nhận
`model_configs` **không bắt buộc**, chứa các cấu hình theo API model key đã chọn.
Mỗi model nhận tham số riêng; tham số không truyền sẽ dùng giá trị mặc định
tương ứng. Không cần sửa hay build lại GPU worker cho mỗi yêu cầu.

```json
{
  "models": ["hy_mt2_30b", "qwen35_35b"],
  "source_language": "en",
  "target_language": "vi",
  "text": "The fox crossed the bridge.",
  "options": {"preserve_formatting": true},
  "model_configs": {
    "hy_mt2_30b": {"temperature": 0.2, "top_p": 0.9, "max_tokens": 1024},
    "qwen35_35b": {"temperature": 0.65, "top_k": 30, "seed": 1234}
  }
}
```

Khi dịch một model, sử dụng `model` thay `models` và chỉ cấu hình model
được chọn. Bỏ `model_configs` hoặc dùng `{}` thì giữ nguyên mặc định decoding
và idempotency hash của API cũ.

**Những tham số hỗ trợ theo model:**

- Sampling: `temperature`, `top_p`, `top_k`, `min_p`, `typical_p`,
  `top_n_sigma`, `dynatemp_range`, `dynatemp_exponent`, `xtc_probability`,
  `xtc_threshold`, `mirostat`, `mirostat_tau`, `mirostat_eta`.
- Chống lặp: `repeat_penalty`, `repeat_last_n`, `frequency_penalty`,
  `presence_penalty`, `dry_multiplier`, `dry_base`, `dry_allowed_length`,
  `dry_penalty_last_n`.
- Đầu ra: `max_tokens` (1–3072, mặc định 1536), `seed` (-1–4294967295),
  `stop` (1–8 chuỗi không rỗng, tối đa 100 ký tự mỗi chuỗi),
  `ignore_eos` (Boolean), `enable_thinking` (Boolean, tùy chọn).

API trả HTTP 422 nếu có khóa không hỗ trợ, số vô hạn/NaN, sai kiểu,
ngoài giới hạn hoặc cấu hình model chưa được chọn. Ví dụ:
`temperature` 0–2, `top_p`/`min_p` 0–1, `top_k` -1–1000.
Giá trị mặc định từng model nằm ở
`src/multilingual_translation_ai_inference/model_options.py` và chỉ được
áp dụng với tham số không bị ghi đè. Cấu hình khi gửi job được lưu trong
PostgreSQL, được tái sử dụng nếu chủ động retry một run đã xác nhận thất bại.
Đổi config nhưng giữ nguyên `Idempotency-Key` sẽ nhận HTTP 409;
hãy dùng key mới cho tác vụ mới.

**Không thể ghi đè theo request:** GGUF/revision, `ctx_size`,
GPU layers, batch/ubatch size, concurrency, tham số khởi động llama-server,
chat messages tùy ý, `stream` và nội bộ server. Đây là cấu hình engine/deployment,
không phải tham số decoding của một yêu cầu. Cấu hình hiện tại có context
4.096 token; ngân sách đầu ra không bảo đảm đủ context cho mọi prompt.
`enable_thinking=true` có thể tạo câu trả lời dạng reasoning và bị pipeline
chỉ-dịch-thuật từ chối. Chưa có benchmark GPU xác minh chất lượng/chi phí
với các cấu hình tùy chỉnh mới.

## Hợp đồng đầu vào

Gateway chấp nhận bất kỳ mã hoặc tên ngôn ngữ nào (ví dụ `fr`,
`zh-Hant`, `Arabic`), không giới hạn danh sách. Nhãn nguồn và đích phải khác nhau sau khi so sánh
không phân biệt hoa/thường (`en`/`EN` trùng nhau); alias như `en`/`English`
không tự động được coi là tương đương. Nhãn phải in được, có chữ cái và dài
1–64 ký tự. Model có thể trả
`UNSUPPORTED_LANGUAGE_PAIR` hoặc dịch sai mà không báo lỗi;
**việc nhận job không xác nhận chất lượng dịch**.
Giới hạn là 1.000 Unicode code point, không phải 1.000 byte UTF-8.

Xem [nghiệm thu độ tin cậy của API](reliability.vi.md) và
[giấy phép model](../MODEL_LICENSE.vi.md). Khi đổi revision hay
quantization, phải xác minh lại artifact trước khi tin kết quả cũ.
