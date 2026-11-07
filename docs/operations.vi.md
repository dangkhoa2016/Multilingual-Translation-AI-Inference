# Vận hành — giám sát, chi phí và đối soát

> 🌐 Language / Ngôn ngữ: [English](operations.md) | **Tiếng Việt**

Dự án tách biệt **quy tắc nhận job**, **hóa đơn Modal thực tế** và
**khôi phục trạng thái bền vững**. Con số ước tính tại API không thay
thế ngân sách/giới hạn do nhà cung cấp cloud áp dụng.

## Giám sát

Modal App có monitor **chỉ dùng CPU, chạy mỗi giờ**. Nó đọc tổng hợp
trạng thái PostgreSQL, các job chưa chắc chắn, job quá hạn và mã lỗi
gần đây. Monitor không gọi GPU, không retry; chỉ ghi log đã loại bỏ
thông tin nhạy cảm trong Modal Logs. **Chưa cấu hình gửi email/webhook.**

CLI cho người vận hành (mặc định chỉ đọc):

```bash
set -a; source .env; set +a
PYTHONPATH=src python scripts/check_production_safeguards.py \
  --profile YOUR_MODAL_PROFILE

# Ngưỡng cảnh báo do người vận hành lựa chọn; exit code 2 khi có cảnh báo:
PYTHONPATH=src python scripts/check_production_safeguards.py \
  --profile YOUR_MODAL_PROFILE \
  --alert-metered-usd 10 --alert-billed-usd 5
```

Các số 10 và 5 chỉ là **ví dụ minh họa**, không phải ngân sách production.

## Quota GPU theo USD ước tính

Nếu cấu hình **cả hai** biến sau, API dành trước một khoản USD cố
định *ước tính* cho mỗi model-run được chấp nhận:

```text
TRANSLATION_ESTIMATED_GPU_USD_PER_RUN
TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY
```

Quota và tạo job cùng nằm trong transaction PostgreSQL. Một
benchmark bốn model cần bốn khoản dự trù. Nếu vượt hạn mức ước tính,
API trả HTTP 429 và không tạo job. Request lặp idempotency không bị
tính lại; retry lỗi đã xác nhận cần một khoản dự trù mới.

**Quan trọng:** hệ thống không đo được trực tiếp số giây GPU, thời
gian chờ, CPU, RAM, storage và các điều chỉnh trên hóa đơn Modal từ
số model-run. Đây **không phải trần chi phí thật**. Cần tạo **Modal
Workspace Budget** riêng theo mức USD do người có quyền quyết định.
API hiện không có ngưỡng USD mặc định bị áp đặt âm thầm.

## Trạng thái chưa xác định và đối soát

Các trạng thái cần phân biệt:
- `failed`: lỗi đã được xác nhận; có thể retry thủ công với giới hạn.
- `dispatch_uncertain`: có thể đã gửi `spawn()` nhưng mất xác nhận.
- `execution_uncertain`: engine có thể hoàn tất dù caller không nhận phản hồi.
- `completed`: kết quả đã lưu bền vững trong PostgreSQL.

Không tự gửi lại trạng thái uncertain. Trước khi xử lý, kiểm tra log,
claim token, model và thời điểm chạy.

```bash
# Chỉ đọc PostgreSQL, không gọi billing:
PYTHONPATH=src python scripts/check_production_safeguards.py --skip-billing

# Đối soát có chủ đích: đổi trạng thái quá hạn, KHÔNG gọi GPU:
PYTHONPATH=src python scripts/check_production_safeguards.py \
  --skip-billing --apply-reconcile
```

Đổi trạng thái database không đồng nghĩa GPU task cũ đã dừng.
Nếu cần dọn dữ liệu cũ, xem kỹ
[`purge_retained_jobs.py`](../scripts/purge_retained_jobs.py).

## Bằng chứng và phần còn thiếu

- [Báo cáo trạng thái vận hành](../reports/operations_safety_snapshot.json)
- [Tích hợp PostgreSQL/GPU thật](../reports/postgresql_gpu_jobs.json)
- [Kiểm tra readiness GPU](../reports/deployed_gpu_readiness.json)

Vẫn cần diễn tập disaster recovery, cảnh báo ngoài Modal, billing
theo dự án và fault injection trên staging. Xem
[chính sách bảo mật](../.github/SECURITY.vi.md).
