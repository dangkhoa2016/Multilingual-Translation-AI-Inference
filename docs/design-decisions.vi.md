# Quyết định kỹ thuật và đánh đổi

> 🌐 Language / Ngôn ngữ: [English](design-decisions.md) | **Tiếng Việt**

Đây là các quyết định kiến trúc đang có hiệu lực, không phải nhật ký
tiến độ hay mã nhiệm vụ nội bộ.

## Một App, bốn worker độc lập

Cả bốn GPU class và CPU gateway nằm trong cùng
[`modal_app.py`](../modal_app.py). Mỗi model có Volume riêng,
prompt/decoding riêng và container GPU riêng. Kiến trúc phù hợp
tần suất API thấp, giảm phí GPU rảnh so với bốn deployment luôn chạy.

Đánh đổi: cold start phải nạp hàng chục GB trọng số, và việc
cấp phát đồng thời bốn L40S tùy quota/capacity Modal.
Scale-to-zero không xóa chi phí Volume và database.

## PostgreSQL là nguồn dữ liệu bền vững

Job được commit vào PostgreSQL trước khi dispatch tới Modal.
Claim token ngăn hai worker xử lý trùng cùng run, kết quả được lưu
trước khi API client polling. Modal `spawn()` không thể commit
atomically cùng PostgreSQL nên cần phân biệt lỗi đã xác nhận
với trạng thái không chắc chắn. **Không tự retry uncertain**.

Tải hiện tại không cần Redis/Celery/Sidekiq. Khi throughput và
công bằng hàng đợi tăng, có thể cân nhắc queue chuyên dụng riêng.

## Tên tài nguyên không khóa vào nhà cung cấp

Modal App, Secret, biến môi trường và API contract không gắn tên
một nhà cung cấp PostgreSQL cụ thể. Khi chuyển hạ tầng, giữ tên
tài nguyên, migrate dữ liệu, xác minh schema rồi cập nhật Secret.

## Nguồn gốc model và giấy phép

GGUF được khóa theo revision, tên file, kích thước và SHA256,
được kiểm tra bằng CPU trước khi load model. Mã nguồn riêng
dùng MIT; model bên thứ ba vẫn theo giấy phép Apache-2.0
công bố từ upstream. Không lưu trọng số trong Git.

## Bảo mật và chi phí

Chỉ public CPU API có xác thực, không mở trực tiếp model server
loopback ở GPU. Ngân sách ước tính có thể hạn chế nhận request
nhưng không phải trần hóa đơn thật. Workspace Budget và kênh
cảnh báo thực tế phải do người vận hành cấu hình.

Xem [kiến trúc](architecture.vi.md), [giấy phép model](../MODEL_LICENSE.vi.md)
và [vận hành](operations.vi.md).
