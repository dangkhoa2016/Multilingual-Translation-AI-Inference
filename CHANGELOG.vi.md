# Nhật ký thay đổi

> 🌐 Language / Ngôn ngữ: [English](CHANGELOG.md) | **Tiếng Việt**

## [1.0.0]

Bản phát hành mã nguồn đầu tiên của **Multilingual Translation AI Inference**.

### Tính năng được bổ sung

- FastAPI gateway có xác thực để gửi job dịch bất đồng bộ bằng một model hoặc so sánh 1–4 model, đồng thời truy vấn trạng thái và kết quả.
- PostgreSQL lưu job, từng lần thực thi model, kết quả và hỗ trợ migration schema bằng Alembic.
- Bốn GPU worker NVIDIA L40S độc lập trên Modal cho Hy-MT2, Index-Translate, Gemma 4 và Qwen3.5; artifact GGUF Q8_0 được lưu riêng và khóa revision.
- Demo mock chạy offline trên CPU, notebook Jupyter API-client song ngữ, công cụ kiểm tra tính toàn vẹn model, triển khai và vận hành.
- Giám sát vận hành trên CPU theo yêu cầu hoặc lịch chạy mỗi giờ khi chủ động bật; mặc định không lên lịch tự động.
- Tạo hai Modal Secrets ban đầu từ một `.env` riêng tư khi chủ động bật; không ghi đè Secrets cũ và vẫn hỗ trợ JSON thủ công.

### Bảo mật và độ tin cậy

- Xác thực Bearer token cho gateway **single-tenant**; giới hạn request theo từng process cùng quota polling và tiếp nhận job dùng chung PostgreSQL.
- Kiểm tra đầu vào, giới hạn kích thước request, xử lý lỗi không làm lộ dữ liệu không tin cậy và kiểm soát nội dung nhạy cảm trong output notebook.
- Idempotency và kiểm soát tiếp nhận đồng thời; xử lý riêng các trạng thái thực thi chưa rõ kết quả để tránh retry mù và tạo thêm tác vụ GPU có phí.
- Telemetry inference tùy chọn, có giới hạn; lỗi hoặc thiếu metrics không làm mất kết quả dịch hợp lệ.

### Xác minh

- Regression tests chạy trên CPU và kiểm tra cài đặt sạch, bao gồm Quick Start trên Python 3.12/3.13.
- Các báo cáo lịch sử đã làm sạch ghi nhận hoạt động API có xác thực, lưu trữ PostgreSQL và những lượt chạy trên bốn GPU worker riêng biệt. **CI không chạy lại inference GPU thật.**

### Phạm vi bản phát hành

- Cung cấp mã nguồn và công cụ triển khai; **không đóng gói trọng số model và không cung cấp endpoint dịch thuật host sẵn**.
- Sử dụng GPU có tính phí. Bằng chứng hạ tầng đã ghi nhận **không chứng minh chất lượng dịch, uptime hoặc hiệu năng hiện tại**; không công bố điểm BLEU, COMET hay đánh giá con người độc lập.
- Gateway sử dụng một Bearer token chung, chưa cung cấp API key riêng cho từng client hoặc rate limit trước xác thực phân tán toàn cục.

Xem [README tiếng Việt](README.vi.md) để cài đặt và sử dụng API; xem [GitHub Release v1.0.0](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/releases/tag/v1.0.0) để đọc điểm nổi bật của bản phát hành.
