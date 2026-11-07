# Trạng thái thực hiện — 2026-11-06

| Mục | Hiện trạng | Bằng chứng |
|---|---|---|
| P0 nguồn model | Đã kiểm tra metadata tài liệu, chưa pin revision/SHA | `docs/model-matrix.md` |
| P1 Python package / FastAPI / model registry | Đã viết | `src/translation_ai_inference` |
| P1 auth / validation / OpenAPI | Đã viết, unit test offline | `api.py`, `schemas.py`, `tests` |
| P1 CI không GPU | Đã chạy GitHub-hosted thành công | `.github/workflows/python-validation.yml` |
| P2 ORM / migration | Đã chạy PostgreSQL development thật | `database.py`, `db/migrations` |
| P2 submit / idempotency / claim token | Đã nghiệm thu PostgreSQL và Modal CPU mock | `repository.py`, `dispatcher.py` |
| P2 Modal CPU `spawn()` | **Đã nghiệm thu trên Modal thật (CPU)** | `modal_app.py`, `dispatcher.py` |
| P2 automatic retry/reconciliation | **Chưa làm** | Đang để `dispatch_uncertain` |
| P3–P4 4 GPU workers / 4 Volumes | **Chưa tạo/đăng ký** | Chỉ có tên tường minh trong `resource_names.py` |
| P5 benchmark/human review | **Chưa làm** | Dataset cũ chưa import |
| P6 security, cost guard, privacy retention | **Chưa làm** | Không đưa production |

Quy tắc: không tự động tạo Volume, không tải GGUF, không deploy hoặc khởi động
GPU trong giai đoạn mã nguồn mock.

## Cập nhật 2026-11-07 — Đổi tên tài nguyên không phụ thuộc PostgreSQL provider

- Modal App: `translation-ai-inference-api-and-model-workers`.
- Modal Secret kết nối PostgreSQL: `translation-ai-inference-postgresql-connection`.
- Runtime env: `TRANSLATION_INFERENCE_DATABASE_URL`.
- Migration env: `TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL`.
- Bốn Modal Volumes của model giữ nguyên vì đã mô tả chính xác nội dung weights.
- Tài liệu và test được đồng bộ; chưa deploy hoặc đổi tên tài nguyên cloud.
- Xem ADR-0003 để biết quy trình chuyển nhà cung cấp PostgreSQL sau này.

## Cập nhật 2026-11-07 — Codespaces và repository chính thức

- Repository: `dangkhoa2016/Multilingual-Translation-AI-Inference`.
- Đồng bộ 40 file mã nguồn từ P1/P2 mock foundation vào Codespaces (gói chuyển kiểm tra SHA256 khớp).
- Python 3.13 trên Codespaces: **22/22 unit tests passed**, **Ruff passed** sau sửa 7 lỗi import chưa chuẩn.
- Alembic SQLite `upgrade head`/`downgrade base` và demo POST/GET mock đều pass.
- GitHub Actions được bổ sung bước Ruff; CI hosted sẽ được xác minh sau khi push.
- **Chưa** tạo PostgreSQL cloud, Modal Secret, Volume hay deploy CPU/GPU.
- Kết quả `is_mock_result=true` không phải bản dịch thật.

## Cập nhật 2026-11-07 — PostgreSQL development nghiệm thu thực tế

- Kết nối thành công PostgreSQL 18.6 qua pooled URL và direct URL (TLS) từ `.env` ở Codespaces.
- Alembic `upgrade head` hoàn tất, kiểm tra `0001_translation_jobs` và đủ ba bảng trên cả hai kết nối.
- `POST /v1/jobs/translations` → 202; `GET /v1/jobs/{id}` → 200, `completed`, `is_mock_result=true`.
- Benchmark bốn mock runs, idempotency không sinh duplicate, key trùng với input khác trả 409.
- Hỗ trợ URL provider `postgresql://` bằng psycopg v3, kèm unit tests.
- Không in/commit credentials; `.env` được ignore và đặt permission `0600` trong Codespaces.
- **24/24 tests + Ruff pass.** Chưa tạo Modal Secrets/deploy CPU vì chưa xác minh workspace đích.
- PostgreSQL development đã có dữ liệu kiểm thử mock, không chứa bản dịch thật.

## Cập nhật 2026-11-07 — Modal CPU deployment & live smoke

- Xác minh Modal workspace được chọn có đủ hai Secrets với tên tường minh và không chứa migration direct URL.
- Modal App `translation-ai-inference-api-and-model-workers` đã được deploy ở môi trường development.
- Bổ sung `app = modal_application` để Modal CLI tự nhận diện entrypoint; chạy CLI trong project `.venv`.
- Hai Functions có 1.0 CPU / 0.5 CPU, 512 MiB, GPU = none. **Không** tạo model Volumes.
- `/health` → 200; `/v1/models` thiếu Bearer → 401; đúng Bearer → 200 với 4 model metadata.
- Translation `POST` → 202, trạng thái `dispatching` → `completed` thông qua Modal CPU mock Function.
- Idempotent replay cùng key dùng cùng job; payload khác với key đã dùng trả HTTP 409.
- Benchmark chạy bốn mock runs qua Modal CPU, cả bốn `completed`, `is_mock_result=true`.
- Script nghiệm thu có thể chạy lại: `scripts/smoke_modal_cpu.py`.
- **25/25 tests + Ruff pass** trên Codespaces; không có model inference thực tế.
- Chưa hoàn thành reconciliation, cost/rate limits, retention, production security hoặc đánh giá chất lượng dịch.


## Cập nhật 2026-11-07 — P2 operational safety

- Migration `0002_p2_safety`: thời gian claim dispatch và bảng `usage_windows`.
- Quota atomically qua PostgreSQL: 10 jobs/phút, 100 jobs/ngày, 200 lượt model/ngày (giá trị mặc định).
- Retry API chỉ cho run **failed rõ ràng**, tối đa 2 attempts; unknown không tự retry.
- Reconcile trạng thái dispatching/running quá hạn thành *uncertain*, cho late worker kết thúc.
- Script `scripts/reconcile_stale_jobs.py` và `scripts/purge_retained_jobs.py` mặc định dry-run.
- Chưa có scheduler thường trực, bảo đảm không phát sinh background GPU job.
- Bài test SQLite toàn bộ: **36/36 passed** trước khi nghiệm thu PostgreSQL migration thực tế.
- Đây là giới hạn theo số lượng, chưa phải ngân sách USD hoặc chứng nhận production.

## Nghiệm thu bổ sung P2 — PostgreSQL + Modal CPU (2026-11-07)

- Migration PostgreSQL 18.6 từ `0001_translation_jobs` lên `0002_p2_safety` thành công.
- Direct và pooled connection cùng nhìn thấy bảng `usage_windows` và cột `dispatch_claimed_at`.
- Concurrent quota qua PostgreSQL thật: 5 submits với limit 2 → **2 accepted, 3 limited**, bộ đếm đúng 2; test owner được dọn.
- Explicit retry trên PostgreSQL: lần 2 được tạo, retry lặp lại bị HTTP 409, parent status `completed` sau khi lần 2 thành công; test owner được dọn.
- Hai scripts maintenance chạy dry-run trên PostgreSQL: stale dispatching = 0, stale running = 0, expired terminal jobs = 0.
- Modal CPU App được deploy lại trên `bsmith888`, không bật GPU/không tạo Volume.
- Live HTTP smoke: health/auth, `spawn()`, translation, benchmark bốn models, polling và idempotency đều pass.
- Unit tests trên Codespaces: **36/36 passed**, Ruff + compileall pass.
- HTTP end-to-end retry của một failed run trên Modal vẫn là bài nghiệm thu riêng; không khẳng định đã pass khi chưa có kết quả.
