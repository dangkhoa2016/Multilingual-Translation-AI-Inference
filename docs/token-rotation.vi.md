# Thay đổi API Bearer token an toàn

> 🌐 Language / Ngôn ngữ: [English](token-rotation.md) | **Tiếng Việt**

Dự án dùng **một Bearer token dùng chung** theo thiết kế single-tenant. Việc thay token không thêm người dùng, không cấp quyền theo tenant và không chuyển chế độ GPU. `GET /health`, `GET /v1/models` công khai; các endpoint tạo/đọc job vẫn yêu cầu Bearer token.

## Khi nào cần thay token?

Thay ngay nếu nghi ngờ thông tin xác thực bị lộ, định kỳ theo quy trình bảo mật nội bộ, hoặc khi bàn giao quyền vận hành. Việc cập nhật Secret **không** sửa token đã lưu trong ứng dụng Rails, notebook, dịch vụ tích hợp khác hoặc file `.env` cá nhân.

## Chuẩn bị và giới hạn vận hành

- Chỉ sử dụng profile và environment Modal **đã xác minh**. Không xóa Secret cũ, không gọi `modal secret create --force` và không triển khai lại GGUF/GPU chỉ để đổi token.
- Đảm bảo các job và request đang xử lý đã được đối soát; `--strategy recreate` có thể chấm dứt container đang hoạt động. Chọn khoảng bảo trì phù hợp.
- **Không thể rotate không gián đoạn hoàn toàn** với một token duy nhất: trong thời điểm chuyển đổi, client dùng token cũ có thể bị trả HTTP 401 cho đến khi được cập nhật.
- Cần `modal` SDK/CLI hỗ trợ `Secret.update()` (từ 1.3.5), Python `python-dotenv`, quyền update Secret và rollover App.
- Kiểm tra `TRANSLATION_DISPATCHER_MODE` riêng; script chỉ cập nhật `TRANSLATION_API_BEARER_TOKEN`, không bật GPU.
- Trường hợp có nhiều container, chiến lược `recreate` được sử dụng để ngừng container cũ trước khi xác nhận thu hồi token.

## Bước 1 — Chuẩn bị hai file riêng tư

File hiện có chứa token **đang hoạt động** (ví dụ `/secure/current-api.env`), với quyền `0600`. File mới chỉ chứa một khóa `TRANSLATION_API_BEARER_TOKEN`.

```bash
umask 077
export CURRENT_TOKEN_FILE="/secure/current-api.env"
export NEW_TOKEN_FILE="/secure/new-api.env"
chmod 600 "$CURRENT_TOKEN_FILE"
python - <<'PY'
from pathlib import Path
from secrets import token_urlsafe
import os

path = Path(os.environ['NEW_TOKEN_FILE'])
if path.exists():
    raise SystemExit('File token mới đã tồn tại; không ghi đè.')
with path.open('x') as stream:
    stream.write('TRANSLATION_API_BEARER_TOKEN=' + token_urlsafe(48) + '\n')
path.chmod(0o600)
print('Đã tạo file token mới, không hiển thị giá trị.')
PY
```

Không in hoặc gửi giá trị token; tuyệt đối không commit hai file này. Giữ token cũ trong kho riêng tư cho đến khi việc chuyển đổi được xác minh hoàn toàn.

## Bước 2 — Dry-run, không chạm Modal

```bash
cd /path/to/Multilingual-Translation-AI-Inference
export MODAL_PROFILE=YOUR_MODAL_PROFILE
export MODAL_ENVIRONMENT=YOUR_MODAL_ENVIRONMENT

PYTHONPATH=src python scripts/deployment/rotate_api_bearer_token.py \
  --profile "$MODAL_PROFILE" \
  --environment "$MODAL_ENVIRONMENT" \
  --current-token-env-file "$CURRENT_TOKEN_FILE" \
  --new-token-env-file "$NEW_TOKEN_FILE"
```

Dry-run kiểm tra cấu trúc và quyền file, độ dài/định dạng token, và bảo đảm hai token khác nhau. Không truy cập mạng, không thay đổi Modal Secret hay tạo container.

## Bước 3 — Cập nhật thật (chủ động, có thể gián đoạn)

Chỉ thực hiện sau khi đã thống nhất lịch bảo trì và xử lý xong job đang chạy.

```bash
export TRANSLATION_GATEWAY_BASE_URL='https://YOUR_GATEWAY.modal.run'

PYTHONPATH=src python scripts/deployment/rotate_api_bearer_token.py \
  --profile "$MODAL_PROFILE" \
  --environment "$MODAL_ENVIRONMENT" \
  --current-token-env-file "$CURRENT_TOKEN_FILE" \
  --new-token-env-file "$NEW_TOKEN_FILE" \
  --base-url "$TRANSLATION_GATEWAY_BASE_URL" \
  --apply --confirm-job-interruption
```

Helper thực hiện theo trình tự: GET `/health`, xác minh token cũ với GET `/v1/jobs/not-a-uuid` (HTTP 422 sau xác thực); cập nhật **duy nhất** khóa `TRANSLATION_API_BEARER_TOKEN` bằng `Secret.update()`; `modal app rollover --strategy recreate`; xác minh token mới nhận HTTP 422 và token cũ nhận HTTP 401. Lệnh xác minh **không gửi POST, không tạo job, không khởi chạy GPU**.

Với lỗi xác minh không phải do HTTP 429, helper **thử** khôi phục token cũ và rollover lại. Khi mạng/cloud xảy ra sự cố, rollback có thể không hoàn tất: kiểm tra Modal bằng tay trước khi tiếp tục, không lặp lại lệnh mù quáng.

**Mã thoát:** `0` chỉ khi xác nhận token mới được chấp nhận và token cũ đã bị từ chối. `2` nghĩa là HTTP 429 khiến xác minh chưa thể kết luận: giữ Secret mới (không tự rollback) và cần đối soát thủ công. `1` là lỗi khác, có thể đã thử rollback. Không coi mã `2` là thành công và không chạy lại lệnh một cách mù quáng.

## Bước 4 — Đồng bộ các client

Sau khi helper báo thành công, cập nhật bí mật phía server của ứng dụng Rails, script API, notebook và các tích hợp tin cậy. Không đặt token vào HTML/browser hoặc tài liệu công khai. Có thể dùng file mới làm bản token hiện hành trong kho bí mật sau khi đã xác minh và sao lưu an toàn. Thu hồi/tiêu hủy bản cũ theo chính sách nội bộ.

## Xử lý sự cố

- **401:** kiểm tra client đang dùng token mới và container đã rollover xong.
- **429:** tôn trọng `Retry-After`; tránh thử token sai lặp lại, vì gateway có chống dò Bearer.
- **422 với GET `/v1/jobs/not-a-uuid`:** token đã vượt qua authentication; UUID cố tình sai để xác minh an toàn, không phải lỗi của job thật.
- **Kết quả bất định:** xem lịch sử rollover, trạng thái Secret và log đã được lọc trên Modal; tuyệt đối không in credential. Đối soát job trước khi tiếp tục.

Tham khảo thêm [cấu hình](configuration.vi.md), [bảo mật](security.vi.md) và [triển khai](deployment.vi.md).
