# Giấy phép và ghi công các model bên thứ ba

> 🌐 Language / Ngôn ngữ: [English](MODEL_LICENSE.md) | **Tiếng Việt**

**Giấy phép MIT của repository chỉ áp dụng cho mã nguồn do dự án tự phát
triển, không tự động áp dụng cho trọng số của model bên thứ ba.** Repository
không phân phối lại trọng số model.

Tôi đã đối chiếu thông tin giấy phép tại **revision Hugging Face đã khóa**
của cả checkpoint gốc lẫn bản GGUF. Metadata của cả bốn nhóm nguồn đều
công bố **Apache-2.0**. Văn bản tiêu chuẩn có tại
[Apache License, Version 2.0](THIRD_PARTY_LICENSES/Apache-2.0.txt).
Trước khi cung cấp dịch vụ thương mại hay phân phối lại model, người triển
khai cần tự kiểm tra giấy phép upstream tại đúng revision, các thông báo
bản quyền, nhãn hiệu, thành phần bên thứ ba và quy định liên quan.

| Model triển khai | Checkpoint gốc | Bản GGUF | Giấy phép công bố |
|---|---|---|---|
| Tencent Hy-MT2-30B-A3B | [Tencent original](https://huggingface.co/tencent/Hy-MT2-30B-A3B) | [Tencent GGUF](https://huggingface.co/tencent/Hy-MT2-30B-A3B-GGUF) | Apache-2.0 |
| Index-Translate-35B-A3B-preview | [IndexTeam original](https://huggingface.co/IndexTeam/Index-Translate-35B-A3B-preview) | [IndexTeam GGUF](https://huggingface.co/IndexTeam/Index-Translate-35B-A3B-preview-GGUF) | Apache-2.0 |
| Gemma 4 31B IT | [Google original](https://huggingface.co/google/gemma-4-31B-it) | [Unsloth GGUF](https://huggingface.co/unsloth/gemma-4-31B-it-GGUF) | Apache-2.0 |
| Qwen3.5-35B-A3B | [Qwen original](https://huggingface.co/Qwen/Qwen3.5-35B-A3B) | [Unsloth GGUF](https://huggingface.co/unsloth/Qwen3.5-35B-A3B-GGUF) | Apache-2.0 |

## Nguồn gốc chính xác

Revision bất biến, tên file, dung lượng, SHA256 và Modal Volume tương ứng
được khóa trong [manifest model](models/four_l40s_workers_q8_0_manifest.json).
Runtime kiểm tra marker xác minh SHA256 trước khi load trọng số. Metadata
trong manifest giúp tái lập kết quả nhưng không thay thế việc đọc đầy đủ
điều khoản giấy phép gốc.

Tencent có `LICENSE.txt` cho Hy-MT2 ở cả checkpoint và GGUF; Qwen có file
LICENSE trong repo checkpoint gốc. Giấy phép Gemma 4 cũng được Google
công bố tại [trang chính thức](https://ai.google.dev/gemma/apache_2).
Với những nguồn không có file LICENSE riêng trong danh sách file tại
revision đã khóa, thông tin bên trên dựa vào metadata của model card;
không nên diễn giải đây là xác nhận pháp lý độc lập.

## Phạm vi không được cấp quyền

- Không sở hữu hoặc tái cấp phép trọng số model.
- Không có quyền tự ý sử dụng nhãn hiệu các nhà phát triển model.
- Không mặc định coi dịch vụ cloud, dataset hay dữ liệu bên ngoài là MIT.
- Không bảo đảm giấy phép vẫn giữ nguyên khi thay checkpoint/revision.

Xem [thông báo bên thứ ba](NOTICE.vi.md), [danh sách model](docs/models.vi.md)
và [MIT LICENSE của mã nguồn](LICENSE). Tài liệu này không phải tư vấn pháp lý.
