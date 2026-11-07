# Chính sách bảo mật

> 🌐 Language / Ngôn ngữ: [English](SECURITY.md) | **Tiếng Việt**

## Phạm vi

Đây là dịch vụ inference tự triển khai, hoạt động độc lập. Người vận
hành tự chịu trách nhiệm về token API, mật khẩu database, cloud account,
chi phí GPU, cấu hình truy cập ngoài và lưu giữ dữ liệu.

## Báo cáo lỗ hổng

**Không tạo issue công khai chứa cách khai thác, secret hoặc dữ liệu người
dùng.** Hãy dùng tính năng báo cáo bảo mật riêng tư/Security Advisory của
GitHub nếu được bật, hoặc liên hệ riêng **Đăng Khoa <i.am@dangkhoa.dev>**.

Cung cấp đường dẫn mã nguồn bị ảnh hưởng, rủi ro, cách tái hiện an toàn
và phiên bản liên quan. Không gửi token production hay database URL thật.

## Ranh giới bảo vệ hiện có

- Tất cả endpoint `/v1` cần bearer token; `/health` công khai.
- Server nội bộ của GPU worker chỉ bind loopback.
- PostgreSQL giữ trạng thái job và khóa chống gửi trùng.
- Trạng thái chưa xác định **không** bị tự retry inference.
- Ngân sách USD ở lớp ứng dụng chỉ là ước tính.
- Chưa công bố chứng nhận bảo mật hoàn chỉnh hoặc multi-tenancy.

Ưu tiên xử lý riêng tư trước khi công khai chi tiết lỗ hổng.
