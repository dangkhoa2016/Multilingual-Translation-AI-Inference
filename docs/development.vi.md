# Phát triển và review

> 🌐 Language / Ngôn ngữ: [English](development.md) | **Tiếng Việt**

Dự án viết bằng Python, FastAPI, SQLAlchemy, PostgreSQL và Modal.
Có thể kiểm thử API cũng như state machine của job **không cần GPU
hoặc tài khoản cloud**.

## Chạy local

```bash
git clone https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference.git
cd Multilingual-Translation-AI-Inference
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env

# Thay Bearer token ví dụ bằng token ngẫu nhiên chỉ dùng local.
set -a; source .env; set +a
python scripts/local_demo.py
```

Mẫu dùng SQLite và dịch giả lập. Kết quả mock có đánh dấu riêng,
không chứng minh GPU đã chạy inference.

## Kiểm thử

```bash
python -m pytest -q
python -m ruff check .
python -m compileall -q src modal_app.py scripts tests
python scripts/audit_public_repository.py
```

GitHub Actions chạy test CPU và audit tài liệu. Không đưa token,
database URL thật hoặc trọng số model vào fixture, log hay pull request.

## API contract

- `GET /health`: trạng thái process công khai, không kiểm tra GPU sâu.
- `GET /v1/models`: danh sách model có xác thực.
- `POST /v1/jobs/translations`: dịch một model, HTTP 202.
- `POST /v1/jobs/benchmarks`: benchmark 1–4 model, HTTP 202.
- `GET /v1/jobs/{job_id}`: polling có xác thực.
- `POST /v1/jobs/{job_id}/runs/{run_id}/retry`: chỉ retry
  lỗi đã xác nhận, theo quota.

Ví dụ request:

```json
{
  "model": "hy_mt2_30b",
  "source_language": "en",
  "target_language": "vi",
  "text": "The little fox crossed the bridge at sunrise.",
  "options": {"preserve_formatting": true}
}
```

Dùng `Authorization: Bearer YOUR_TOKEN`; nên có
`Idempotency-Key` để tránh tạo trùng. Văn bản phải có 1–1.000
Unicode code point không rỗng; ngôn ngữ nguồn khác đích và thuộc
`en`, `vi`, `de`, `ja`, `ko`.

## Đóng góp mã nguồn và tài liệu

Giữ logic inference đặc thù model trong runtime GPU. Bảo toàn
transaction PostgreSQL và claim token chống chạy trùng.
Tài liệu Markdown hướng tới người dùng phải có bản tiếng Anh/Việt
tương ứng và liên kết chuyển ngôn ngữ. Ưu tiên commit nhỏ, rõ mục
đích, có test phù hợp.

Xem [hướng dẫn đóng góp](../.github/CONTRIBUTING.vi.md),
[kiến trúc](architecture.vi.md) và [bảo mật](../.github/SECURITY.vi.md).
