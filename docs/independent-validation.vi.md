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

## 2. Chạy full demo từ notebook

Mở [notebook API](../notebooks/translation_api_demo.ipynb) trên Jupyter, Colab hoặc Kaggle. `DISPLAY_LANGUAGE="en"` là mặc định (đổi `"vi"` để hiển thị tiếng Việt). Chọn `DEMO_MODE="offline"` và **Run All** để chạy warm-up/ba lượt đo giả lập, hoàn toàn không dùng Internet/GPU.

Muốn thử GPU trên **deployment của bạn**:

1. Bật `modal-gpu` theo [hướng dẫn dành cho operator](deployment.vi.md), kiểm tra `/health` có `phase="gpu"`, `inference_enabled=true` và model đã chọn được bật/đã xác minh ở `/v1/models`.
2. Có thể đặt `TRANSLATION_GATEWAY_BASE_URL` và `TRANSLATION_API_BEARER_TOKEN` trong Colab/Kaggle Secrets hoặc biến môi trường. Nếu thiếu hoặc Secrets timeout, **Run All tự mở ô nhập ẩn**.
3. Chọn `DEMO_MODE="gpu"` và giữ mặc định `BENCHMARK_SEQUENCE="per_model"`; kiểm tra `WARMUP_TEXT` và ba đoạn `MEASUREMENT_TEXTS`. Với bốn model, **Run All gửi tối đa 16 API jobs thật**: warm-up riêng từng model, ngay sau đó đo ba lượt benchmark một model (**16 GPU model-runs**). Tùy chọn `BENCHMARK_SEQUENCE="parallel"` giữ luồng đa model cũ với năm API jobs và cũng gồm 16 model-runs. Chạy GPU có thể phát sinh phí.
4. Giữ cửa sổ idle scaledown mặc định 60 giây khi chạy `per_model`; có thể tạm dùng 120 giây cho thí nghiệm dài và cần khôi phục sau đó. GPU idle còn warm có thể phát sinh phí. Nhấn **Run All**, nhập URL/token qua ô ẩn khi được hỏi; notebook tự polling từng job. Chỉ dùng văn bản công khai, không nhạy cảm nếu chia sẻ output.

Run All giãn cách các POST GPU mới tối thiểu 6,25 giây nhằm phù hợp quota mặc định 10 jobs/phút khi gateway không có lưu lượng khác. Notebook không tự tăng quota; nếu gateway đã có tải hoặc giới hạn chặt hơn, HTTP 429 vẫn dừng demo và không tự gửi lại POST.

Nếu `GET /health` bị HTTP 403 qua Cloudflare custom domain, proxy có thể chặn client Python. Notebook dùng User-Agent rõ ràng. Có thể dùng HTTPS Gateway Modal trực tiếp của deployment riêng hoặc điều chỉnh Cloudflare. Không đặt Bearer token trong URL.

Bất cứ warm-up/lượt đo GPU nào bị lỗi, chưa rõ trạng thái hoặc trả mock sẽ khiến demo dừng trước POST có phí tiếp theo. Kết quả thiếu không được báo thành công.

Notebook là HTTP client dùng CPU; không cần GPU Kaggle/Colab. Notebook cũng không tự bật dispatcher GPU. Không cần bật các cờ POST True/False hay xác nhận có phí riêng.

**Lỗi GET tạm thời:** HTTP 429 được thử lại theo `Retry-After` trong thời gian polling; 502/503/504 và lỗi mạng dùng GET-only backoff có giới hạn. Lỗi xác thực/xung đột dừng ngay, không lặp POST có phí.

**Bảng so sánh:** HTML responsive escape toàn bộ nội dung từ API và hiển thị lần thử mới nhất, mã lỗi an toàn và metrics số. Trường thiếu hiển thị `N/A`.

### Điều chỉnh scaledown tạm thời khi benchmark

Bốn worker L40S mặc định có `scaledown_window=60` giây và `min_containers=0`. Trong lượt GPU thật trên tài khoản chính thức, Gemma-4 mất reuse ở TEXT 2: thời gian từ lúc TEXT 1 hoàn tất đến khi TEXT 2 được nhận là 7,034 giây, vượt cửa sổ 5 giây cũ. Logs Modal xác nhận container GPU khác, nhưng không ghi lý do dừng chính xác. Cửa sổ 60 giây tính đến HTTP preflight, polling và nhịp POST 6,25 giây mà không bảo đảm reuse tuyệt đối. GPU idle còn warm có thể tính phí. Khi cần thử giữ warm lâu hơn, có thể tạm dùng 120 giây và **giữ `min_containers=0`**, sau đó khôi phục 60 giây. `GET /health` chỉ kiểm tra CPU gateway.

Trong terminal đã đăng nhập đúng Modal workspace của bạn, dùng environment thực tế:

```bash
export MODAL_ENVIRONMENT="YOUR_MODAL_ENVIRONMENT"
APP="multilingual-translation-ai-inference-api-and-model-workers"
for worker in HyMT2L40SWorker IndexTranslateL40SWorker Gemma4L40SWorker Qwen35L40SWorker; do
  modal function autoscaler update --env "$MODAL_ENVIRONMENT" \
    "$APP/$worker.*" --scaledown-window 120
done

# Sau benchmark HOẶC khi bị gián đoạn, PHẢI khôi phục 60 giây:
for worker in HyMT2L40SWorker IndexTranslateL40SWorker Gemma4L40SWorker Qwen35L40SWorker; do
  modal function autoscaler update --env "$MODAL_ENVIRONMENT" \
    "$APP/$worker.*" --scaledown-window 60
  modal function autoscaler settings --env "$MODAL_ENVIRONMENT" "$APP/$worker.*"
done
```

Cửa sổ 120 giây chỉ giảm nguy cơ cold start, không bảo đảm container không bị thay thế. `queue_ms` bao gồm điều phối và khởi động chứ không chỉ thời gian nạp model.

### Quan sát độ trễ GPU

Một phiên thực tế 16 lượt GPU đều hoàn tất, nhưng cách warm-up song song cũ khiến model hoàn tất sớm có thể scale down khi chờ model khác. Dữ liệu **Modal Function Call thực tế** cho thấy:

| Worker | Lượt gọi | Container khác nhau | Chậm nhất từ enqueue đến start |
|---|---:|---:|---:|
| Hy-MT2 | 4 | 3 | 111,18 giây |
| Index-Translate | 4 | 3 | 351,00 giây |
| Gemma-4 | 4 | 3 | 903,24 giây |
| Qwen3.5 | 4 | 4 | 36,67 giây |

Đây là timestamp Modal thực, không công bố call ID, GPU UUID, token hoặc nội dung người dùng. **Không thể tách riêng** thời gian chờ cấp GPU khỏi điều phối container, nạp GGUF và readiness chỉ từ những bản ghi này; Modal không cung cấp thời lượng startup riêng cho các lượt gọi đó. Cả 16 lượt đều thành công. Vì mỗi model đã dùng 3–4 container cho bốn lượt, warm-up cũ không bảo đảm reuse. Chế độ `per_model` mặc định mới đo ngay ba văn bản sau warm-up của chính model đó; `worker_reuse_confirmed` trên deployment mới là bằng chứng reuse trực tiếp. Luồng per-model mới đã được kiểm chứng trên bản triển khai cập nhật; xem kết quả riêng bên dưới.

### Nghiệm thu GPU theo từng model

Phiên notebook GPU trên bản triển khai tự quản lý chạy theo `per_model` mặc định, mỗi model nhận cùng ba văn bản mẫu công khai từ tiếng Anh sang tiếng Việt. **16/16 lượt GPU thật hoàn thành** (bốn warm-up và mười hai lượt đo qua 16 API jobs riêng). API ghi `worker_reuse_confirmed=1` cho **12/12 lượt đo**. [Bằng chứng số đã làm sạch](gpu-per-model-evidence.json) có đủ mười sáu lượt đo, không chứa định danh cloud hay nội dung dịch; cho phép đối chiếu phép tính nhưng không thay thế bằng chứng hạ tầng gốc được lưu riêng. Thống kê Modal đối chiếu xác nhận mỗi worker có bốn lượt gọi thành công trên **một container**, không có lỗi container trong phiên.

| Model | Queue + startup warm-up | Engine ready | Queue trung vị khi đo | Inference trung vị | End-to-end trung vị | Xác nhận reuse |
|---|---:|---:|---:|---:|---:|---:|
| Hy-MT2 | 453,831 giây | 16,025 giây | 2,308 giây | 0,559 giây | 3,888 giây | 3/3 |
| Index-Translate | 34,582 giây | 23,053 giây | 0,390 giây | 0,448 giây | 0,894 giây | 3/3 |
| Gemma-4 | 36,360 giây | 18,027 giây | 0,584 giây | 2,425 giây | 3,129 giây | 3/3 |
| Qwen3.5 | 35,067 giây | 24,040 giây | 0,580 giây | 0,456 giây | 1,087 giây | 3/3 |

Đây là **thời gian quan sát được từ API**, không phải cam kết SLA hay điểm chất lượng dịch. `queue_ms` tính từ lúc tạo run đến khi worker bắt đầu xử lý; `engine_ready_ms` chỉ đo khoảng khởi động và sẵn sàng của llama.cpp trong container. **Warm-up Hy-MT2 có thời gian queue/startup bất thường**, dù engine sẵn sàng nhanh. Logs hiện có không đủ để quy toàn bộ phần chênh lệch cho cấp phát GPU hay nạp model. Các lượt đo sau đó tái sử dụng worker; không quan sát thấy container restart hoặc function call thất bại.

Cell chính của notebook hoàn tất sau **11 phút 28 giây**, so với **21 phút 11 giây** ở phiên cũ với cách điều phối khác. Đây là hai quan sát riêng, **không phải phép đo nhân quả có kiểm soát**. Ba văn bản khác độ dài nên các trung vị chỉ mô tả phiên demo, không phải phép đo thông lượng chuẩn hóa cùng độ dài. Không cần chạy thêm GPU chỉ để kiểm chứng worker reuse.

## 3. Chạy lại và khôi phục an toàn

Mặc định, `DEMO_RUN_ID="auto"` tạo ID mới từ timestamp UTC và hậu tố ngẫu nhiên một lần trong mỗi Python kernel. Chạy lại Run All trong **cùng kernel** giữ nguyên ID và tái sử dụng idempotency key xác định khi stage/payload không đổi. **Kernel mới sẽ tạo ID mới và có thể gửi thêm GPU jobs tính phí**; không restart rồi POST lại khi kết quả trước chưa rõ. Muốn tiếp tục lượt cũ qua kernel mới, chỉ định lại đúng ID gốc và giữ nguyên payload khi bản ghi server còn tồn tại, hoặc dùng `RECOVERY_JOB_ID` để khôi phục chỉ bằng GET. Notebook hiển thị văn bản nguồn tiếng Anh trước mỗi request và trong bảng kết quả; chỉ chia sẻ dữ liệu không nhạy cảm.

**Khôi phục bằng Run All chỉ GET:** Chọn `RECOVERY_JOB_ID="prompt"` cùng `DEMO_MODE="gpu"`. Run All hỏi UUID qua prompt ẩn (hoặc đọc Secret/biến môi trường `TRANSLATION_EXISTING_JOB_ID`) và chỉ GET job cũ, không yêu cầu gateway còn bật GPU. Trong kernel tin cậy, `accepted_demo_job_ids()` trả danh sách UUID đã nhận. Muốn nhập lại credential thủ công, chạy `reset_demo_credentials()` trong cell riêng tư tạm thời; nếu dùng environment/Secrets cần sửa tại nguồn.

**Nếu chưa rõ kết quả POST, không tự chạy lại mù quáng.** Tìm UUID job đã nhận từ audit/database riêng tư rồi thực hiện **GET-only** bằng quyền truy cập của bạn:

```bash
curl -fsS -H "Authorization: Bearer $TRANSLATION_API_BEARER_TOKEN"   "$TRANSLATION_GATEWAY_BASE_URL/v1/jobs/YOUR_ACCEPTED_JOB_UUID"
```

Không đưa Bearer token hoặc UUID job thật vào notebook/log công khai. Khi chủ động đánh giá lần mới, hãy đối soát job cũ trước, rồi dùng kernel mới với `DEMO_RUN_ID="auto"` hoặc chỉ định một ID mới duy nhất.

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
