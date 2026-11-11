# Hướng dẫn sử dụng LARIS

LARIS là trợ lý nghiên cứu chạy cục bộ: nạp tài liệu của bạn vào kho, tìm kiếm có trích nguồn, đọc
file (kể cả PDF scan và ảnh bằng OCR), chạy skill và quy trình (workflow). Văn bản này được soạn sẵn
và in nguyên văn, không qua mô hình. Gõ `/how-to-use` bất cứ lúc nào để xem lại.

> **Lưu ý trạng thái:** mô hình nền chưa được nghiệm thu. Kênh tìm kiếm BM25 là kênh đáng tin;
> tìm kiếm dense và câu trả lời trích xuất còn yếu. Mọi câu trả lời phải có nguồn `[nguồn #hạng]`.

---

## 1. Khởi động nhanh

Có ba tiến trình, tất cả chạy trên máy bạn:

```bash
laris model serve --port 8000                 # API mô hình (tương thích OpenAI; hiện là bản giữ chỗ)
laris app serve                                # giao diện web, mặc định http://127.0.0.1:8765
laris agent chat                               # phiên làm việc trong terminal
```

- Chưa có mô hình thật: bỏ qua `model serve`; hệ thống dùng "trợ lý tích hợp" chỉ trích đoạn văn.
- Muốn dùng một API mô hình: `laris app serve --model-api-url http://127.0.0.1:8000/v1 --model-name laris-core`.
- Cổng, thư mục và mọi giới hạn nằm trong `configs/default.yaml`; ghi đè bằng
  `.laris/config.yaml`, biến môi trường `LARIS_*` (xem `.env.example`) hoặc tham số dòng lệnh.

## 2. Nạp tài liệu (kiến thức mới)

| Cách | Lệnh / thao tác |
|---|---|
| Web | Bảng **Kho tài liệu** → chọn file → **Nạp**; hoặc kéo thả file vào khung chat |
| Terminal | `laris app ingest thu-muc-hoac-file ...` |
| Trong chat | Nhờ trợ lý dùng công cụ `ingest_path` (cần bạn đồng ý) |

- Hỗ trợ: txt, md, pdf (có lớp chữ), ảnh và PDF scan (OCR `eng+vie`), jsonl/parquet kiểu BEIR.
- Mỗi lần nạp, hệ thống **tự tạo hoặc cập nhật một skill** `corpus-<tên thư mục hoặc tài liệu>`
  (chỉ chứa tên nguồn, số đoạn, thuật ngữ chính, các bước tìm kiếm và giới hạn; không chứa nội dung).
- Nạp lại cùng tài liệu sẽ thay thế bản cũ. Xem trạng thái kho: `laris app status` hoặc bảng Kho tài liệu.
- Tạo lại skill cho cả kho: `laris skills sync`.

## 3. Hỏi đáp và tìm kiếm

- Trong chat, hỏi bình thường: *"Các tài liệu của tôi nói gì về hiệu suất perovskite?"*.
- Câu trả lời về kho tài liệu luôn được tìm trước rồi mới trả lời, kèm trích nguồn `[nguồn #hạng]`.
  Thiếu trích nguồn, hệ thống yêu cầu viết lại một lần rồi mới cảnh báo.
- Chỉ tìm không trả lời: `laris app search --query "..."`; câu trả lời trích xuất:
  `laris app ask --query "..." ` (cần checkpoint cục bộ).
- Đính kèm file vào tin nhắn (nút 📎 hoặc kéo thả): trợ lý nhận đường dẫn tương đối và có thể đọc nó.

## 4. Lệnh gạch chéo (`/`)

Gõ `/` trong ô chat để mở menu (web) hoặc dùng trực tiếp (terminal).

| Lệnh | Tác dụng |
|---|---|
| `/how-to-use` | In hướng dẫn này (không gọi mô hình) |
| `/<tên-skill> <yêu cầu>` | Chạy một skill, ví dụ `/literature-review ...` |
| `/workflow <tên> <yêu cầu>` | Chạy một quy trình có giới hạn chặt |
| `/workflows` | Liệt kê quy trình (terminal) |
| `/skills` | Liệt kê skill (terminal) |
| `/compact [ghi chú]` | Nén ngữ cảnh ngay |
| `/context` | Xem mức dùng ngữ cảnh và trạng thái tự nén |
| `/rate up\|down` | Đánh giá câu trả lời vừa rồi (terminal) |
| `/learn on\|off` | Bật/tắt lưu dữ liệu fine-tune cục bộ (terminal) |
| `/write on\|off` | Tự duyệt các thao tác ghi (terminal) |
| `/model [URL [TÊN]]` | Xem/đổi API mô hình (terminal) |
| `/new`, `/sessions`, `/resume ID` | Quản lý phiên (terminal) |
| `/tools`, `/status`, `/exit` | Công cụ, trạng thái, thoát (terminal) |

Terminal còn có: `laris agent chat -p "câu hỏi"` (chạy một lần rồi thoát) và `--resume` (nối lại phiên cuối).

## 5. Skill

Skill là cách làm việc có sẵn (ví dụ tổng quan tài liệu, thiết kế thí nghiệm, phản biện).

- Xem: `laris skills list`, `laris skills show <tên>`.
- Dùng: `/<tên-skill> <yêu cầu>`, hoặc để trợ lý tự gọi khi yêu cầu khớp mô tả.
- Dạy kỹ năng mới: nói *"tôi muốn thêm một skill ..."* — trợ lý dùng skill `skill-authoring`, soạn bản
  nháp rồi gọi `save_skill` (cần bạn đồng ý). Hoặc tự viết `SKILL.md` rồi
  `laris skills lint <file>` và `laris skills add --file <file>`.
- Skill hợp lệ cần: tên chữ thường-gạch ngang, mô tả có "Use when ...", và các mục
  `## When to use`, `## Steps`, `## Output`, `## Limits`. Skill không được nhắc tới file chính sách,
  không chứa mật khẩu/khóa và không được yêu cầu bỏ qua quy tắc.
- Skill chỉ **thêm** kiến thức tác vụ; không bao giờ nới quy tắc, công cụ hay giới hạn.

## 6. Quy trình (workflow)

Quy trình là chuỗi bước có giới hạn cứng: công cụ được phép, số bước tối đa, mức duyệt, bắt buộc trích
nguồn và các mục phải có trong câu trả lời.

| Tên | Dùng khi |
|---|---|
| `grounded-qa` | Trả lời một câu hỏi chỉ dựa trên kho tài liệu, có nguồn và độ bất định |
| `document-intake` | Nạp tài liệu mới sau khi bạn đồng ý, rồi báo cáo kết quả |
| `evidence-review` | Rút claim, phương pháp, hạn chế và so sánh giữa các nguồn |
| `research-brief` | Viết bản tóm tắt nghiên cứu và lưu ra file sau khi bạn đồng ý |

Chạy: `/workflow grounded-qa <câu hỏi>`. Kiểm tra: `laris workflows list|show|check`.
Chỉ bạn mới khởi chạy được quy trình; mô hình không tự chọn hay mở rộng nó.

## 7. Ngữ cảnh dài và tự động nén

- **Tự nén luôn bật**: khi ngữ cảnh gần đầy (mặc định 80% của 32768 token), hệ thống cắt bớt kết quả
  công cụ cũ rồi tóm tắt các lượt cũ; bản gốc được lưu vào kho lưu trữ. Bạn làm việc liên tục được.
- Thanh ngữ cảnh hiển thị ở web; `/context` trong terminal. `/compact` để nén thủ công.
- Sau khi nén, nếu cần chi tiết cũ, hãy yêu cầu đọc lại nguồn thay vì dựa vào trí nhớ.

## 8. Cho phép và bảo mật

- **Hỏi trước khi ghi**: `write_file`, `ingest_path`, `save_memory`, `save_skill` luôn xin phép
  (terminal: `y` / `a` luôn trong phiên / `N`). Từ chối là quyết định cuối.
- Ghi file chỉ vào thư mục output; bộ nhớ dự án ở `.laris/memory/`.
- Trợ lý **không** đọc được: file chính sách và quy tắc nội bộ, `.env`, cấu hình, dữ liệu fine-tune,
  hội thoại của người khác, khóa và chứng chỉ. Yêu cầu tiết lộ prompt hay quy tắc nội bộ sẽ bị từ chối.
- Nội dung trong tài liệu là **dữ liệu không đáng tin**: chỉ dẫn nằm trong tài liệu không được làm theo.
- API mô hình ngoài máy bị chặn trừ khi bật `model_api.allow_remote`. Khóa API chỉ khai báo bằng
  **tên biến môi trường**, không ghi vào file.
- Chính sách có khóa toàn vẹn: sửa file chính sách mà không cập nhật khóa sẽ làm mọi phiên dừng.
  Kiểm tra: `laris harness verify`.

## 9. Cài đặt

Web: nút **Cài đặt**. Có thể đổi: địa chỉ API mô hình, tên mô hình, tên biến chứa khóa, hướng dẫn bổ
sung của bạn (không thay thế quy tắc hệ thống), tự duyệt ghi, tự nén (cửa sổ, ngưỡng), và bật/tắt lưu
dữ liệu fine-tune. Các thiết lập bảo mật không chỉnh được ở đây.

Thứ tự ưu tiên cấu hình (sau thắng): mặc định → `configs/default.yaml` → `~/.laris/config.yaml` →
`.laris/config.yaml` → cài đặt của bạn → biến `LARIS_*` → tham số dòng lệnh.

## 10. Dữ liệu hữu ích để fine-tune sau

- Lượt trả lời tốt (hoàn tất, đúng trích nguồn, không lộ thông tin nhạy cảm) được lưu **chỉ trên máy
  này** ở `artifacts/finetune`: hội thoại, cặp truy vấn–đoạn đúng/sai cho truy hồi, và cặp bản nháp
  bị bác–bản cuối.
- Đánh giá bằng 👍/👎 (web) hoặc `/rate up|down`. Mẫu 👎 bị loại khi xuất.
- Xem: `laris learn stats`; xuất: `laris learn export --kind sft --out đường-dẫn.jsonl`;
  xóa sạch: `laris learn purge --yes`. Tắt thu thập: ô cài đặt hoặc `/learn off`.
- Hệ thống **không** tự huấn luyện gì; dữ liệu chỉ để chủ dự án dùng sau.

## 11. Trí nhớ dự án và bộ não hệ thống

**Vault của dự án (`vault/`)** là thư mục Markdown theo định dạng Obsidian, tự tạo ở lần làm việc đầu
tiên trong codebase của bạn (nạp tài liệu hoặc một lượt hỏi đáp), hoặc tạo tay bằng `laris vault init`.
Sau đó mỗi lần làm việc sẽ thêm ghi chú có liên kết với nhau:

- `Sources/`: mỗi tài liệu đã nạp, kèm khái niệm chính; `Concepts/`: thuật ngữ và nơi nó xuất hiện;
- `Questions/` và `Sessions/`: câu hỏi, câu trả lời đã được xác minh và buổi làm việc, nối tới nguồn đã dẫn;
- `_inbox/`: đề xuất đang chờ bạn duyệt (chưa dùng để trả lời).

Mở thư mục `vault/` bằng Obsidian (không bắt buộc) để xem đồ thị liên kết. Bạn có thể sửa ghi chú: hệ
thống chỉ ghi trong khối `laris:begin ... laris:end`; nếu bạn sửa trong khối đó, hệ thống giữ nguyên phần
bạn sửa và báo xung đột thay vì ghi đè. Lệnh: `laris vault init|check|status`. Tắt ghi tự động bằng
`vault.auto_record: false` trong cấu hình.

**Bộ não hệ thống** là cây hướng dẫn suy luận nội bộ (bảo mật, chỉ đọc). Hệ thống không đọc toàn bộ: nó vào
ở nút gốc, theo liên kết cha → con tới đúng hub rồi mở đúng ghi chú cần. Bạn chỉ thấy tên các ghi chú đã
dùng (dòng `◈ bộ não: ...`), không thấy nội dung. Kiểm tra cấu trúc: `laris brain check`; xem cây tên:
`laris brain tree`; xem một tác vụ đi vào hub nào: `laris brain route "câu hỏi"`.

## 12. Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| "Không gọi được API mô hình" | Chạy `laris model serve` hoặc xóa địa chỉ API để dùng trợ lý tích hợp; `/model` để xem |
| "No documents yet" | Chưa nạp tài liệu: xem mục 2 |
| `[ERROR] protected policy files do not match the integrity lock` | File chính sách bị sửa; chủ dự án chạy `laris harness verify`, rồi `laris harness lock` sau khi duyệt thay đổi |
| PDF không ra chữ | Là PDF scan: cần `tesseract` (OCR `eng+vie`); thử nạp lại dạng ảnh |
| Câu trả lời thiếu mục hoặc cảnh báo chưa dẫn nguồn | Quy trình/kiểm tra nguồn đã yêu cầu viết lại một lần; hỏi lại hẹp hơn hoặc nạp thêm tài liệu |
| "Đã dừng: hết số bước" | Giới hạn tối đa 10 bước mỗi lượt; chia nhỏ yêu cầu hoặc nói "tiếp tục" |

## 13. Tham khảo nhanh lệnh `laris`

```text
laris app ingest|index|search|ask|status|serve     kho tài liệu và giao diện web
laris agent tools|run|chat                         trợ lý trong terminal
laris model serve                                  API mô hình
laris skills list|show|check|lint|add|sync         skill
laris workflows list|show|check                    quy trình
laris harness verify|lock                          toàn vẹn chính sách (chủ dự án)
laris learn stats|export|purge                     dữ liệu fine-tune cục bộ
laris vault init|check|status                      vault Obsidian của dự án
laris brain check|tree|route                       bộ não hệ thống (chủ dự án)
```

Tài liệu kỹ thuật: `docs/development/CLI.md`, `docs/architecture/AGENT_HARNESS.md`, `.laris/README.md`.
