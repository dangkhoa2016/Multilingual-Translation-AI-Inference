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

Số liệu từ [báo cáo GPU](../reports/four_gpu_parallel_inference.json);
**không phải VRAM peak chính xác, SLA hay chứng nhận chất lượng dịch**.
Runtime dùng revision CUDA `llama.cpp` đã xác minh, tham số decoding
theo model, context 4.096 token và một luồng inference mỗi container.

## Hợp đồng đầu vào

Gateway chấp nhận mã ngôn ngữ `en`, `vi`, `de`, `ja`, `ko`,
và yêu cầu nguồn khác đích. Đây là **các hướng API chấp nhận**,
không đồng nghĩa chất lượng dịch đã được chứng nhận.
Giới hạn là 1.000 Unicode code point, không phải 1.000 byte UTF-8.

Xem [đánh giá chất lượng](benchmarking.vi.md) và
[giấy phép model](../MODEL_LICENSE.vi.md). Khi đổi revision hay
quantization, phải xác minh lại artifact trước khi tin kết quả cũ.
