# Nhật ký thay đổi

> 🌐 Language / Ngôn ngữ: [English](CHANGELOG.md) | **Tiếng Việt**

Changelog chỉ ghi các tính năng có ý nghĩa với người dùng, không
chứa mã giai đoạn nội bộ hoặc nhật ký thử nghiệm tạm thời.

## Chưa phát hành ổn định — public preview

### Đã bổ sung
- API FastAPI bất đồng bộ có xác thực và PostgreSQL.
- Bốn GPU worker NVIDIA L40S độc lập phục vụ GGUF, có scale-to-zero.
- Truy vết model, khóa revision, SHA256 và bằng chứng inference thật.
- Job idempotent, retry lỗi đã xác nhận, quota và xử lý uncertain.
- Công cụ xem billing chỉ đọc, ngân sách GPU ước tính tùy chọn và
  CPU monitor chạy mỗi giờ.
- Tài liệu EN/VI, bảng giấy phép model, MIT License cho mã nguồn,
  các chính sách cộng đồng và bảo mật GitHub.

### Đã nghiệm thu
- Bốn GPU khác nhau hoạt động; output thật đi qua API và PostgreSQL.
- Giới hạn 1.000 Unicode code point và hai request cùng model.
- Regression test CPU và công cụ tái lập local.

### Chưa khẳng định
- Chưa có điểm chất lượng dịch được chứng nhận, SLA liên tục,
  trần chi phí thực tế của nhà cung cấp hoặc chứng nhận bảo mật.

Xem [lộ trình](docs/roadmap.vi.md), [benchmark](docs/benchmarking.vi.md)
và [vận hành](docs/operations.vi.md). Chưa công bố release ổn định
khi các yêu cầu còn lại chưa hoàn thành.
