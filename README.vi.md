# Multilingual Translation AI Inference — Modal + PostgreSQL

**Trạng thái (07/11/2026): API Modal đã chạy dịch thật với bốn GPU worker L40S độc lập, background job và PostgreSQL. Cả bốn model GGUF Q8_0 đã được nghiệm thu qua API. Chưa có chứng nhận chất lượng dịch độc lập hoặc đầy đủ giới hạn chi phí/bảo mật production.**

Mục tiêu: một Modal App, gateway FastAPI CPU, bốn worker L40S độc lập,
PostgreSQL lưu trạng thái và kết quả job (Neon là một lựa chọn nhà cung cấp).
API bất đồng bộ, đầu vào tối đa 1.000 ký tự Unicode. Phần CPU mock vẫn có
để kiểm thử hoặc rollback, **không phải model dịch**; API đã triển khai hiện dùng GPU thật.

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

**Cả bốn Volume đã được tạo, tải đầy đủ GGUF Q8_0 và xác minh SHA256
toàn file.** Các GPU class tương ứng đã đăng ký trong cùng Modal App:
`HyMT2L40SWorker`, `IndexTranslateL40SWorker`,
`Gemma4L40SWorker` và `Qwen35L40SWorker`. Mỗi GPU tự scale-to-zero.

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
Chế độ `modal-gpu` dùng Modal RPC nội bộ để chạy dịch thật trên GPU L40S và
lưu kết quả vào PostgreSQL.

## Kiểm tra và triển khai

```bash
python -m pytest -q
python scripts/local_demo.py
```

Hướng dẫn PostgreSQL, Modal Secrets, Volume, quy trình deploy và rollback:
[`docs/deployment.md`](docs/deployment.md).
`.venv/bin/modal deploy --profile YOUR_MODAL_PROFILE modal_app.py` đăng ký
CPU Gateway, CPU mock fallback và **bốn GPU class L40S** trong cùng App.
GPU không giữ chạy thường trực; `min_containers=0`.

Khi Secret đang dùng `TRANSLATION_DISPATCHER_MODE=modal-gpu`, hãy nạp `.env`,
đặt `TRANSLATION_GATEWAY_BASE_URL` bằng URL HTTPS của gateway đã deploy,
rồi chạy `scripts/smoke_modal_gpu_api.py --run` để nghiệm thu một model
hoặc thêm `--all-models` cho cả bốn. Đây là **các lệnh có tính phí GPU**.
Kịch bản `smoke_modal_cpu.py` chỉ dùng khi đã chuyển về chế độ mock.

**Đã nghiệm thu:** PostgreSQL schema, API Gateway đã xác thực,
API POST → Modal GPU worker → PostgreSQL → API GET;
cả bốn model trả kết quả thật với `is_mock_result=false`.

**Bảo vệ vận hành P2:** đã có quota giao dịch trên PostgreSQL (idempotent
replay không bị trừ thêm quota, kể cả khi nhiều request đồng thời), retry thủ công
chỉ với lần chạy thất bại rõ ràng, đối soát job quá hạn theo nguyên tắc không
tự chạy lại, và công cụ xóa job cũ có chế độ xem trước.
API retry qua HTTP trên Modal CPU đã được nghiệm thu thực tế (HTTP 202,
409 cho attempt trùng, job hoàn tất và giữ nguyên lịch sử). Hướng dẫn:
[`docs/p2-operational-safety.md`](docs/p2-operational-safety.md).

**Chưa hoàn tất:** đối soát tự động, cảnh báo/hạn mức chi phí USD,
đánh giá chất lượng bằng bản dịch tham chiếu và người kiểm duyệt,
kiểm thử tải cao, ngưỡng 1.000 ký tự đầy đủ và bảo mật nâng cao.
API GPU đã hoạt động nhưng chỉ nên sử dụng có kiểm soát cho đến khi
các yêu cầu chất lượng và vận hành được nghiệm thu.


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
  chưa hoàn tất benchmark tham chiếu và chứng nhận chất lượng dịch.
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
kiểm duyệt, chưa thử nhiều seed. Ở thời điểm P3 API chỉ chạy CPU mock;
P5 sau đó đã triển khai dịch GPU thật.

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
- Modal App nghiệm thu P4 là **tạm thời và đã dừng**. Sang P5, bốn
  GPU class đã được deploy vào App chính thức và API dịch thật đã đạt smoke;
  vẫn cần kiểm thử ngưỡng tối đa, độ ổn định và chất lượng.

Chứng cứ: [Tài liệu P4](docs/p4-four-independent-l40s-workers.md)
 · [Bản dịch và GPU runtime đồng thời](reports/p4_four_l40s_models_runtime_smoke_v1.json)
 · [Manifest bốn model và Volume](models/four_l40s_workers_q8_0_manifest.json).


## P5 — API dịch thật với bốn GPU L40S và PostgreSQL (07/11/2026)

**Cả bốn model GGUF Q8_0 hiện được phục vụ qua một FastAPI Gateway CPU
có Bearer authentication.** Endpoint `POST /v1/jobs/benchmarks` đã hoàn thành
bốn lần inference thật với `is_mock_result=false`, lưu kết quả vào
PostgreSQL và đọc lại thành công qua API GET được xác thực.

- Bốn GPU class có cơ chế load model một lần cho mỗi container đang hoạt động,
  mỗi class dùng `min_containers=0`, `buffer_containers=0`,
  `max_containers=1`; không phải trả tiền GPU khi instance đã scale-to-zero.
- Bài kiểm thử 849 ký tự qua PostgreSQL → Modal GPU → API GET đạt 4/4,
  mất khoảng **68 giây**.
- Gọi benchmark bốn model trực tiếp qua API đạt 4/4 trong khoảng **54,5 giây**;
  bài POST một model và kiểm tra idempotency cũng đạt.
- Có thể rollback có kiểm soát về CPU mock bằng cách đổi Modal Secret;
  không đưa token hoặc database URL vào Git.
- **Chưa thể suy ra bản dịch luôn chính xác:** vẫn cần benchmark có bản dịch
  tham chiếu đa ngôn ngữ, kiểm duyệt ngữ nghĩa và giới hạn chi phí/bảo mật tốt hơn.

Xem [hướng dẫn vận hành GPU và toàn bộ kết quả](docs/real-gpu-deployment.md),
[báo cáo bốn class đã deploy](reports/p5_deployed_four_gpu_classes_readiness_v1.json)
và [kết quả bốn model qua API thật](reports/p5_real_gpu_api_four_model_smoke_v1.json).
