# Kiểm tra bản cài đặt của bạn

> 🌐 Language / Ngôn ngữ: [English](independent-validation.md) | **Tiếng Việt**

Dùng hướng dẫn này để kiểm tra bản cài local, kết nối notebook với gateway
riêng và xác minh deployment tự triển khai. Bắt đầu bằng demo CPU;
kiểm tra GPU cần tài nguyên do bạn cấu hình và có phát sinh phí cloud.

## 1. Kiểm tra luồng API local

Làm theo [Quick Start](../README.vi.md#bắt-đầu--không-cần-gpu) trong virtual
environment Python 3.12+ mới, cài `.[demo]`, rồi chạy:

```bash
python -m pip check
python scripts/examples/local_demo.py
```

Kết quả mong đợi: **POST 202**, **GET 200**, `status: completed` và
`is_mock_result == true`. Demo kiểm tra luồng gửi, lưu và đọc job bằng
SQLite tạm cùng văn bản mock. Bản dịch thật được kiểm tra riêng trên
gateway đã triển khai của bạn.

## 2. Gửi yêu cầu dịch từ notebook

Mở [notebook API](../notebooks/translation_api_demo.ipynb) trên Jupyter,
Colab hoặc Kaggle. Tắt mọi cờ live và **Run All offline** một lần.
Bước này khởi tạo `Client helpers`; sử dụng bình thường không cần sửa hay chạy lại chúng.

1. Trong **Basic Settings**, chọn model, ngôn ngữ và văn bản mẫu.
2. Nạp gateway và Bearer token qua Secrets riêng.
3. Trong Basic Settings, bật xác nhận chi phí GPU và polling job đã gửi.
   Với một model, bật `RUN_SINGLE_MODEL_POST`, chọn `"single"`. Để so sánh,
   bật `RUN_MULTI_MODEL_POST`, chọn `"multi"` và chọn `MULTI_MODEL_KEYS`
   (mặc định hai model; chủ động chọn thêm, tối đa bốn). Giữ cờ POST còn lại tắt.
   Chạy **Basic Settings → Load private Secrets → POST translation → GET job**
   cho một model, hoặc thay bằng **POST benchmark** để so sánh.
   Không Run All khi các cờ POST có phí đang bật.
4. Để chỉ xem lại, tắt cả hai cờ POST rồi chạy
   **Basic Settings → GET job**. Chỉ bật `SHOW_TRANSLATIONS` với văn bản không nhạy cảm.
   Đối chiếu attempt mới nhất của từng model theo từng cột; model lỗi giữ trạng thái
   và mã lỗi riêng, các bản dịch thành công còn lại vẫn xem được.

Với yêu cầu mới sau khi đã kiểm tra kết quả trước, đổi cả
`TEXT_TO_TRANSLATE` và `NEW_SINGLE_REQUEST_ACTION`, hoặc `NEW_BENCHMARK_REQUEST_ACTION`
để so sánh, tại Basic Settings. Nếu POST chưa rõ kết quả,
giữ key/payload gốc và đối soát trước khi gửi lại.

## 3. Đọc tiếp job đã nhận sau restart

Trước khi restart, lưu kín UUID đã nhận theo **Save accepted job UUID** /
**View saved job UUID** trong notebook. Tạm bật `SHOW_JOB_IDS=True`, chạy
cell chỉ đọc UUID, lưu thành `TRANSLATION_EXISTING_JOB_ID` riêng tư,
xóa output rồi tắt lại `SHOW_JOB_IDS=False`.

Sau khi restart kernel:

1. **Run All offline** với mọi cờ live tắt để khởi tạo kernel mới.
2. Trong Basic Settings giữ `RUN_SINGLE_MODEL_POST=False`, `RUN_MULTI_MODEL_POST=False`
   và `RUN_SUBMITTED_JOB_POLL=False`. Trong **Advanced Settings** bật `RUN_EXISTING_JOB_POLL=True`.
3. Nạp kín `TRANSLATION_GATEWAY_BASE_URL`, `TRANSLATION_API_BEARER_TOKEN`
   và `TRANSLATION_EXISTING_JOB_ID`. Với Colab/Kaggle Secrets, chọn provider
   và bật `LOAD_EXISTING_JOB_ID_FROM_SECRETS=True`; giữ `False` nếu dùng biến
   môi trường local. GET theo UUID không cần lưu request key.
4. Chạy **Basic Settings → Advanced Settings → Load private Secrets → GET job**.
   Luồng này không gửi POST hay tạo job GPU. Nếu thiếu UUID hoặc credential
   gốc, khôi phục chúng trước khi tiếp tục.

## 4. Kiểm tra deployment tự triển khai

| Thành phần | Cách kiểm tra | Kết quả mong đợi |
|---|---|---|
| Database và API | Làm theo [triển khai](deployment.vi.md), chạy migration và dùng mock gateway có xác thực | Job và kết quả được lưu bền vững trong PostgreSQL của bạn |
| Tệp model | Xác minh GGUF đã khóa revision và cấu hình Modal Secrets/Volumes | Bốn artifact khớp manifest model |
| GPU inference | Bật dispatcher GPU và chủ động chạy smoke test trong [độ tin cậy](reliability.vi.md) | Các run được yêu cầu hoàn tất với đầu ra không mock |
| Khôi phục | Lặp lại luồng chỉ GET bên trên với job đã nhận | Đọc được đúng job mà không gửi POST mới |

Ghi revision mã nguồn, phiên bản phụ thuộc và kết quả quan sát khi so sánh
các bản cài. CPU mock, thực thi GPU và đánh giá chất lượng dịch kiểm tra
những khía cạnh khác nhau; xem [độ tin cậy](reliability.vi.md) và
[lộ trình cộng đồng](roadmap.vi.md) về vận hành và tích hợp.

## Chia sẻ phản hồi

Nếu bước nào bị lỗi hoặc chưa rõ, mở
[GitHub Issue](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/issues)
với OS, phiên bản Python/package, bước đã thực hiện, hành vi mong đợi và
ví dụ tái hiện tối thiểu. Xóa token, URL riêng, UUID và văn bản dịch khỏi
tệp đính kèm. Xem [hỗ trợ](../.github/SUPPORT.vi.md) khi cần trợ giúp.
