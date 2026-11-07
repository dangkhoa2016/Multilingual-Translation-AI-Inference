# Multilingual Translation AI Inference — Modal + PostgreSQL

**Trạng thái: P1/P2 CPU mock đã triển khai; P3 đã xác minh Hy-MT2 Q8_0 trên L40S và chạy 16 ca dịch đa ngôn ngữ. Đã phát hiện lỗi trung thực ngữ nghĩa; chưa triển khai API GPU production.**

Mục tiêu: một Modal App, gateway FastAPI CPU, bốn worker L40S độc lập,
PostgreSQL lưu trạng thái và kết quả job (Neon chỉ là nhà cung cấp dự kiến ban đầu). API mặc định là bất đồng bộ,
đầu vào tối đa 1.000 ký tự Unicode. Phần mock **không phải model dịch**.

## Quy ước tên Modal tường minh

| Loại | Tên đầy đủ |
|---|---|
| Modal App | `translation-ai-inference-api-and-model-workers` |
| Gateway CPU | `translation_inference_fastapi_cpu_gateway` |
| Worker mock CPU | `translation_inference_cpu_mock_job_worker` |
| Secret API | `translation-ai-inference-api-authentication` |
| Secret kết nối PostgreSQL | `translation-ai-inference-postgresql-connection` |
| Volume Hy-MT2 | `translation-ai-inference-hy-mt2-30b-a3b-gguf-weights` |
| Volume Index-Translate | `translation-ai-inference-index-35b-a3b-preview-gguf-weights` |
| Volume Gemma 4 IT | `translation-ai-inference-gemma-4-31b-it-gguf-weights` |
| Volume Qwen3.5 | `translation-ai-inference-qwen-3-5-35b-a3b-gguf-weights` |

Tên App, Secret và biến môi trường không phụ thuộc Neon hay nhà cung cấp PostgreSQL khác.
Đổi nhà cung cấp chỉ cần cập nhật PostgreSQL URL/Secret, nếu schema tương thích.

Đã tạo và xác minh **một Volume Hy-MT2** chứa GGUF Q8_0. Ba Volume còn lại
chưa tạo. Script `scripts/create_named_modal_volumes.sh` chỉ dùng khi thực sự cần.
Chưa đăng ký GPU Functions vào App production để tránh cấp phát L40S ngoài ý muốn.

## Chạy local không tốn GPU

Yêu cầu Python 3.11+:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export TRANSLATION_INFERENCE_DATABASE_URL=sqlite+pysqlite:///./translation_inference_local.sqlite3
export TRANSLATION_API_BEARER_TOKEN=your-own-long-local-token
export TRANSLATION_DISPATCHER_MODE=inline-mock
alembic -c db/alembic.ini upgrade head
uvicorn translation_ai_inference.local:app --host 127.0.0.1 --port 8000
```

Nếu tạo `.env` trong Codespaces, cần nạp trước khi chạy Alembic/Uvicorn:
`set -a; source .env; set +a`. File `.env` đã được Git bỏ qua.
URL PostgreSQL dạng `postgresql://` được tự động dùng driver psycopg v3.

Windows PowerShell: sử dụng `.venv\Scripts\Activate.ps1` và `$env:KEY='value'`
thay cho các lệnh `source`/`export`.

Ví dụ gửi một job:

```bash
curl -X POST http://127.0.0.1:8000/v1/jobs/translations \
  -H "Authorization: Bearer $TRANSLATION_API_BEARER_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: translation-demo-001' \
  -d '{"model":"hy_mt2_30b","source_language":"en","target_language":"vi","text":"Hello, world!"}'
```

API trả `202`, `job_id`, `status_url`; gọi `GET /v1/jobs/{job_id}`
để xem kết quả. Kết quả mock luôn có `is_mock_result=true` và ghi
`MOCK ONLY — NOT A TRANSLATION`. Không dùng để đánh giá chất lượng dịch.

Các chế độ: `inline-mock` chạy mock ngay tại gateway để thử local;
`record-only` chỉ lưu job ở `queued`; `modal-cpu-mock` gọi `spawn()`
đến CPU mock worker (chỉ sau khi deploy và có PostgreSQL).

## Kiểm tra và triển khai

```bash
python -m pytest -q
python scripts/local_demo.py
```

Hướng dẫn cấu hình PostgreSQL và hai Modal Secrets: [`docs/deployment.md`](docs/deployment.md).
`.venv/bin/modal deploy --profile YOUR_MODAL_PROFILE modal_app.py ` **chỉ đăng ký CPU**, không tạo Volume hay gọi GPU.
Đã chạy thử nghiệm thu `spawn()` từ gateway đến CPU worker, PostgreSQL và polling.
Để nghiệm thu lại, nạp `.env` rồi chạy
`.venv/bin/python scripts/smoke_modal_cpu.py --base-url YOUR_HTTPS_MODAL_URL`.
Kịch bản kiểm tra Bearer token, idempotency, API polling và bốn mock runs.
Các thông số P3, chọn model và benchmark vẫn theo kế hoạch
[`docs/implementation-plan.vi.md`](docs/implementation-plan.vi.md).

**Đã nghiệm thu:** migrations PostgreSQL development, Modal CPU deploy,
API gateway → `spawn()` → CPU mock worker → PostgreSQL → polling.

**Bảo vệ vận hành P2:** đã có quota giao dịch trên PostgreSQL (idempotent
replay không bị trừ thêm quota, kể cả khi nhiều request đồng thời), retry thủ công
chỉ với lần chạy thất bại rõ ràng, đối soát job quá hạn theo nguyên tắc không
tự chạy lại, và công cụ xóa job cũ có chế độ xem trước.
API retry qua HTTP trên Modal CPU đã được nghiệm thu thực tế (HTTP 202,
409 cho attempt trùng, job hoàn tất và giữ nguyên lịch sử). Hướng dẫn:
[`docs/p2-operational-safety.md`](docs/p2-operational-safety.md).

**Chưa hoàn tất:** reconciliation tự động an toàn, cảnh báo chi phí theo USD,
budget/rate limits, đánh giá chất lượng có bản dịch tham chiếu và người kiểm duyệt,
3 model GPU còn lại, bảo mật nâng cao và retention. Không đưa API mock ra production dịch thuật.


## P3 — Hy-MT2 Q8_0: weights đã kiểm chứng và smoke L40S thành công

Đã cố định revision checkpoint, GGUF Q8_0 chính chủ và kiểm tra metadata.
**Toàn bộ GGUF 31.985.729.376 bytes đã tải một lần vào Modal Volume**, được
tính SHA256 trực tiếp trên file và xác minh khớp hash đã pin. Bài thử
cấp phát một L40S cũng thành công. Việc load model và dịch thật trên GPU
là các bước nghiệm thu riêng, không đồng nghĩa với việc SHA256 đã khớp.

- [Tài liệu preflight Hy-MT2](docs/p3-hy-mt2-readiness.md)
- [Lock file](models/hy_mt2_30b_q8_0.lock.json)
- Kiểm lại: `python scripts/verify_hy_mt2_p3.py --online --deep-header`
- Đã build CUDA từ commit llama.cpp cố định, load toàn bộ GGUF và dịch
  một câu EN→VI trên L40S **thành công**.
- Đã chạy 16 ca EN↔VI, DE↔VI, JA↔VI, KO↔VI trên L40S. Đoạn nguồn dài
  617–969 ký tự. Phát hiện lỗi đổi nghĩa chất liệu ở các bản dịch VI→ngôn ngữ khác;
  chưa hoàn tất benchmark tham chiếu và tiêu chí production.
- [Kết quả GPU smoke](docs/p3-hy-mt2-l40s-smoke.md) và
  [báo cáo JSON](reports/p3_hy_mt2_l40s_smoke.json).

## P3 — Benchmark kiểm thử đa ngôn ngữ Hy-MT2 (07/11/2026)

Đã chạy thử nghiệm riêng biệt trên **một NVIDIA L40S**: **16/16 yêu cầu** có
bản dịch, gồm EN↔VI, DE↔VI, JA↔VI và KO↔VI. Latency trung bình sau khi model
đã nạp là **0,653 giây** với văn bản có cấu trúc và **3,127 giây** với đoạn truyện.
VRAM cao nhất được lấy mẫu **31.189 MiB**; Modal RPC mất **52,271 giây**,
bao gồm thời gian chuẩn bị GPU.

**Lưu ý:** Tuy tất cả mã placeholder đều được giữ, kiểm tra ngữ nghĩa đã phát
hiện lỗi nghiêm trọng: *la bàn bạc* bị dịch thành la bàn bằng đồng hoặc đồng thau
ở cả bốn hướng VI→ngôn ngữ khác. Bộ fixture này là dữ liệu mô phỏng, chưa có
bản dịch tham chiếu và kiểm duyệt độc lập. **Chưa phê duyệt Hy-MT2 cho production**.

- [Thiết kế benchmark, kết quả đo và các giới hạn](docs/p3-hy-mt2-quality-diagnostic-review.md)
- [Toàn bộ bản dịch GPU](reports/p3_hy_mt2_quality_diagnostic_v1.json)
- [Đánh giá ngữ nghĩa sơ bộ](reports/p3_hy_mt2_quality_review_v1.json)
- Kiểm tra dữ liệu và script không tốn GPU:
  `modal run --profile YOUR_MODAL_PROFILE scripts/modal_hy_mt2_quality_benchmark.py`.
- Thêm `--run` mới cấp phát **L40S có tính phí**; CI không chạy GPU.

## P3 — Kiểm thử glossary thuật ngữ chất liệu (07/11/2026)

Đã chạy thêm một bài kiểm thử **có chủ đích** trên một L40S: 20 trường hợp,
mỗi trường hợp dùng prompt mặc định và prompt có glossary tiếng Việt,
tổng cộng **40/40 request thành công**. Glossary đã sửa lỗi
*la bàn bạc → đồng/đồng thau* ở cả bốn hướng dịch thử lại, và sửa lỗi
*hộp bằng đồng → đồng thau* trong bản dịch EN/DE. Một câu chỉ dẫn tiếng Đức
bị đảo ngược chiều thay thế vật liệu cũng được sửa trong phép thử.

**Không đánh đồng phép thử này với benchmark chất lượng độc lập**: bộ câu
được thiết kế nhằm kiểm tra lỗi đã biết, chưa có bản dịch tham chiếu của người
kiểm duyệt, chưa thử nhiều seed. API production vẫn chỉ chạy CPU mock.

- [Phương pháp, kết quả và giới hạn](docs/p3-hy-mt2-material-glossary-probe.md)
- [40 output dịch thật và thời gian xử lý](reports/p3_hy_mt2_material_glossary_probe_v1.json)
- [Đánh giá ngữ nghĩa sơ bộ](reports/p3_hy_mt2_material_glossary_review_v1.json)
- Chạy kiểm tra dữ liệu không cần GPU:
  `modal run --profile YOUR_MODAL_PROFILE scripts/modal_hy_mt2_material_glossary_probe.py`.
- Chỉ khi thêm `--run` mới cấp phát **L40S tính phí**.

## P4 — Bốn model trên bốn GPU Modal L40S độc lập (07/11/2026)

**Đã kiểm thử bằng GPU thực tế:** cả bốn model GGUF Q8_0
(Hy-MT2, Index-Translate, Gemma 4 IT, Qwen3.5) đều nạp thành công
và dịch được một câu **đồng thời trên bốn NVIDIA L40S khác nhau**.

- Mỗi model có **Modal Volume riêng**; toàn bộ file GGUF đều được tính
  SHA256 và khớp với revision đã khóa trước khi nạp GPU.
- **4 GPU UUID khác nhau**, mức đồng thời thực tế của bốn inference: **4/4**.
- VRAM quan sát của từng model: **31.151–35.336 MiB**, không phải peak chính xác.
- Mỗi worker dùng `min_containers=0`, `buffer_containers=0`,
  `max_containers=1`, có thể scale-to-zero độc lập.
- Modal App nghiệm thu là **tạm thời và đã dừng**. CPU FastAPI gateway
  hiện vẫn dùng **mock worker**; chưa tích hợp inference GPU vào API
  production, chưa nghiệm thu đầu vào dài và độ ổn định.

Chứng cứ: [Tài liệu P4](docs/p4-four-independent-l40s-workers.md)
 · [Bản dịch và GPU runtime đồng thời](reports/p4_four_l40s_models_runtime_smoke_v1.json)
 · [Manifest bốn model và Volume](models/four_l40s_workers_q8_0_manifest.json).
