# Vận hành — giám sát, chi phí và đối soát

> 🌐 Language / Ngôn ngữ: [English](operations.md) | **Tiếng Việt**

Dự án tách biệt **quy tắc nhận job**, **hóa đơn Modal thực tế** và
**khôi phục trạng thái bền vững**. Con số ước tính tại API không thay
thế ngân sách/giới hạn do nhà cung cấp cloud áp dụng.

## Giám sát

Modal App có **monitor chỉ dùng CPU**, nhưng **mặc định không bật lịch**
chạy tự động. Để kiểm tra mỗi giờ, đặt
`TRANSLATION_OPERATIONS_MONITOR_SCHEDULE=hourly` khi deploy; xem
[hướng dẫn triển khai](deployment.vi.md#deploy-một-modal-app). Khi không có
lịch, vẫn có thể chủ động chạy monitor bằng tay. Mỗi lần chạy chỉ đọc
trạng thái tổng hợp PostgreSQL, job chưa chắc chắn, job quá hạn và mã
lỗi gần đây; không gọi GPU hoặc tự retry.

**Cách nhận cảnh báo:** Monitor ghi trạng thái vào Modal Logs. Nếu phát
hiện vấn đề, nó ghi `alert` rồi đánh dấu lần chạy CPU là failed.
Người vận hành cần xem **Function Calls** và **Logs** trong Modal;
monitor **không tự gửi email/webhook hoặc thông báo bên ngoài**. Muốn
nhận thông báo tự động, phải tích hợp hệ thống cảnh báo riêng. Cảnh báo
không tự sửa hoặc retry job. CPU monitor chạy định kỳ và các truy vấn
PostgreSQL vẫn có thể phát sinh chi phí khi không có request dịch.

CLI cho người vận hành (mặc định chỉ đọc):

```bash
set -a; source .env; set +a
PYTHONPATH=src python scripts/operations/check_safeguards.py \
  --profile YOUR_MODAL_PROFILE

# Ngưỡng cảnh báo do người vận hành lựa chọn; exit code 2 khi có cảnh báo:
PYTHONPATH=src python scripts/operations/check_safeguards.py \
  --profile YOUR_MODAL_PROFILE \
  --alert-metered-usd 10 --alert-billed-usd 5
```

Các số 10 và 5 chỉ là **ví dụ minh họa**, không phải ngân sách production.

Snapshot có `pending_jobs_count` và `pending_runs_by_model`, gồm cả run
uncertain trên toàn database. `estimated_gpu_usd_reserved_today` tổng hợp
khoản dự trù **ngày UTC hiện tại** của các owner đã cấu hình; billing CLI là
số liệu **tháng hiện tại của Modal workspace**. Hai số khác phạm vi/thời gian,
không thể lấy hiệu để kết luận overrun hoặc đối soát từng job.

## Giới hạn công việc chưa hoàn tất

Mặc định tối đa **20 job/owner** và **20 run/model** đang ở `queued`,
`dispatching`, `running`, `dispatch_uncertain` hoặc `execution_uncertain`.
Run theo model được đếm chung mọi owner; job được đếm một lần dù có nhiều
model. PostgreSQL khóa các khóa owner/model ổn định trong transaction nhận
job; các replica phải dùng cùng cấu hình. Đây là trần công việc được nhận,
không phải số GPU đang chạy hoặc cam kết thời gian chờ.

Vượt trần trả HTTP 429, `Retry-After: 30`; không lưu job/run mới hay trừ quota,
ngân sách dự trù. Idempotent replay của job còn lưu vẫn được phép. Retry lỗi
đã xác nhận cũng chịu trần; retry một model không tốn thêm suất job nếu model
khác của cùng job còn hoạt động. Job uncertain vẫn giữ suất, không tự giải
phóng theo tuổi. Cần đối soát trước khi nhận thêm thay vì tự retry hoặc
chuyển trạng thái để né trần. Xem [cấu hình](configuration.vi.md).

## Quota GPU theo USD ước tính

Nếu cấu hình **cả hai** biến sau, API dành trước một khoản USD cố
định *ước tính* cho mỗi model-run được chấp nhận:

```text
TRANSLATION_ESTIMATED_GPU_USD_PER_RUN
TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY
```

Quota và tạo job cùng nằm trong transaction PostgreSQL. Một
request API dùng bốn model cần bốn khoản dự trù. Nếu vượt hạn mức ước tính,
API trả HTTP 429 và không tạo job. Request lặp idempotency không bị
tính lại; retry lỗi đã xác nhận cần một khoản dự trù mới.

**Quan trọng:** hệ thống không đo được trực tiếp số giây GPU, thời
gian chờ, CPU, RAM, storage và các điều chỉnh trên hóa đơn Modal từ
số model-run. Đây **không phải trần chi phí thật**. Cần tạo **Modal
Workspace Budget** riêng theo mức USD do người có quyền quyết định.
Các ngưỡng ước tính chỉ được áp dụng khi người vận hành chọn cấu hình.

## Phục hồi run còn queued — tùy chọn

Khi nhận job, gateway ghi PostgreSQL trước rồi mới dispatch. Nếu process
dừng giữa hai bước, một run có thể nằm lại ở `queued`. Coordinator
`translation_inference_cpu_queued_recovery` chỉ phục hồi các run chắc chắn
còn `queued`; **không** retry `dispatching`, `running`,
`dispatch_uncertain` hoặc `execution_uncertain`.

Job mới lưu `dispatch_mode` đã được chấp thuận (schema revision
`0006_queued_recovery_intent`). Job cũ có dispatch mode NULL sẽ không
được tự động phục hồi. Việc đổi dispatcher từ CPU mock sang GPU **không**
biến job mock cũ thành tác vụ GPU tính phí. Claim sử dụng PostgreSQL
parent lock và compare-and-set; các sweep đồng thời không thể claim
một run hai lần. Mỗi sweep lấy batch có giới hạn, xen kẽ theo model.

Mặc định **không có lịch tự chạy**. Chỉ khi operator chọn
`TRANSLATION_QUEUED_RECOVERY_SCHEDULE=hourly` lúc deploy, coordinator
mới chạy theo giờ; độc lập với monitor schedule. CPU và PostgreSQL
có thể tính phí. Ở `modal-cpu-mock`, chỉ phục hồi mock job. Ở
`modal-gpu`, recovery vẫn **bị chặn**, trừ khi operator chủ động
đặt thêm `TRANSLATION_QUEUED_RECOVERY_ALLOW_GPU=YES` vào API
authentication Secret sau khi duyệt ngân sách. Bước này có thể
**đánh thức GPU L40S** để thực hiện các job GPU đã được nhận trước đó,
nên không bật chỉ để kiểm tra health.

Cơ chế queued recovery khác với stale reconciliation: run đã claim có
thể đã khởi chạy ở Modal nhưng chưa nhận ACK, vì vậy chỉ operator
được đối soát các trạng thái chưa xác định; không retry tự động.

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
PYTHONPATH=src python scripts/operations/check_safeguards.py --skip-billing

# Đối soát có chủ đích: đổi trạng thái quá hạn, KHÔNG gọi GPU:
PYTHONPATH=src python scripts/operations/check_safeguards.py \
  --skip-billing --apply-reconcile
```

Đổi trạng thái database không đồng nghĩa GPU task cũ đã dừng.
Nếu cần dọn dữ liệu cũ, xem kỹ
[`purge_jobs.py`](../scripts/operations/purge_jobs.py).

### Lưu giữ job và thời hạn bảo vệ idempotency

`purge_old_terminal_jobs()` **chỉ được operator chủ động gọi**,
với thời hạn giữ mặc định **90 ngày** và chế độ xem trước trừ khi
chọn `apply=True`. Chỉ job `completed`, `failed` hoặc
`partial_failed` đã kết thúc và đủ cũ mới được xóa; job pending,
running hoặc uncertain không đủ điều kiện. Đủ 90 ngày **không có
nghĩa job tự động bị xóa**.

**Quan trọng:** idempotency key và request hash nằm trong bản ghi
job, không có sổ chống trùng riêng tồn tại vĩnh viễn. Purge job xóa
cả thông tin chống trùng; gửi lại cùng key/payload có thể tạo
**job GPU mới phát sinh phí**. Chống gửi trùng chỉ có hiệu lực khi
bản ghi job gốc còn trong database. Cần xác minh thời hạn lưu giữ
với operator trước khi gửi lại yêu cầu cũ; không tự gửi lại job
uncertain. Backup do operator quản lý riêng.

## Tài liệu vận hành

- [Ví dụ vận hành đã ẩn thông tin riêng](../reports/operations_safety_snapshot.json)
- [Tổng hợp tích hợp API](../reports/postgresql_gpu_jobs.json)
- [Tổng hợp GPU worker](../reports/deployed_gpu_readiness.json)

## Sao lưu và kiểm tra khôi phục PostgreSQL

**Việc khôi phục database do người vận hành quản lý; repository không
tự động sao lưu production.** Hãy bật backup hoặc point-in-time recovery
tại nhà cung cấp PostgreSQL, cấu hình thời gian lưu giữ, quyền truy cập
và định kỳ thử khôi phục. Tạo **bản sao riêng trước khi migration, đổi
nhà cung cấp hoặc thao tác có nguy cơ mất dữ liệu**. Nội dung bản dịch
có thể nhạy cảm: file backup phải được mã hóa/giới hạn quyền, lưu ngoài
Git và không đưa vào `reports/` công khai.

Nếu cần **logical backup** thủ công, dùng PostgreSQL client tương thích
với server. Kết nối tới **direct endpoint** bằng các biến môi trường
libpq và `PGPASSFILE` riêng tư; không gõ mật khẩu trong shell history:

```bash
# Ví dụ cho người vận hành: cấu hình riêng PGHOST, PGPORT, PGUSER,
# PGDATABASE, PGSSLMODE và PGPASSFILE trước khi chạy.
umask 077
mkdir -p "$HOME/translation-db-backups"
pg_dump --format=custom --no-owner \
  --file "$HOME/translation-db-backups/translation-backup.dump"
pg_restore --list "$HOME/translation-db-backups/translation-backup.dump" >/dev/null
```

Để **kiểm tra khôi phục**, tạo một PostgreSQL database *mới, rỗng,
có kiểm soát truy cập*, trỏ kết nối libpq đến database thử nghiệm rồi
chạy `pg_restore --no-owner --dbname YOUR_EMPTY_TEST_DB
/path/to/translation-backup.dump`. Kiểm tra Alembic revision,
số lượng bản ghi job/run và khả năng đọc dữ liệu của ứng dụng,
**không gọi GPU thật**. **Không restore đè database production hoặc
dùng `--clean` trên production.** Provider snapshot và logical dump
có đặc tính khôi phục khác nhau; tự xác định mục tiêu phục hồi và
ghi chép quy trình phù hợp.

Xem [chính sách bảo mật](../.github/SECURITY.vi.md)
và [triển khai](deployment.vi.md).
