# Bảo mật API gateway

> 🌐 Language / Ngôn ngữ: [English](security.md) | **Tiếng Việt**

CPU gateway kiểm tra Bearer token **trước khi đọc JSON** hoặc tạo job.
Các biện pháp áp dụng cho mọi đường dẫn `/v1/`. Endpoint `/health` không
yêu cầu xác thực và chỉ thể hiện trạng thái sống của gateway CPU, không
xác nhận GPU sẵn sàng. Swagger UI và OpenAPI schema công khai đã bị tắt.

## Giới hạn request trước xác thực

Mọi request `/v1/` chịu cửa sổ phút cố định theo đồng hồ monotonic của process:
mặc định **120 request/peer/phút** và **600 request/process/phút**. Khi hết
ngân sách, API trả 429 kèm `Retry-After` **trước khi so sánh token** hoặc đọc
body. Request có token đúng cũng chịu trần này. Xoay nhiều peer có thể đẩy
bộ đếm peer cũ khỏi RAM nhưng không xóa bộ đếm tổng của process.
Cửa sổ cố định có thể cho phép burst quanh ranh giới phút.

Hai biến `TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PEER` và
`TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PROCESS` điều chỉnh trần này.
Riêng `GET /v1/jobs/{job_id}` có quota theo owner dùng chung PostgreSQL,
mặc định **120/phút UTC**, qua `TRANSLATION_MAX_JOB_POLLS_PER_MINUTE`.
Request GET sai UUID bị validation từ chối trước khi trừ quota polling.
`/health` và catalog không truy vấn database hoặc GPU; catalog vẫn chịu
xác thực và trần request của process.

## Chống dò token qua các lần xác thực thất bại

Mặc định, **ba lần nhập Bearer token sai trong năm phút** từ cùng một định
danh mạng do ASGI xác nhận sẽ kích hoạt HTTP **429** và **khóa tạm 15 phút**
tại process gateway hiện tại. Các lần sai trước đó trả HTTP **401** với
`WWW-Authenticate: Bearer`. Khi bị khóa, API trả `Retry-After` tính bằng giây.
Trong ngân sách request còn lại, token đúng xóa bộ đếm lỗi, kể cả trong
thời gian phản hồi 429 cho token sai. Cơ chế này vẫn so sánh token cho các
request được trần trước xác thực cho phép; nó không dừng toàn bộ phép so sánh.

Có thể chỉnh ngưỡng qua Modal Secret xác thực của API:

| Biến | Mặc định | Mục đích |
|---|---:|---|
| `TRANSLATION_AUTH_FAILURE_LIMIT` | `3` | Số lần sai trước khi khóa cục bộ |
| `TRANSLATION_AUTH_FAILURE_WINDOW_SECONDS` | `300` | Cửa sổ trượt đếm lỗi |
| `TRANSLATION_AUTH_LOCKOUT_SECONDS` | `900` | Thời gian khóa tạm |
| `TRANSLATION_AUTH_MAX_TRACKED_CLIENTS` | `4096` | Số định danh lưu trong RAM mỗi process |
| `TRANSLATION_MAX_API_BODY_BYTES` | `65536` | Giới hạn body có xác thực |

Các giá trị phải là số nguyên dương trong giới hạn được kiểm tra. Bộ đếm
dùng RAM giới hạn, không truy vấn database hay cấp phát GPU. Hết hạn khóa
thì cửa sổ lỗi được đặt lại.

## Độ mạnh Bearer token

Gateway yêu cầu Bearer token dài **16–4096 ký tự ASCII in được**, không chứa
khoảng trắng hoặc ký tự điều khiển (kể cả tab, xuống dòng). Notebook dùng cùng
quy tắc này. Nên dùng token ngẫu nhiên từ trình quản lý
secret (ví dụ `secrets.token_urlsafe(32)`), không dùng mật khẩu dễ nhớ.
Với bản đã triển khai, kiểm tra riêng độ dài token trước khi nâng cấp và
đồng bộ việc đổi token giữa gateway cùng các API client.

## Định danh IP và giới hạn khi triển khai

Gateway lấy IP từ `scope["client"]` của ASGI, **không tin** giá trị
`X-Forwarded-For` hoặc `Forwarded` do client tự gửi. Nhà cung cấp hosting
hoặc reverse proxy đáng tin cậy phải xác định đúng IP nguồn. Nếu proxy chỉ
cung cấp một IP dùng chung cho nhiều người, bộ đếm của họ sẽ chung một nhóm;
token đúng vượt qua bộ đếm lỗi nhưng vẫn chịu trần request chung của peer.

**Quan trọng: đây là giới hạn theo process gateway, không phải khóa IP
toàn cục.** Modal có thể chạy nhiều container CPU; bộ đếm trong RAM không
đồng bộ giữa các replica và sẽ mất khi container khởi động lại. Lưu lượng
từ nhiều IP khác nhau cũng có thể đẩy bản ghi cũ ra khỏi bộ nhớ giới hạn.
Muốn chặn thống nhất trên nhiều replica cần WAF/rate limiter tại edge đáng
tin cậy hoặc kho dữ liệu chia sẻ có cập nhật nguyên tử, kèm cấu hình proxy/IP
được kiểm tra. Cơ chế hiện tại không thay thế bảo vệ DDoS quy mô lớn.

## Bảo vệ request và response

- Token được kiểm tra trước khi đọc body quá lớn hoặc JSON sai cấu trúc.
- Body trên `/v1/` lớn hơn ngưỡng trả HTTP **413**, cả khi không có
  `Content-Length`.
- Response `/v1/` có xác thực sử dụng `Cache-Control: no-store` và
  `X-Content-Type-Options: nosniff`; không in token trong lỗi.
- Quota tạo job, idempotency và ngân sách GPU ước tính vẫn là các lớp bảo
  vệ riêng cho yêu cầu đã xác thực và tránh chạy inference trả phí ngoài ý muốn.
- API mặc định **single-tenant**. Một Bearer token dùng chung không phân quyền
  riêng từng khách hàng; cần thay token nếu nghi bị lộ.

`GET /v1/models` chỉ đọc catalog. Trường `dispatch_enabled` phản ánh chế
độ điều phối; `runtime_verified` là kết quả xác minh lịch sử; trường
`runtime_status="not_checked"` nói rõ chưa kiểm tra GPU trực tiếp.
Trường `enabled` cũ vẫn tồn tại để tương thích, nhưng không bảo đảm GPU
sẵn sàng ở thời điểm GET. `GET /health` và `GET /v1/models` không bật GPU.

## Metadata truy cập tùy chọn

Đặt `TRANSLATION_AUDIT_LOG_ENABLED=true` để ghi JSON ra stdout gồm method đã
chuẩn hóa, route mẫu, HTTP status, xác thực thành công hay chưa và thời gian.
Không ghi token, body, bản dịch, query, UUID, IP hoặc owner. Route lạ dùng
`/v1/unmatched`; lỗi handler chưa xử lý trả 500 với thông báo chung.
Mặc định logging tắt. Khi bật, số sự kiện không vượt trần request/phút của
process; sự kiện vượt ngưỡng bị bỏ. Đây là metadata vận hành best-effort,
không phải nhật ký kiểm toán đầy đủ. Người vận hành quản lý thời gian lưu và
quyền truy cập log; log reverse proxy/hosting cần chính sách riêng.

## Kiểm thử và ứng phó

Chạy kiểm thử ngoại tuyến, không cấp phát GPU:

```bash
python -m pytest -q tests/api/test_auth_guard.py
python -m pytest -q
python -m ruff check .
```

`401` là token thiếu/sai; `429` với nội dung
`Too many failed authentication attempts` là khóa do xác thực; `429` vì
quota tạo job có thông báo khác. Tôn trọng `Retry-After`. Không tự động
POST lại job trả phí khi chưa rõ kết quả: giữ idempotency key và đối soát.

Cập nhật Modal Secret có thể cần rollover ứng dụng có kiểm soát. Không in
credential, body request hoặc UUID job thật trong log công khai.
Xem [cấu hình](configuration.vi.md), [triển khai](deployment.vi.md) và
[vận hành](operations.vi.md).
