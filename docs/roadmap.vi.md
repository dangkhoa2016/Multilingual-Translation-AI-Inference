# Lộ trình và giới hạn bằng chứng

> 🌐 Language / Ngôn ngữ: [English](roadmap.md) | **Tiếng Việt**

Dự án hiện là **bản thử nghiệm inference GPU thật có xác thực**.
Bốn model GGUF khác nhau đã hoàn thành job dịch trên Modal và lưu
kết quả vào PostgreSQL. Khả năng chạy được không đồng nghĩa
chất lượng dịch hoặc bảo mật production đã được chứng nhận.

## Đã nghiệm thu

- Bốn L40S worker load được GGUF có revision/SHA256 đã khóa.
- Quan sát bốn GPU hoạt động song song, UUID khác nhau.
- CPU API tạo và polling job bền vững trong PostgreSQL.
- API dịch một model và benchmark bốn model trả kết quả thật.
- Đã kiểm thử đúng giới hạn 1.000 Unicode code point.
- Đã thử concurrency nhỏ trên cùng model và tái sử dụng container.
- CPU monitor chạy mỗi giờ, không cấp phát GPU.
- Idempotency, quota, uncertain-state có unit test CPU.

## Còn thiếu trước khi phát hành ổn định

1. **Chất lượng dịch:** dataset tham chiếu khóa cố định, người
   kiểm duyệt tám hướng ngôn ngữ, chấm nghĩa/thuật ngữ và phân
   tích sai lệch. Hy-MT2 từng có lỗi thay đổi vật liệu.
2. **Phục hồi vận hành:** fault injection trên staging riêng,
   mất xác nhận, phục hồi, tải hàng đợi và soak test.
3. **Bảo mật:** phân tách tenant nếu cần, rà soát xâm nhập,
   vòng đời token, chính sách lưu giữ dữ liệu.
4. **Chi phí thực tế:** đặt Workspace Budget trong Modal và
   có kênh cảnh báo bên ngoài. Quota dự trù mỗi run không
   đo được hóa đơn thật.
5. **Nghiệm thu phát hành:** tài liệu, tính tương thích,
   CI và điểm chất lượng độc lập trước khi gọi là stable.

Không suy diễn SLA throughput, model chiến thắng benchmark hoặc
storage GPU hoàn toàn miễn phí khi chưa có số liệu.

Xem [benchmark](benchmarking.vi.md), [độ tin cậy](reliability.vi.md),
[vận hành](operations.vi.md) và [hỗ trợ](../.github/SUPPORT.vi.md).
