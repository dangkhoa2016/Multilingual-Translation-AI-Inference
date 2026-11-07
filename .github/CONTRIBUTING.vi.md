# Hướng dẫn đóng góp

> 🌐 Language / Ngôn ngữ: [English](CONTRIBUTING.md) | **Tiếng Việt**

Cảm ơn bạn muốn đóng góp cho Multilingual Translation AI Inference.

## Trước khi sửa đổi

1. Tìm các issue hiện có và đọc [kiến trúc](../docs/architecture.vi.md),
   [triển khai](../docs/deployment.vi.md), [giấy phép model](../MODEL_LICENSE.vi.md).
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
python scripts/audit_public_repository.py
```

Các PR thông thường chỉ cần kiểm thử CPU. Không tự gọi Modal GPU thật
khi chưa có thỏa thuận về quyền truy cập và giới hạn chi phí.

## Quy tắc pull request

- Commit có mục đích rõ ràng theo Conventional Commits, ví dụ
  `fix(api): reject invalid translation payloads`.
- Ưu tiên từng commit nhỏ, **khoảng 600 dòng code thay đổi trở xuống**.
  Tài liệu song ngữ dài có thể vượt ngưỡng này khi cần thiết.
- Có unit test phù hợp, cập nhật tài liệu và giải thích thay đổi API
  hoặc schema có nguy cơ phá vỡ tương thích.
- Không tạo timestamp giả, không nhận quyền tác giả không thuộc mình,
  không tuyên bố kiểm thử chưa thực hiện.
- Tôn trọng bản quyền và các nghĩa vụ giấy phép upstream.

Dùng [mẫu pull request](PULL_REQUEST_TEMPLATE.vi.md).
