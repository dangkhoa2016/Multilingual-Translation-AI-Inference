# Model matrix — Translation AI Inference (P0)

**Ngày kiểm tra:** 2026-11-06
**Trạng thái:** kiểm tra nguồn công khai; **chưa chạy trên Modal L40S** và **chưa pin SHA256**.
**Nguồn cơ sở:** bản handoff ngày 2026-11-06, lưu trong [`implementation-plan.vi.md`](implementation-plan.vi.md) (đã cập nhật quy ước tên PostgreSQL trung lập).

## 1. Danh sách ứng viên và Q8_0

| Key | Checkpoint (base/original) | GGUF repo | Chính xác file Q8_0 | GGUF size công bố | License hiện hiển thị | Runtime ở mức tài liệu |
|---|---|---|---|---:|---|---|
| `hy_mt2_30b` | `tencent/Hy-MT2-30B-A3B` | `tencent/Hy-MT2-30B-A3B-GGUF` | `Hy-MT2-30B-A3B-Q8_0.gguf` | ~32.0 GB | Apache-2.0 | Repo GGUF có hướng dẫn llama.cpp; GPU smoke chưa chạy |
| `index_35b` | `IndexTeam/Index-Translate-35B-A3B-preview` | `IndexTeam/Index-Translate-35B-A3B-preview-GGUF` | `Index-Translate-35B-A3B-preview.Q8_0.gguf` | ~37.8 GB | Apache-2.0 | GGUF chính chủ, chuyển đổi bằng llama.cpp (10/2026); GPU smoke chưa chạy |
| `gemma4_31b_it` | `google/gemma-4-31B-it` | `unsloth/gemma-4-31B-it-GGUF` | `gemma-4-31B-it-Q8_0.gguf` | ~32.6 GB | Apache-2.0 | Unsloth có hướng dẫn llama.cpp; GPU smoke chưa chạy |
| `qwen35_35b` | `Qwen/Qwen3.5-35B-A3B` | `unsloth/Qwen3.5-35B-A3B-GGUF` | `Qwen3.5-35B-A3B-Q8_0.gguf` | ~36.9 GB | Apache-2.0 | Unsloth có hướng dẫn llama.cpp; GPU smoke chưa chạy |

**Quan trọng:** Những kích thước này là trọng lượng file GGUF được nhà phát hành liệt kê, **không phải peak GPU VRAM**. Tổng dung lượng tham khảo của bốn file Q8_0 là ~139.3 GB (không phải dung lượng GPU đồng thời). Mỗi model có **một L40S 48GB** riêng. Với Index và Qwen, headroom tính từ kích thước file còn tương đối hạn chế, chưa trừ KV cache, compute buffer và CUDA overhead.

### Tính chính xác của tên checkpoint

- `gemma4_31b_it`: model instruction-tuned `-it`, **không phải base**.
- `index_35b`: checkpoint **`-preview`** có weights, không lấy trang tên không `preview` làm nguồn.
- `qwen35_35b`: ID không có hậu tố `-Base`; tắt thinking bằng chat template khi phục vụ translation, nếu runtime thực sự hỗ trợ.
- Không cần `mmproj` cho **text-only** ở v1. Không tải model qua HF theo từng request: weights đưa vào Modal Volume sau khi pin và verify.

## 2. Chính sách prompt/decoding phải tách theo model

| Model | Khuyến nghị được công bố | Điểm phải smoke-test |
|---|---|---|
| Hy-MT2 30B | `temperature=0.7`, `top_p=1.0`, `top_k=-1`, `repetition_penalty=1.0`, `max_tokens=4096`; prompt dịch có thể là tiếng Anh và yêu cầu *chỉ xuất bản dịch*. | Engine có áp dụng đúng top-k=-1/chat template không; đúng hướng EN↔VI/DE↔VI/JA↔VI/KO↔VI |
| Index-Translate preview | `temperature=0` / greedy, `enable_thinking=false`, dùng chat template. Prompt chỉ dẫn dịch riêng. | `llama.cpp` `--jinja --chat-template-kwargs '{"enable_thinking":false}'` khả dụng trên bản build pin; không leak thinking |
| Gemma 4 31B IT | Model card: `temperature=1.0`, `top_p=0.95`, `top_k=64`; thinking kiểm soát bởi token hệ thống `<|think|>`; không kích hoạt cho translation v1. | Chat template đặc thù Gemma 4, không rò các control tokens, kết quả tiếng đích hợp lệ |
| Qwen3.5 35B A3B | Model card mô tả non-thinking `chat_template_kwargs={"enable_thinking":false}` và tham số chung `temperature=0.7`, `top_p=0.8`, `top_k=20`; hỗ trợ tùy engine. | Disable thinking có được áp dụng thật trong engine GGUF; kết quả không có `<think>` |

**Không ép tất cả model `temperature=0`**, vì nhà phát hành Hy-MT2 đưa khuyến nghị khác. Đóng băng prompt version và runtime version trước benchmark; với Index có thể thử thêm prompt đầy đủ cho thuật ngữ và format, nhưng không điều chỉnh theo held-out test.

## 3. Các gate chưa qua — không chuyển sang P3

| Hạng mục | Trạng thái | Chứng cứ cần thu |
|---|---|---|
| GGUF file công khai và tên đúng | **Đã đối chiếu trang model** | HF file listings |
| License Apache-2.0 trên model cards | **Đã thấy thông tin công khai** | Kiểm chứng license file và các nghĩa vụ downstream trước phát hành |
| Revision SHA40 của cả 4 repo | **Chưa pin** | Script `scripts/verify_hf_metadata.py` |
| SHA256 của từng GGUF blob | **Chưa pin / chưa tải** | HF LFS/Xet metadata, xác minh lại hash trên file tải về |
| engine llama.cpp commit/CUDA pinned | **Chưa** | Khóa commit + build image digest + smoke logs |
| Prompt và chat template đúng | **Đã đọc khuyến nghị**, chưa runtime test | Output test mỗi model |
| Peak VRAM, warm/cold start, tokens/s | **Chưa đo** | Modal GPU logs/metrics |
| Modal L40S quota, region, concurrency, budget | **Chưa kiểm tra tài khoản** | Modal console/CLI authenticated |
| Neon project / branch, limits hiện hành | **Limits công khai đã kiểm**, tài khoản chưa | Neon console authenticated |
| Bản benchmark cũ sẵn có và hash đúng | **Chưa nhập** | Dữ liệu + manifest |

## 4. Các nguồn kiểm chứng trực tiếp (truy cập 2026-11-06)

- Hy-MT2: https://huggingface.co/tencent/Hy-MT2-30B-A3B
- Hy-MT2 GGUF files: https://huggingface.co/tencent/Hy-MT2-30B-A3B-GGUF/tree/main
- Index preview: https://huggingface.co/IndexTeam/Index-Translate-35B-A3B-preview
- Index official GGUF: https://huggingface.co/IndexTeam/Index-Translate-35B-A3B-preview-GGUF
- Gemma 4 instruction: https://huggingface.co/google/gemma-4-31B-it
- Gemma 4 GGUF files: https://huggingface.co/unsloth/gemma-4-31B-it-GGUF/tree/main
- Qwen3.5: https://huggingface.co/Qwen/Qwen3.5-35B-A3B
- Qwen3.5 GGUF files: https://huggingface.co/unsloth/Qwen3.5-35B-A3B-GGUF/tree/main

Các dữ kiện tại đây được xác minh ở mức **tài liệu công khai**, không đại diện một lần triển khai hoặc đánh giá chất lượng độc lập.


## 5. P3 Hy-MT2 pinning update — 2026-11-07

The first model `hy_mt2_30b` now has an immutable official checkpoint revision,
an official GGUF revision, an exact Q8_0 file name, byte size, Hugging Face
LFS/Xet SHA256 and bounded GGUF header verification. The pinned upstream
llama.cpp source also contains `hy_v3` loading code.

Evidence, offline/online verifier and exact model lock:

- [P3 Hy-MT2 readiness](p3-hy-mt2-readiness.md)
- [Machine-readable Hy-MT2 lock](../models/hy_mt2_30b_q8_0.lock.json)
- `scripts/verify_hy_mt2_p3.py --online`

**Do not conflate SHA256 read from HF metadata with SHA256 recomputed on
the entire downloaded 31.99 GB file.** The full-file check and real L40S
load test have **not** passed. Index, Gemma 4 and Qwen3.5 remain unpinned
and unverified in P3; do not infer their readiness from Hy-MT2.
