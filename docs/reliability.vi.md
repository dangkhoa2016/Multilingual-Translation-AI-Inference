# Độ tin cậy và kiểm tra tích hợp

> 🌐 Language / Ngôn ngữ: [English](reliability.md) | **Tiếng Việt**

Dùng hướng dẫn này để hiểu cách API xử lý yêu cầu, xem kết quả tích hợp
đã ghi nhận và chạy các kiểm tra tương tự trên deployment của bạn.

## Hành vi API

- Văn bản tối đa 1.000 Unicode code points. Nhãn ngôn ngữ do người dùng chọn;
  [danh mục model](models.vi.md#hợp-đồng-đầu-vào) giải thích kiểm tra đầu vào và khả năng hỗ trợ.
- Gửi lại key idempotency còn lưu với cùng payload trả về cùng job;
  thay payload sẽ trả HTTP 409.
- GET có xác thực đọc kết quả được lưu bền vững. Xem attempt mới nhất của
  từng model; cần đối soát job chưa rõ kết quả trước một POST khác.
- Mỗi container model xử lý một luồng inference. Các request đồng thời
  có thể phải xếp hàng nếu cùng chọn một model.

Xem [tài liệu API](development.vi.md#api-contract) để biết schema response và trạng thái.

## Kết quả tích hợp đã ghi nhận

Các bản tổng hợp do dự án ghi nhận mô tả từng lượt chạy cụ thể. Dùng các
bước tái lập bên dưới để kiểm tra bản cài với mã nguồn và cấu hình hiện tại của bạn.

| Tình huống | Kết quả thực tế | Bằng chứng |
|---|---|---|
| Nạp bốn model đã triển khai | Cả bốn nạp thành công | [Báo cáo readiness](../reports/deployed_gpu_readiness.json) |
| HTTP job một model | Hoàn tất với đầu ra không mock | [Báo cáo dịch](../reports/gpu_api_translation.json) |
| HTTP job bốn model | 4/4 hoàn tất và được lưu | [Báo cáo benchmark](../reports/gpu_api_four_model_benchmark.json) |
| Đúng 1.000 Unicode code point trên bốn model | 4/4 hoàn thành, không mock | [Báo cáo](../reports/unicode_input_boundary.json) |
| 1.001 ký tự, ngôn ngữ sai hoặc nội dung rỗng | HTTP 422, không nhận job | [Báo cáo](../reports/unicode_input_boundary.json) |
| Cùng Idempotency-Key và payload | Tái sử dụng job, không trừ quota hai lần | [Báo cáo](../reports/unicode_input_boundary.json) |
| Cùng key nhưng khác payload | HTTP 409 | [Báo cáo](../reports/unicode_input_boundary.json) |
| Hai POST gần đồng thời tới Hy-MT2 | Hai job riêng và đều hoàn thành | [Báo cáo](../reports/concurrent_model_jobs.json) |
| Hai lần gọi readiness Hy-MT2 | Cùng GPU UUID, tái sử dụng worker | [Báo cáo](../reports/gpu_container_reuse.json) |
| Bốn model hoạt động độc lập | Bốn GPU UUID L40S khác nhau | [Báo cáo](../reports/four_gpu_parallel_inference.json) |

Bài thử 1.000 ký tự có Unicode ngoài ASCII và hơn 1.000 byte UTF-8;
giới hạn đếm theo **Unicode code point**, không theo byte.

Các lần từ chối mã ngôn ngữ trong báo cáo cũ thuộc hợp đồng năm mã
trước đây; phiên bản hiện tại nhận nhãn ngôn ngữ do người dùng chọn,
không có whitelist. Báo cáo lưu lại chính sách đã dùng trong lượt chạy đó.

Hai RPC readiness liên tiếp mất **25,104 giây** và **0,459 giây**.
Lần đầu không chắc là cold start; không dùng các số đó làm SLA.
Hai request HTTP gửi đồng thời tới **một model** không có nghĩa
inference cùng lúc trên một GPU vì class chỉ được một container.

## Nguồn gốc và giới hạn bằng chứng

Các file JSON là bản tổng hợp các lượt chạy trước của dự án, đã lược bỏ dữ
liệu riêng. Chúng mô tả hành vi hạ tầng, không đo chất lượng dịch hay xác
nhận dịch vụ hiện sẵn sàng. Phạm vi này không bao gồm log thực thi gốc đầy
đủ hoặc chứng nhận độc lập.

| Nhóm bằng chứng | Có thể kiểm tra | Chưa thể kết luận |
|---|---|---|
| [Cấp phát GPU](../reports/four_gpu_capacity.json) | Bốn GPU riêng và khoảng thời gian chạy Unix được ghi nhận | Model đã nạp hoặc chất lượng bản dịch |
| [GGUF/CUDA inference](../reports/four_gpu_parallel_inference.json) | Đầu ra bốn model, mẫu VRAM và khoảng thời gian thực thi Unix | Tính sẵn sàng của HTTP production hoặc độ chính xác ngữ nghĩa |
| [Readiness đã triển khai](../reports/deployed_gpu_readiness.json) | Trạng thái nạp model và VRAM quan sát được | Worker luôn khỏe hoặc luôn warm |
| [HTTP xác thực và lưu trữ](../reports/gpu_api_four_model_benchmark.json) | Hoàn thành job, đầu ra không mock; xem thêm [bằng chứng PostgreSQL](../reports/postgresql_gpu_jobs.json) | Thời điểm chạy có thể kiểm chứng độc lập hoặc điểm chất lượng dịch |
| [Giới hạn đầu vào và đồng thời](../reports/unicode_input_boundary.json) | HTTP từ chối, idempotency và job hoàn thành; xem [hai request đồng thời](../reports/concurrent_model_jobs.json) | Cam kết hiệu năng chung |
| [Snapshot vận hành](../reports/operations_safety_snapshot.json) | Bộ đếm trạng thái và cảnh báo đã lược bỏ dữ liệu riêng | Tổng chi phí billing hoặc lịch sử giám sát liên tục |

Một số báo cáo GPU giữ khoảng thời gian thực thi dạng Unix, nhưng nhiều
bản tổng hợp **không có thời điểm ghi nhận có thể kiểm chứng độc lập**.
Metadata của commit Git cho biết thời điểm báo cáo được đưa vào source
control, **không nhất thiết là lúc phép thử chạy**. Không thể khôi phục
ngày giờ còn thiếu chỉ từ các bản tổng hợp. Thời lượng thực thi là kết
quả quan sát từng lần, không phải cam
kết SLA. Các báo cáo này không tính BLEU, COMET hay điểm chất lượng dịch
do con người đánh giá.

## Kiểm thử tự động

Bộ test tự động trên CPU thường dùng SQLite cô lập để kiểm tra đầu vào,
xác thực API, idempotency, concurrency và trạng thái job; **không phải**
kiểm thử trực tiếp PostgreSQL production. Kiểm tra PostgreSQL và GPU
của bạn theo [hướng dẫn xác minh bản cài đặt](independent-validation.vi.md).

Kiểm thử an toàn xuất bản ngăn notebook lưu output, nhúng credentials,
bật truy cập thật theo mặc định hoặc công khai định danh riêng trong báo cáo.

## Chạy các kiểm tra

```bash
# Không sử dụng GPU:
python -m pytest -q
python -m ruff check .
PYTHONPATH=src python scripts/api/reliability_smoke.py

# Kiểm thử API thật có tính phí:
set -a; source .env; set +a
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_GATEWAY.modal.run"
PYTHONPATH=src python scripts/api/reliability_smoke.py --run-boundary
PYTHONPATH=src python scripts/api/reliability_smoke.py --run-concurrency
PYTHONPATH=src python scripts/api/container_reuse.py --run
```

Bản tổng hợp từ các lượt chạy mới được ghi vào **thư mục tạm riêng, duy nhất,
nằm ngoài repository** (quyền thư mục `0700`, file `0600`). Script in đường
dẫn đó và không ghi đè các JSON lịch sử được dẫn ở trên. Bản runtime không
lưu job ID hoặc GPU UUID thật; việc tái sử dụng container được ghi bằng kết
quả so sánh cùng GPU. Rà soát và làm sạch một bản sao trước khi chia sẻ
hoặc thêm vào Git.

Negative test hiện tại dùng **nhãn sai cấu trúc** như `123`, không có chữ cái.
Tên in được tùy ý như `xx` được hợp đồng đầu vào chấp nhận, nên không được
dùng làm trường hợp mong đợi HTTP 422. Đầu vào được chấp nhận vẫn không
chứng minh model hỗ trợ cặp ngôn ngữ đó hoặc dịch chính xác.

## Tài liệu liên quan

Xem [vận hành](operations.vi.md), [triển khai](deployment.vi.md)
và [thông tin model](models.vi.md).
