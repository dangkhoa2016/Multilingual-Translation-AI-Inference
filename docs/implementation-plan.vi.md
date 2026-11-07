# KẾ HOẠCH TRIỂN KHAI — Translation AI Inference trên Modal + PostgreSQL

> **Bản dự thảo để duyệt** · Ngày lập: **2026-11-06** · Ngôn ngữ: **Tiếng Việt**
> **Trạng thái:** Chưa triển khai, chưa tạo database, chưa tiêu tốn GPU cho dự án này.
> **Cập nhật tên tài nguyên (2026-11-07):** App/Secrets và env vars dùng tên trung lập với nhà cung cấp PostgreSQL. Neon chỉ là phương án host dự kiến; xem `docs/decisions/ADR-0003-postgresql-provider-independent-configuration.md`.
> **Mục tiêu:** Chất lượng dịch thuật cao nhất có thể trong giới hạn **1 GPU NVIDIA L40S 48 GB cho mỗi model**, tối ưu **scale-to-zero** vì tần suất sử dụng API rất thấp.

---

## 1. Quyết định kiến trúc

### 1.1. Những điều đã thống nhất

- **Một source repository** cho API, model adapters, Modal Functions, migrations, benchmark, tests và tài liệu.
- **Một Modal App**, gồm một **FastAPI CPU gateway** và **4 inference Function/Class độc lập**; mỗi Function dùng **1 GPU L40S 48 GB** khi có việc.
- **`min_containers=0`, `buffer_containers=0`, `max_containers=1`** cho từng GPU Function trong giai đoạn đầu; không giữ GPU hoạt động 24/7.
- **Background jobs dùng Modal `spawn()`**, không chạy worker poll Redis/Postgres vô hạn trong container GPU.
- **PostgreSQL (dự kiến ban đầu được host tại Neon)** là hệ thống lưu trạng thái job, kết quả dịch, benchmark và thống kê; không lưu weights vào database.
- **Model weights dạng GGUF Q8_0**, triển khai bằng `llama.cpp`/`llama-server` **nếu đã xác minh tương thích chính xác** với từng kiến trúc; không mặc định engine nào cũng chạy được mọi model.
- **API chỉ thỉnh thoảng mới có traffic**; ưu tiên giảm chi phí cố định, chấp nhận cold start và đo thời gian thực tế.
- **Đầu vào mục tiêu khoảng 1.000 ký tự/đoạn**; phục vụ dịch văn bản (text-only). Không cần tải `mmproj` chỉ để dịch chữ.
- **Chung code, độc lập autoscaling:** mỗi Function tự bật/tắt; một yêu cầu chỉ gọi 1 model hoặc có thể fan-out gọi 4 model.

### 1.2. Sơ đồ luồng xử lý

```text
Client / Rails 8 / Benchmark script
                  |
                  | HTTPS + Bearer API key
                  v
       Modal FastAPI Gateway (CPU)
       - Validation, auth, rate limit
       - Idempotency, create/read jobs
                  |
           +------+------+
           |             |
           v             v
   Neon PostgreSQL   Modal .spawn()
   (source of truth)     |
                         +---------+---------+---------+
                         |         |         |         |
                         v         v         v         v
                     Hy-MT2     Index    Gemma 4     Qwen3.5
                     L40S       L40S       L40S       L40S
                         |         |         |         |
                         +---------+---------+---------+
                                       |
                              Update PostgreSQL results
                                       |
                         GET /v1/jobs/{job_id}
```

**Nguyên tắc:** Gateway ngủ không làm mất các job đã được Modal tiếp nhận. GPU không bị scale-down vì “không có HTTP request” trong lúc một Function vẫn đang xử lý job. Tuy nhiên container vẫn có thể lỗi hoặc hết timeout; phải có retry, idempotency và reconciliation.

---

## 2. Danh sách 4 model và kiểm chứng nguồn

**Chưa chọn model mặc định theo cảm tính.** Cả bốn là ứng viên để đo chất lượng trên cùng tập benchmark.

| ID nội bộ | Checkpoint chính xác | GGUF Q8_0 đề xuất | Dung lượng weights tham khảo | Ưu tiên |
|---|---|---|---:|---|
| `hy_mt2_30b` | `tencent/Hy-MT2-30B-A3B` | `tencent/Hy-MT2-30B-A3B-GGUF` | ~32,0 GB | 1 |
| `index_35b` | `IndexTeam/Index-Translate-35B-A3B-preview` | `IndexTeam/Index-Translate-35B-A3B-preview-GGUF` | ~37,8 GB | 1 |
| `gemma4_31b_it` | **`google/gemma-4-31B-it`** | `unsloth/gemma-4-31B-it-GGUF` | ~32,6 GB | 2 |
| `qwen35_35b` | **`Qwen/Qwen3.5-35B-A3B`** *(bản instruction, không dùng `-Base`)* | `unsloth/Qwen3.5-35B-A3B-GGUF` | ~36,9 GB | 2 |

**Điều chỉnh quan trọng từ thảo luận trước:** Gemma 4 phải là **bản instruction-tuned `-it`**, không phải `google/gemma-4-31B` base. Với Index-Translate, triển khai **checkpoint `preview` có weights**; không dùng nhầm trang `Index-Translate-35B-A3B` ghi “weights coming soon”.

**Không lấy dung lượng file GGUF làm peak VRAM.** Cần đo thêm KV cache, compute buffers, CUDA context và overhead. Trong 48 GB VRAM, bản Q8_0 37–38 GB có **ít headroom hơn** và có thể phải giảm batch/context nếu OOM.

### 2.1. Phương pháp xác thực trước tải weights

- [ ] Chốt **repo ID + commit/revision + tên file + SHA256** cho từng checkpoint.
- [ ] Kiểm tra **Apache-2.0** và giấy phép, file license, provenance của bản GGUF.
- [ ] Kiểm tra file đã đủ shard và chat template đúng; không tải projector khi chỉ làm text translation.
- [ ] Kiểm tra `llama.cpp` build/CUDA runtime tương thích `hy_v3`, `qwen3_5_moe`, `gemma4`.
- [ ] Kiểm thử prompt riêng từng model; không áp dụng chung một prompt/decoding nếu tác giả model có khuyến cáo khác.
- [ ] Khởi động từng model riêng trên L40S, xác minh **GPU load thành công + dịch đúng 1 câu + peak VRAM < 48 GB**.
- [ ] Nếu Q8_0 không ổn định: thử rút context/concurrency trước, rồi **Q6_K** nếu cần; mọi thay đổi quant phải đo lại chất lượng.

### 2.2. Các model đối chứng (không cần GPU deployment thường trực)

- TranslateGemma-12B-IT hoặc kết quả benchmark TranslateGemma đã có từ các thử nghiệm trước.
- Các output lịch sử của những model khác nếu dữ liệu/phiên bản thực tế còn có thể xác minh.
- Không tuyên bố “model X dịch tốt nhất” trước khi có benchmark so sánh mù và kiểm duyệt thủ công.

---

## 3. Yêu cầu chức năng

### 3.1. Dịch bằng một model

- Chọn model, ngôn ngữ nguồn, ngôn ngữ đích, văn bản và tùy chọn phong cách/thuật ngữ.
- Giai đoạn đầu: **1–1.000 ký tự** (định nghĩa cách đếm ký tự Unicode nhất quán tại API; cho phép xuống dòng).
- Trả `job_id` qua API async là **luồng mặc định** để không bị HTTP timeout vì cold start.
- Hỗ trợ **sync tùy chọn** cho request ngắn nếu chạy đủ nhanh; khi timeout phải chuyển/hướng sang async, không sinh job trùng.
- Kết quả phải chỉ chứa bản dịch theo yêu cầu, không lẫn prompt, giải thích hoặc thinking tags.

### 3.2. So sánh cả bốn model

- Một lần submit tạo một **benchmark job** và tối đa 4 **model runs** độc lập.
- Fan-out lên các Modal Functions tương ứng, cho phép chạy song song nếu quota GPU cho phép.
- Fan-in kết quả theo `job_id`, **partial results** được hiển thị kể cả khi một model thất bại.
- Ghi lại model version, prompt version, quant, tốc độ, cold start, usage và trạng thái từng run.
- Người dùng có thể xem lại bản dịch sau khi GPU đã scale-to-zero.

### 3.3. Ngoài phạm vi bản đầu tiên

- Dịch ảnh/PDF/OCR/video; không triển khai `mmproj` trong v1.
- Streaming token realtime trong v1 (cân nhắc sau).
- Cân bằng tải đa GPU cho một model, autoscaling nhiều container, batching lớn và queue ưu tiên.
- Fine-tuning và huấn luyện model.
- Giao diện web hoàn chỉnh; có thể dùng FastAPI OpenAPI và script test ban đầu.

---

## 4. API contract v1 (đề xuất)

| Method + path | Ý nghĩa | Ghi chú |
|---|---|---|
| `GET /v1/models` | Danh sách model, hỗ trợ ngôn ngữ, trạng thái cấu hình | Không đánh thức GPU |
| `POST /v1/jobs/translations` | Submit dịch bằng một model | Trả `202 Accepted`, `job_id` |
| `POST /v1/jobs/benchmarks` | Submit dịch song song 4 model hoặc subset | Trả `202 Accepted`, `job_id` |
| `GET /v1/jobs/{job_id}` | Trạng thái job + partial results + lỗi | Chỉ đọc PostgreSQL, không đánh thức GPU |
| `GET /health` | Kiểm tra gateway | Không khởi động model |
| `POST /v1/translate` | Sync API (tùy chọn) | Chỉ bật sau khi nghiệm thu timeout |
| `POST /v1/jobs/{job_id}/cancel` | Hủy theo best-effort (giai đoạn sau) | Không cam kết hủy tức thì job GPU đang chạy |

**Ví dụ input**

```json
{
  "model": "hy_mt2_30b",
  "source_language": "en",
  "target_language": "vi",
  "text": "The quick brown fox jumps over the lazy dog.",
  "options": {"preserve_formatting": true}
}
```

**Ví dụ response khi submit**

```json
{
  "job_id": "<uuid>",
  "status": "queued",
  "kind": "translation",
  "status_url": "/v1/jobs/<uuid>"
}
```

**Quy tắc request:**

- `Idempotency-Key` từ client (header), kết hợp user/tenant + payload hash để chặn submit trùng do retry.
- Authentication **Bearer token** qua Modal Secrets; khóa không bao giờ commit vào git hoặc ghi nguyên văn trong logs.
- Giới hạn input, output budget, số job đang chạy và timeout để tránh runaway GPU cost.
- Trả lỗi 4xx cho model/language/options sai, 429 khi vượt quota, 5xx có `error_code` rõ ràng.
- OpenAPI schema, contract tests, ví dụ curl và client tối thiểu.

---

## 5. Database PostgreSQL

### 5.1. Các bảng đề xuất

| Bảng | Trường quan trọng (rút gọn) | Mục đích |
|---|---|---|
| `model_registry` | `model_key`, `hf_repo`, `revision`, `quant`, `sha256`, `enabled`, `prompt_version` | Cố định provenance |
| `jobs` | `id`, `kind`, `request_hash`, `idempotency_key`, `source_lang`, `target_lang`, `input_text`, `status`, `created_at`, `finished_at` | Job chính, source of truth |
| `job_runs` | `id`, `job_id`, `model_key`, `attempt_no`, `modal_call_id`, `status`, `started_at`, `finished_at`, `error_code` | Mỗi model/run và retry |
| `translation_results` | `run_id`, `translation_text`, `input_tokens`, `output_tokens`, `timing_json`, `metadata_json` | Dữ liệu kết quả |
| `benchmark_reviews` | `job_id`, `run_id`, `rubric_scores`, `error_tags`, `reviewer`, `notes` | Đánh giá chất lượng |

**Các chỉ mục và ràng buộc bắt buộc:**

- Unique `(request owner, idempotency_key)` nếu có auth/owner; không coi cùng input là luôn cùng job nếu cấu hình/model khác.
- Unique `(job_id, model_key, attempt_no)`; foreign keys và check constraints cho status hợp lệ.
- Index `(status, created_at)`, `(job_id)`, `(model_key, created_at)` cho tìm job mắc kẹt và thống kê.
- Có migration versioned; test migration trên môi trường thử nghiệm trước production.

### 5.2. Kết nối và dữ liệu

- Dùng **Neon pooled connection URL** cho truy vấn ngắn từ gateway/Function; **direct connection URL** khi migration hoặc thao tác cần kết nối phiên ổn định.
- Engine/pool nhỏ; không giữ transaction mở xuyên suốt inference GPU.
- Xử lý Neon auto-suspend/reconnect, connection reset và transient DB errors có backoff.
- Trong v1, lưu text trong Postgres với **retention có cấu hình** (ví dụ 30 ngày) và tùy chọn không lưu text nhạy cảm; không đưa văn bản nguồn/bản dịch vào application logs.
- Không lưu model weights, bản sao dataset lớn hoặc file đầu vào dung lượng lớn trong Postgres.

### 5.3. Trạng thái và khôi phục

```text
queued -> dispatching -> running -> completed
   |           |           |
   +-------> failed <------+
   |                       |
   +-----> cancelled*      +-> retrying -> running
```

`cancelled*` là best-effort; chỉ bật API khi đã xác minh cơ chế hủy thực tế.

**Bài toán race/duplicate quan trọng:**

1. API tạo job `queued` trong DB, commit xong **mới** gọi Modal `.spawn()`.
2. Sau `.spawn()`, ghi `modal_call_id` và chuyển `dispatching`/`running` bằng cập nhật có điều kiện.
3. Nếu API crash giữa commit và spawn hoặc giữa spawn và cập nhật call ID, trạng thái có thể không đồng bộ. Không giả định exactly-once.
4. Mỗi GPU run có UUID/attempt riêng; cập nhật status bằng **compare-and-set/row-level lock** và kết quả idempotent.
5. Có **reconciliation** các job `queued`/`dispatching`/`running` vượt ngưỡng: ưu tiên chạy lazy khi có request mới; thêm **Modal scheduled CPU job tần suất thấp** chỉ nếu cần tự phục hồi khi không có traffic.
6. Retry có giới hạn, phân loại lỗi: thiếu GPU/quota, OOM, model load, HTTP/DB transient, timeout, invalid input. Không retry vô hạn.
7. `FunctionCall` của Modal không thay thế DB lưu lịch sử dài hạn; kết quả cuối ghi vào Neon.

---

## 6. GPU inference, cold start và chi phí

### 6.1. Cấu hình khởi điểm (cần benchmark)

```python
# Pseudocode / cấu hình định hướng — chưa phải mã hoàn chỉnh
GPU_SETTINGS = {
    "gpu": "L40S",
    "min_containers": 0,
    "buffer_containers": 0,
    "max_containers": 1,
    "scaledown_window": 60,
    "timeout": 1800,
}
```

- Ưu tiên **1 request đồng thời / GPU** ở vòng đầu; tăng sau khi đo KV cache và VRAM peak.
- **Context phục vụ thử nghiệm:** 4.096 tokens, dự phòng tăng 8.192 nếu ngôn ngữ/format yêu cầu; **max output** khởi điểm 2.048 tokens. Không nhầm “1.000 ký tự” với “1.000 tokens”.
- Model-specific prompt/decoding: dùng đúng chat template và khuyến cáo từng nhà phát hành. `temperature=0` không phải luôn là lựa chọn phù hợp cho mọi model (ví dụ Hy-MT2 có khuyến nghị riêng).
- Đóng băng binary llama.cpp/CUDA dependencies theo commit/image tag; không build lại trong mỗi cold start.
- Model weights nằm trên **Modal Volume** (ưu tiên volume riêng mỗi model), download **một lần**, xác minh SHA256 và mount readonly khi inference; không tải lại 30–40GB từ HF sau mỗi request.
- Ghi separate metrics: `container_start_ms`, `model_load_ms`, `queue_wait_ms`, `inference_ms`, `end_to_end_ms`, `tokens_per_second`, `peak_vram_mb`.
- Cân nhắc memory snapshot sau khi đạt correctness; chỉ giữ nếu giảm cold start và không gây lỗi engine.

### 6.2. Quy tắc giới hạn chi phí

- **Không keep-alive/ping GPU**, không `min_containers>0` trong v1.
- Quota mặc định 1 GPU container cho mỗi model, tối đa 4 GPU khi chạy benchmark đầy đủ.
- Có daily/monthly cost guard ở tầng API và cảnh báo dashboard Modal; test khi thiếu quota hoặc GPU chưa sẵn có.
- Tính chi phí bằng **tổng giây GPU được cấp**, gồm warm-up, loading, inference và idle trước khi scale-down (cộng CPU/RAM/volume/network/Neon nếu phát sinh).
- Giá L40S Modal tham chiếu **$0.000542 / GPU-second** tại ngày soạn tài liệu (giá có thể thay đổi):
  - **1 model × 5 phút GPU:** ~**$0.163 GPU**.
  - **4 model × 5 phút GPU/model:** ~**$0.650 GPU**.
  - Các con số trên **không phải** chi phí cam kết mỗi request vì cold start và thời lượng xử lý chưa được đo.
- Mỗi model đều phải đo ít nhất một vòng **cold** và một vòng **warm**, sau đó tính `USD / 1.000 ký tự` dựa trên kết quả thực.

---

## 7. Benchmark chất lượng dịch thuật

### 7.1. Tập dữ liệu

- Tận dụng bộ benchmark dịch truyện/văn bản đã từng kiểm duyệt nếu vẫn có thể truy cập; ghi rõ dataset hash, phiên bản và phạm vi được phép sử dụng.
- Bổ sung test set **khoảng 1.000 ký tự/đầu vào** với nhiều thể loại: hội thoại, văn học, mô tả kỹ thuật, email công việc, thành ngữ, tên riêng và ngôn ngữ hỗn hợp.
- Các cặp ngôn ngữ chính: **EN↔VI, DE↔VI, JA↔VI, KO↔VI**; không tự giả định tất cả model hỗ trợ chất lượng ngang nhau cho từng cặp.
- Chia **smoke**, **regression**, **human review**, **held-out benchmark**; không hiệu chỉnh prompt trên held-out test set.

### 7.2. Phương pháp đánh giá

1. Chạy **cùng inputs và cùng điều kiện đo**, seed/prompt/model-revision cố định, nhưng **không ép chung decoding** nếu không đúng hướng dẫn model; mọi khác biệt phải công khai.
2. Lưu text nguồn, text tham chiếu (nếu có), output và metadata; mã hóa/ẩn tên model khi làm **blind human review**.
3. Rubric đề xuất: **45% đúng nghĩa**, **25% văn cảnh/thành ngữ**, **20% tự nhiên**, **10% thuật ngữ/định dạng**.
4. Tag lỗi nghiêm trọng: sai chủ thể, phủ định, số lượng, thời gian, xưng hô, thành ngữ, bỏ sót, thêm ý và sai ngôn ngữ đích.
5. Nếu có công cụ phù hợp: đo COMET/XCOMET hoặc thước đo dịch thuật khác như **chỉ báo phụ**; không dùng một metric làm quyết định duy nhất.
6. Báo cáo **theo từng chiều ngôn ngữ**, có ví dụ tốt/xấu, confidence/uncertainty và so sánh cặp (paired comparison).
7. Thông tin inference (latency, cold start, chi phí) **báo cáo riêng**; không trộn trực tiếp vào điểm chất lượng trừ khi có tiêu chí ra quyết định rõ.

### 7.3. Quy tắc chọn model mặc định

- Một model chỉ được làm **default** nếu vượt ngưỡng kiểm duyệt chất lượng và không có lỗi nghiêm trọng lặp lại.
- Có thể chỉ định **default theo cặp ngôn ngữ**, thay vì một model thắng cho tất cả.
- Nếu các model tương đương về chất lượng, chọn model có **chi phí / latency thấp hơn**.
- Giữ bốn endpoint để benchmark tùy chọn; không buộc client phải khởi động đủ bốn GPU cho mỗi yêu cầu.

---

## 8. Các giai đoạn thực hiện (theo thứ tự ưu tiên)

### P0 — Nghiên cứu & chốt tài nguyên (bắt buộc trước khi deploy)

- [ ] Kiểm tra tài khoản Modal: quota L40S, region, hạn mức đồng thời, ngân sách khả dụng.
- [ ] Tạo ma trận 4 model: repo/revision, Q8 file, sha256, license, prompt, engine compatibility, VRAM dự kiến.
- [ ] Xác minh Neon free/paid limits hiện tại, cấu hình autosuspend, pooled/direct URLs.
- [ ] Chốt scope v1: chỉ text, giới hạn 1.000 ký tự, cặp ngôn ngữ, chính sách retention.

**Bàn giao:** `docs/model-matrix.md`, `docs/architecture.md`, ADR quyết định GPU/engine.
**Gate:** không deploy nếu còn model chưa xác minh checkpoint hoặc giấy phép.

### P1 — Repository & API skeleton

- [ ] Khởi tạo Python project quản lý dependencies/lockfile.
- [ ] Xây FastAPI routes, Pydantic request/response, API key auth, exception handling.
- [ ] Thiết kế shared interface `ModelAdapter`, model registry, prompt template riêng.
- [ ] Unit tests không cần GPU; lint/typecheck; CI chạy không cần secrets/GPU.
- [ ] Tạo tài liệu **README.md (EN)** và **README.vi.md (VI)** riêng biệt.

**Bàn giao:** code chạy local với fake adapters, OpenAPI và test pass.
**Gate:** không có GPU dependency trong CI thông thường.

### P2 — PostgreSQL & job orchestration

- [ ] Tạo Neon project/branch dev, lưu secrets trong Modal; không commit URL có password.
- [ ] Migrations, repositories, indexes, pool, structured logs và tracing IDs.
- [ ] Modal async Functions mock + `.spawn()`, polling, fan-out/fan-in, partial results.
- [ ] Idempotency, failed dispatch, retry, reconciliation, timeout và cancel best-effort.
- [ ] Test đồng thời submit trùng, crash ở các điểm nhạy cảm và DB reconnect sau auto-suspend.

**Bàn giao:** hệ thống job hoàn chỉnh **chưa cần chạy GPU**.
**Gate:** một lần submit/retry không sinh bản ghi kết quả trùng; có đường phục hồi khi job mắc kẹt.

### P3 — Hai model dịch thuật chuyên dụng

- [ ] Chuẩn bị Volume chứa Hy-MT2 Q8_0 và Index-Translate preview Q8_0.
- [ ] Dùng llama.cpp build tương thích; xác minh chat template/decoding.
- [ ] Deploy **mỗi model 1 GPU Function L40S** và kiểm tra input 1.000 ký tự.
- [ ] Đo cold/warm start, peak VRAM, output correctness, load time, thất bại do GPU quota.
- [ ] Kiểm tra scale về zero và gọi lại sau khi idle.

**Bàn giao:** 2 inference model end-to-end qua API + Neon.
**Gate:** Q8_0 chạy ổn định trong 48GB và trả bản dịch hợp lệ; nếu không thì ghi rõ phương án giảm context/quant.

### P4 — Gemma 4 31B IT và Qwen3.5 35B A3B

- [ ] **Gemma 4 `-it`**, không dùng base.
- [ ] Qwen3.5 **instruct**, không dùng Base; kiểm soát thinking/output.
- [ ] Tạo Volume và triển khai hai GPU Function độc lập; kiểm tra peak VRAM.
- [ ] Test cả bốn model một lúc, đo quota và tổng thời gian benchmark.

**Bàn giao:** đủ 4 model từ cùng repository và cùng contract.
**Gate:** cả bốn độc lập bật/tắt; lỗi một model không làm hỏng kết quả ba model còn lại.

### P5 — Benchmark, review và lựa chọn default

- [ ] Import tập benchmark cũ và thêm cases ~1.000 ký tự đa ngôn ngữ.
- [ ] Chạy lại cùng một benchmark suite cho 4 model, đóng băng config.
- [ ] Kết xuất CSV/JSON/Markdown summary, human review, bảng lỗi theo cặp ngôn ngữ.
- [ ] Chọn default theo chất lượng; fallback khi model lỗi/quota (nếu được bật rõ ràng).

**Bàn giao:** `reports/benchmark-YYYYMMDD.md`, raw run metadata và bảng so sánh.
**Gate:** không tuyên bố “tốt nhất” nếu chưa có dữ liệu đối chứng đáng tin.

### P6 — Production hardening và nghiệm thu cuối

- [ ] Security: auth, input limits, rate limits, secret rotation, no raw text in logs.
- [ ] Reliability: retry có giới hạn, reconciliation, database reconnect, observability.
- [ ] Cost: scale-to-zero, container caps, cost alerts, budget test, benchmark dollars/run.
- [ ] Docs EN/VI: hướng dẫn deploy, cấu hình Neon, Modal Secrets, API examples, limitations.
- [ ] CI: unit + integration mock, smoke optional qua cờ/secret (không tự bật GPU trên mọi PR).
- [ ] Release notes, version pin, hash, rollback guide.

**Bàn giao:** bản v1 có thể phục hồi, đo đạc được, và đủ thông tin vận hành.
**Gate:** hoàn thành checklist nghiệm thu ở mục 9.

---

## 9. Checklist nghiệm thu cuối (Definition of Done)

### Chức năng

- [ ] `POST /v1/jobs/translations` tạo và thực hiện thành công ít nhất 1 job/model.
- [ ] `POST /v1/jobs/benchmarks` tạo 4 model runs; client nhận kết quả từng model, kể cả partial failure.
- [ ] `GET /v1/jobs/{id}` trả trạng thái/kết quả **không bật GPU**.
- [ ] Cặp ngôn ngữ EN/VI, DE/VI, JA/VI, KO/VI được kiểm thử cả hai chiều trong phạm vi hỗ trợ thực tế.
- [ ] Kiểm tra input ~1.000 ký tự, Unicode, dấu tiếng Việt, newline, placeholder, tên riêng.

### Reliability

- [ ] Thử cold start sau GPU scale-to-zero thành công.
- [ ] Worker đang chạy không bị tắt vì thiếu HTTP request mới.
- [ ] Retry request cùng idempotency key không tạo job trùng.
- [ ] Simulate API crash sau commit-trước-spawn và sau spawn-trước-lưu call ID.
- [ ] Job mắc kẹt được tìm và hòa giải trạng thái; DB reconnect khi Neon thức lại.
- [ ] Các model tách biệt, failure một model không làm mất kết quả model khác.

### Performance, chất lượng và chi phí

- [ ] Ghi peak VRAM cho tất cả model, **dưới 48GB** ở workload tiêu chuẩn.
- [ ] Có cold/warm start p50/p95 ở mức số mẫu đủ dùng và ghi rõ sample size.
- [ ] Có tokens/s, end-to-end latency, billable GPU seconds và ước tính USD/job.
- [ ] Có rubric chất lượng, human review, lỗi nghiêm trọng và quyết định chọn default.
- [ ] Sau idle, không còn GPU container nóng; không có keep-alive đánh thức GPU.

### Bảo mật, chứng cứ và tài liệu

- [ ] Không để lộ Neon URL/API key, raw prompts nhạy cảm trong logs/commits.
- [ ] Model source/revision/sha256/quant/license được ghi lại đầy đủ.
- [ ] **README.md EN** và **README.vi.md VI** tách biệt, API docs, deploy/rollback docs.
- [ ] Test CI pass; cấu hình workflow không tự tiêu GPU nếu chưa cho phép.

---

## 10. Cấu trúc repository dự kiến

```text
translation-ai-inference/
├── modal_app.py                  # 1 Modal App; CPU Gateway + 4 GPU workers
├── pyproject.toml
├── uv.lock                       # hoặc lockfile tương đương
├── config/
│   ├── models.yaml               # model pins, prompts, engine settings
│   └── settings.py
├── api/
│   ├── main.py
│   ├── auth.py
│   ├── routes/
│   │   ├── models.py
│   │   ├── translations.py
│   │   ├── benchmarks.py
│   │   └── jobs.py
│   └── schemas/
├── inference/
│   ├── adapters/
│   │   ├── base.py
│   │   ├── hy_mt2.py
│   │   ├── index_translate.py
│   │   ├── gemma4.py
│   │   └── qwen35.py
│   ├── runtime.py
│   └── prompt_templates/
├── jobs/
│   ├── dispatcher.py
│   ├── worker.py
│   └── reconciliation.py
├── db/
│   ├── models.py
│   ├── repositories.py
│   └── migrations/
├── benchmark/
│   ├── datasets/
│   ├── evaluate.py
│   ├── metrics.py
│   └── report.py
├── scripts/
│   ├── download_models.py
│   ├── verify_weights.py
│   └── smoke_test.py
├── tests/
├── docs/
│   ├── architecture.md
│   ├── model-matrix.md
│   ├── api.md
│   ├── deployment.md
│   ├── runbook.md
│   └── decisions/
├── reports/                      # chỉ đưa các báo cáo đã kiểm chứng
├── .github/workflows/
├── .env.example                  # placeholders; không có secret thật
├── README.md                     # English
└── README.vi.md                  # Tiếng Việt
```

---

## 11. Các rủi ro và quyết định cần duyệt

| Rủi ro | Ảnh hưởng | Cách xử lý |
|---|---|---|
| Q8_0 + KV cache vượt 48 GB | OOM, không deploy được | Giảm context/batch, thử Q6_K và đo lại chất lượng |
| llama.cpp chưa hỗ trợ đúng một kiến trúc/model | Output sai, crash | Pin bản build, smoke test, fallback engine riêng cho model đó |
| Cold start kéo dài | HTTP request timeout | Async job mặc định; UI polling; tối ưu Volume và binary |
| 4 L40S không đủ quota cùng thời điểm | Benchmark bị chờ/lỗi | Fan-out giới hạn, retry có backoff, hỗ trợ partial results |
| API crash ở khoảng DB commit / Modal spawn | Job mắc kẹt/duplicate | Idempotency, run ID, reconciliation và conditional updates |
| Neon auto-suspend | Kết nối đầu tiên chậm/đứt | Pool/reconnect, timeout đủ, retry transient DB errors |
| Kết quả Q8 không tự động tốt nhất | Phán đoán chất lượng sai | Blind review, baseline, rubric theo cặp ngôn ngữ |
| Tốn tiền vì container idle/cache | Chi phí vượt dự kiến | Scale-to-zero, Volume dung lượng vừa đủ, không keep-alive |
| Dữ liệu người dùng nhạy cảm | Rò rỉ qua logs/DB | Secrets, privacy/retention, hạn chế lưu raw text |

### Các quyết định đề xuất phê duyệt ngay

1. **MVP tập trung text translation 1.000 ký tự**, không làm OCR/ảnh/PDF.
2. **Async là API chính**; sync là tiện ích bổ sung, không phụ thuộc thời gian cold start.
3. **PostgreSQL** lưu jobs/results; **Modal `spawn()`** chạy tác vụ; **không Redis/Sidekiq/Celery** ở v1.
4. **4 GPU Function L40S độc lập** trong một Modal App; `min_containers=0`.
5. **Q8_0 là mục tiêu**, không là cam kết: từng model phải qua gate VRAM + correctness.
6. **Giữ Gemma 4 bản IT và Index bản preview** (đúng weights), ghi rõ provenance.
7. **Chọn default sau benchmark**, không cố định trước khi kiểm thử.

---

## 12. Tài liệu tham khảo đã kiểm tra (2026-11-06)

### Model cards và GGUF

- Hy-MT2: https://huggingface.co/tencent/Hy-MT2-30B-A3B
- Hy-MT2 GGUF Q8: https://huggingface.co/tencent/Hy-MT2-30B-A3B-GGUF
- Index-Translate **preview**: https://huggingface.co/IndexTeam/Index-Translate-35B-A3B-preview
- Index GGUF Q8: https://huggingface.co/IndexTeam/Index-Translate-35B-A3B-preview-GGUF
- Gemma 4 **31B IT**: https://huggingface.co/google/gemma-4-31B-it
- Gemma 4 31B IT GGUF: https://huggingface.co/unsloth/gemma-4-31B-it-GGUF
- Qwen3.5-35B-A3B (instruction): https://huggingface.co/Qwen/Qwen3.5-35B-A3B
- Qwen3.5 GGUF: https://huggingface.co/unsloth/Qwen3.5-35B-A3B-GGUF

### Hạ tầng

- Modal scaling: https://modal.com/docs/guide/scale
- Modal invoking Functions: https://modal.com/docs/guide/trigger-deployed-functions
- Modal SDK autoscaler settings: https://modal.com/docs/sdk/py/latest/Function
- Modal pricing: https://modal.com/pricing
- Neon scale-to-zero: https://neon.com/docs/introduction/scale-to-zero
- Neon connection pooling: https://neon.com/docs/connect/connection-pooling

---

## 13. Bước thực hiện đầu tiên sau khi duyệt kế hoạch

**Bắt đầu với P0, không tải 4 model cùng lúc và không deploy production ngay.** Trước tiên chốt ma trận model/provenance và kiểm tra quota/cost. Sau đó dựng code gateway + Neon với **mock jobs** (P1–P2). Chỉ khi nền tảng job/recovery đã đạt gate mới triển khai **Hy-MT2 Q8_0** trên **một L40S** để đo VRAM/cold start thực tế, rồi lần lượt bổ sung Index, Gemma 4 IT và Qwen3.5.

> **Tài liệu này là kế hoạch để duyệt, chưa phải nghiệm thu triển khai.** Những giả định về VRAM, latency, chất lượng và chi phí phải được thay bằng số đo thực khi bắt đầu P3–P5.
