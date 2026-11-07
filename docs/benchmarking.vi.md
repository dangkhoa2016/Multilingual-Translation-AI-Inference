# Đánh giá dịch thuật — bằng chứng và kiểm duyệt ngữ nghĩa

> 🌐 Language / Ngôn ngữ: [English](benchmarking.md) | **Tiếng Việt**

## Những gì đã nghiệm thu

Repository có báo cáo inference **thật** trên Modal L40S, không dùng
file JSON giả lập để tuyên bố model đã chạy được.

| Bằng chứng | Chứng minh được | Chưa chứng minh được |
|---|---|---|
| [Bốn GPU](../reports/four_gpu_parallel_inference.json) | Bốn model load và trả nội dung trên GPU riêng | Độ chính xác bản dịch |
| [Benchmark API](../reports/gpu_api_four_model_benchmark.json) | API xác thực, job bền vững, output không mock | Xếp hạng chất lượng |
| [Giới hạn 1.000 ký tự](../reports/unicode_input_boundary.json) | Bốn model xử lý giới hạn đầu vào | Hiệu năng văn bản rất dài |
| [Hy-MT2 đa ngôn ngữ](../reports/hy_mt2_quality_diagnostic.json) | Output qua tám hướng dịch | Điểm chất lượng có tham chiếu |
| [Kiểm duyệt thuật ngữ](../reports/hy_mt2_material_glossary_review.json) | Phân tích lỗi thay đổi vật liệu/ý nghĩa | Giải pháp hoàn hảo cho dịch sai |

Diagnostic Hy-MT2 bao gồm Anh↔Việt, Đức↔Việt, Nhật↔Việt và
Hàn↔Việt. Có 16 trường hợp hoàn thành, nhưng **không có cảnh báo tự
động không đồng nghĩa ngữ nghĩa đã đúng**.

## Các lỗi chất lượng quan trọng

Kiểm tra thủ công phát hiện trường hợp **silver compass** (la bàn bằng
bạc) bị dịch thành vật liệu khác. Dùng glossary giúp cải thiện một số
trường hợp đã biết, nhưng chưa có bằng chứng về chất lượng trên đầu
vào mới. Cả bốn model đều cần được kiểm tra cùng loại lỗi.

Hiện chưa model nào có bộ điểm chất lượng độc lập đủ lớn, được người
đánh giá có năng lực ngôn ngữ duyệt và có bản dịch tham chiếu.
**Không kết luận model tốt nhất hay đạt độ chính xác hoàn hảo.**

## Quy trình benchmark công bằng được đề xuất

1. Khóa nguồn dữ liệu độc lập với output model: câu ngắn/dài, phủ
   định, số liệu, đơn vị, thành ngữ, tên riêng, văn hóa, Markdown
   và placeholder.
2. Kiểm thử đủ tám hướng dịch; có người kiểm duyệt phù hợp với
   tiếng Đức, Nhật, Hàn, Anh và Việt.
3. Dùng chung nội dung nguồn, giới hạn sinh phù hợp và ghi rõ
   decoding; vẫn tôn trọng chat template riêng của từng model.
4. Đánh giá đúng ý, tự nhiên, thuật ngữ, thiếu/thừa nghĩa,
   bảo toàn định dạng và hallucination.
5. Công bố mức độ nhất quán giữa người chấm. Nếu dùng COMET/BLEU,
   ghi rõ triển khai metric và bản dịch tham chiếu.
6. Chỉ công bố artifact không có dữ liệu riêng tư người dùng.

## Cách tái lập bằng chứng

```bash
# CPU: kiểm tra báo cáo đã ghi, không cần GPU
python -m pytest -q
PYTHONPATH=src python scripts/verify_hy_mt2_metadata.py

# Kiểm thử GPU thật có tính phí, chỉ chạy khi được cho phép
PYTHONPATH=src python scripts/modal_four_model_gpu_smoke.py --help
PYTHONPATH=src python scripts/api_reliability_smoke.py --help
```

Các kết quả gốc và ghi chú kiểm duyệt nằm trong
[`reports/`](../reports). Timestamp ở các file máy là nguồn gốc
thử nghiệm, không phải lời hứa kết quả mãi không đổi.
Xem [model](models.vi.md) và [độ tin cậy](reliability.vi.md).
