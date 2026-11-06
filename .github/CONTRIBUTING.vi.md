# Hướng dẫn đóng góp

> 🌐 Language / Ngôn ngữ: [English](CONTRIBUTING.md) | **Tiếng Việt**

Mời bạn cùng đóng góp, dù mới dùng thử hay đang mở rộng một deployment.
Bạn không cần GPU hay tài khoản cloud để cải thiện tài liệu, ví dụ hoặc
mã ứng dụng có thể kiểm thử trên CPU.

## Bạn có thể đóng góp gì?

- Báo lỗi có cách tái hiện hoặc làm rõ một bước cài đặt.
- Cải thiện tài liệu English/Tiếng Việt và hướng dẫn notebook.
- Chia sẻ ví dụ tích hợp API ngắn.
- Thảo luận backend model, cách triển khai hoặc đánh giá chất lượng dịch qua
  [GitHub Issues](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/issues).

Với câu hỏi sử dụng, xem [hỗ trợ](SUPPORT.vi.md). Báo lỗ hổng theo
[chính sách bảo mật](SECURITY.vi.md).

## Trước khi sửa đổi

1. Tìm công việc liên quan trong các issue hiện có. Các hướng dẫn
   [kiến trúc](../docs/architecture.vi.md), [triển khai](../docs/deployment.vi.md)
   và [giấy phép model](../MODEL_LICENSE.vi.md) giải thích từng phần của dự án.
2. Trao đổi trước khi thay đổi API contract, nguồn model, xử lý trọng số
   hoặc cơ chế quản lý chi phí.
3. **Không commit** token, mật khẩu, trọng số model bên thứ ba hoặc dữ liệu
   dịch thuật có thông tin cá nhân.
4. Tất cả hướng dẫn Markdown hướng tới người dùng phải có đủ bản
   English/Tiếng Việt và liên kết chuyển ngôn ngữ hợp lệ.

## Kiểm thử local

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m pytest -q tests/security/test_publication_safety.py
```

Các PR thông thường chỉ cần kiểm thử CPU. Không tự gọi Modal GPU thật
khi chưa có thỏa thuận về quyền truy cập và giới hạn chi phí.

## Quy tắc pull request

- Commit có mục đích rõ ràng theo Conventional Commits, ví dụ
  `fix(api): reject invalid translation payloads`.
- Mỗi pull request tập trung vào một vấn đề hoặc cải tiến rõ ràng.
- Có unit test phù hợp, cập nhật tài liệu và giải thích thay đổi API
  hoặc schema có nguy cơ phá vỡ tương thích.
- Mô tả các kiểm tra đã chạy và giới hạn người review cần biết.
- Tôn trọng bản quyền và các nghĩa vụ giấy phép upstream.

Dùng [mẫu pull request](PULL_REQUEST_TEMPLATE.vi.md).
