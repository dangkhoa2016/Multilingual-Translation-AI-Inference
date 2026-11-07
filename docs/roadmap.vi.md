# Lộ trình cùng cộng đồng

> 🌐 Language / Ngôn ngữ: [English](roadmap.md) | **Tiếng Việt**

Multilingual Translation AI Inference là dịch vụ dịch thuật dành cho việc sử
dụng API thực tế và tự triển khai. Lộ trình tập trung vào khả năng vận hành,
độ tin cậy, bảo mật và tích hợp — không hướng tới xếp hạng model hay benchmark
chất lượng bản dịch. Đây là các ý tưởng để cộng đồng thảo luận, không phải
cam kết tính năng hoặc lịch phát hành.

## Những gì đã có trong phiên bản 1.0.0

- FastAPI Gateway xác thực Bearer và PostgreSQL lưu trạng thái job bền vững.
- Job dịch thuật bất đồng bộ, kiểm tra đầu vào và bảo vệ idempotency.
- Bốn worker GGUF NVIDIA L40S được quản lý độc lập.
- Demo và regression test CPU cùng tài liệu song ngữ.
- Mã nguồn MIT và ghi công riêng các model upstream.

## Ưu tiên đóng góp đề xuất

1. **Vận hành API đáng tin cậy:** cải thiện tài liệu vòng đời job, xử lý lỗi,
   khôi phục yêu cầu đã tiếp nhận, bảo vệ concurrency và hướng dẫn xử lý
   hàng đợi quá tải hoặc lỗi upstream. Giữ nguyên bảo đảm idempotency và
   kiểm thử trường hợp lỗi mà không phải gọi GPU có phí.
2. **Bảo mật và sử dụng công bằng:** đề xuất credential riêng cho từng client,
   phân quyền theo phạm vi, quota và rate-limit với ranh giới tin cậy rõ ràng.
   Đây là hướng mở rộng trong tương lai, không phải tính năng đã phát hành;
   cần bổ sung CPU test và ví dụ cấu hình an toàn trước khi bật.
3. **Quan sát vận hành và tích hợp:** bổ sung chỉ số vận hành phù hợp với
   quyền riêng tư và thông tin chẩn đoán có cấu trúc (không ghi log văn bản
   dịch hoặc token), ví dụ API client tái sử dụng và test quá trình polling
   job bất đồng bộ. Các ví dụ mặc định nên dùng phản hồi giả lập.

Hãy thảo luận đề xuất qua [GitHub Issues](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/issues)
trước khi thực hiện những thay đổi lớn.

## Hướng mở rộng có thể cân nhắc

- Client SDK và ví dụ sử dụng bằng các ngôn ngữ lập trình khác.
- Tích hợp giám sát, chẩn đoán sức khỏe hệ thống và cảnh báo tùy chọn.
- Chính sách tiếp nhận request có cấu hình, giới hạn sử dụng theo client và
  kiểm soát số job chạy đồng thời.
- Hướng dẫn triển khai ở các môi trường khác và bổ sung model backend phù
  hợp, với yêu cầu tài nguyên và giấy phép được ghi rõ.

Các nội dung trên chỉ là đề xuất, không phải cam kết về độ sẵn sàng production
hay tính năng đã hỗ trợ trong bản hiện tại. Xem
[hướng dẫn đóng góp](../.github/CONTRIBUTING.vi.md) để tham gia.
