# Độ tin cậy — giới hạn API đã kiểm thử và rủi ro còn lại

> 🌐 Language / Ngôn ngữ: [English](reliability.md) | **Tiếng Việt**

Các kết quả sau chỉ chứng minh **những trường hợp cụ thể trên GPU thật**,
không phải SLA, stress test đầy đủ hoặc chứng nhận chất lượng bản dịch.

## Kiểm thử HTTP thật

| Tình huống | Kết quả thực tế | Bằng chứng |
|---|---|---|
| Đúng 1.000 Unicode code point trên bốn model | 4/4 hoàn thành, không mock | [Báo cáo](../reports/unicode_input_boundary.json) |
| 1.001 ký tự, ngôn ngữ sai hoặc nội dung rỗng | HTTP 422, không nhận job | [Báo cáo](../reports/unicode_input_boundary.json) |
| Cùng Idempotency-Key và payload | Tái sử dụng job, không trừ quota hai lần | [Báo cáo](../reports/unicode_input_boundary.json) |
| Cùng key nhưng khác payload | HTTP 409 | [Báo cáo](../reports/unicode_input_boundary.json) |
| Hai POST gần đồng thời tới Hy-MT2 | Hai job riêng và đều hoàn thành | [Báo cáo](../reports/concurrent_model_jobs.json) |
| Hai lần gọi readiness Hy-MT2 | Cùng GPU UUID, tái sử dụng worker | [Báo cáo](../reports/gpu_container_reuse.json) |
| Bốn model hoạt động độc lập | Bốn GPU UUID L40S khác nhau | [Báo cáo](../reports/four_gpu_parallel_inference.json) |

Bài thử 1.000 ký tự có Unicode ngoài ASCII và hơn 1.000 byte UTF-8;
giới hạn đếm theo **Unicode code point**, không theo byte.

Hai RPC readiness liên tiếp mất **25,104 giây** và **0,459 giây**.
Lần đầu không chắc là cold start; không dùng các số đó làm SLA.
Hai request HTTP gửi đồng thời tới **một model** không có nghĩa
inference cùng lúc trên một GPU vì class chỉ được một container.

## Xử lý lỗi

Unit tests trên CPU mô phỏng:
- socket timeout, mất kết nối;
- JSON completion lỗi, output bị cắt hoặc chỉ có reasoning;
- nhiều request cùng Idempotency-Key và tranh chấp quota;
- phân biệt lỗi đã xác nhận với dispatch/execution chưa chắc chắn;
- retry giới hạn, giữ kết quả thành công, đối soát trạng thái.

Hệ thống **không tự retry** execution uncertain. Việc đổi trạng thái
database không chứng minh engine trên GPU đã bị hủy.

## Cách tái lập an toàn

```bash
# Không sử dụng GPU:
python -m pytest -q
python -m ruff check .
PYTHONPATH=src python scripts/api_reliability_smoke.py

# Kiểm thử API thật có tính phí:
set -a; source .env; set +a
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_GATEWAY.modal.run"
PYTHONPATH=src python scripts/api_reliability_smoke.py --run-boundary
PYTHONPATH=src python scripts/api_reliability_smoke.py --run-concurrency
PYTHONPATH=src python scripts/gpu_container_reuse.py --run
```

## Phần còn thiếu

Cần thêm burst/soak test dài hạn, fault injection trong **staging riêng**,
gửi cảnh báo ra ngoài, giới hạn ngân sách thực tế ở nhà cung cấp và
đánh giá chất lượng dịch có người kiểm duyệt. Xem
[vận hành](operations.vi.md) và [benchmark](benchmarking.vi.md).
