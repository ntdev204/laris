# Hướng dẫn sử dụng LARIS

LARIS là trợ lý nghiên cứu chạy cục bộ: nạp tài liệu của bạn vào kho, tìm kiếm có trích nguồn, đọc
file (kể cả PDF scan và ảnh bằng OCR), chạy skill và quy trình (workflow). Văn bản này được soạn sẵn
và in nguyên văn, không qua mô hình. Gõ `/how-to-use` bất cứ lúc nào để xem lại.

> **Lưu ý trạng thái:** mô hình nền chưa được nghiệm thu. Kênh tìm kiếm BM25 là kênh đáng tin;
> tìm kiếm dense và câu trả lời trích xuất còn yếu. Mọi câu trả lời phải có nguồn `[nguồn #hạng]`.

---

## 1. Khởi động nhanh

Chỉ cần lệnh `laris` (giao diện terminal giống Claude Code):

```bash
laris login                    # nhập API key một lần (nhập ẩn, lưu riêng cho bạn)
laris                          # mở phiên mới
laris --resume                 # liệt kê các phiên đã lưu để chọn
laris --resume <mã-phiên>      # mở lại đúng phiên (gõ vài ký tự đầu của mã cũng được)
laris -p "câu hỏi"             # hỏi một câu rồi thoát
laris whoami | laris logout    # xem mã người dùng / xóa khóa đã lưu
```

- **API key quyết định không gian riêng của bạn.** Mỗi key có hội thoại, cài đặt, tệp tải lên và dữ
  liệu riêng; key khác không thấy được. Đổi key là sang một không gian khác. Key không bao giờ được ghi
  vào hội thoại hay nhật ký. Có thể đặt sẵn bằng biến môi trường `LARIS_API_KEY`; nếu chưa có, `laris`
  sẽ hỏi.
- Trong phiên, gõ `/help` để xem lệnh, `/sessions` để xem phiên, `/resume <mã>` để chuyển phiên,
  `/new` để mở phiên mới, Ctrl+D để thoát.
- Chưa có mô hình thật: hệ thống dùng "trợ lý tích hợp" chỉ trích đoạn văn từ tài liệu.

## 2. Nạp tài liệu (kiến thức mới)

| Cách | Lệnh / thao tác |
|---|---|
| Trong chat | Nhờ trợ lý dùng công cụ `ingest_path` (cần bạn đồng ý) |

- Hỗ trợ: txt, md, pdf (có lớp chữ), ảnh và PDF scan (OCR `eng+vie`), jsonl/parquet kiểu BEIR.
- Mỗi lần nạp, hệ thống **không tạo skill**. Thay vào đó nó thêm **tri thức mới theo lĩnh vực** vào bộ
  não: một ghi chú trong `vault/Knowledge/<lĩnh vực>/` (thuật ngữ chính, các khẳng định, phương pháp,
  tập dữ liệu, chỉ số trích từ tài liệu), nối với ghi chú nguồn và hiện cạnh hub lĩnh vực tương ứng
  (xem mục 11). Tài liệu không khớp lĩnh vực nào vào nhóm `General`.
- Nạp lại cùng tài liệu sẽ cập nhật ghi chú, không nhân đôi. Xem trạng thái kho: `/status`.
- Skill chỉ được tạo khi **bạn yêu cầu** (mục 5). Muốn dạy một kiến thức mới bằng lời, nói *"hãy ghi nhớ
  rằng ..."*: trợ lý gọi `save_knowledge` (cần bạn đồng ý) để thêm vào đúng lĩnh vực.

## 3. Hỏi đáp và tìm kiếm

- Trong chat, hỏi bình thường: *"Các tài liệu của tôi nói gì về hiệu suất perovskite?"*.
- Câu trả lời về kho tài liệu luôn được tìm trước rồi mới trả lời, kèm trích nguồn `[nguồn #hạng]`.
  Thiếu trích nguồn, hệ thống yêu cầu viết lại một lần rồi mới cảnh báo.
- Chỉ muốn danh sách đoạn tìm được, không cần câu trả lời: nói rõ *"chỉ tìm, đừng trả lời"*.
- Nhắc tới file bằng đường dẫn trong tin nhắn: trợ lý có thể đọc nó (đường dẫn tương đối).

## 4. Lệnh gạch chéo (`/`)

Gõ trực tiếp trong phiên.

| Lệnh | Tác dụng |
|---|---|
| `/how-to-use` | In hướng dẫn này (không gọi mô hình) |
| `/<tên-skill> <yêu cầu>` | Chạy một skill, ví dụ `/literature-review ...` |
| `/workflow <tên> <yêu cầu>` | Chạy một quy trình có giới hạn chặt |
| `/workflows` | Liệt kê quy trình  |
| `/skills` | Liệt kê skill  |
| `/compact [ghi chú]` | Nén ngữ cảnh ngay |
| `/context` | Xem mức dùng ngữ cảnh và trạng thái tự nén |
| `/rate up\|down` | Đánh giá câu trả lời vừa rồi  |
| `/learn on\|off` | Bật/tắt lưu dữ liệu fine-tune cục bộ  |
| `/write on\|off` | Tự duyệt các thao tác ghi  |
| `/model [URL [TÊN]]` | Xem/đổi API mô hình  |
| `/new`, `/sessions`, `/resume ID` | Quản lý phiên  |
| `/tools`, `/status`, `/exit` | Công cụ, trạng thái, thoát  |

Terminal còn có: `laris agent chat -p "câu hỏi"` (chạy một lần rồi thoát) và `--resume` (nối lại phiên cuối).

## 5. Skill

Skill là cách làm việc có sẵn (ví dụ tổng quan tài liệu, thiết kế thí nghiệm, phản biện).

- Xem: `/skills`.
- Dùng: `/<tên-skill> <yêu cầu>`, hoặc để trợ lý tự gọi khi yêu cầu khớp mô tả.
- Skill chỉ tạo khi bạn yêu cầu; kiến thức mới (sự kiện, định nghĩa, kết quả) thì dùng `save_knowledge`.
- Dạy kỹ năng mới: nói *"tôi muốn thêm một skill ..."* — trợ lý dùng skill `skill-authoring`, soạn bản
  nháp rồi gọi `save_skill` (cần bạn đồng ý). 
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

Chạy: `/workflow grounded-qa <câu hỏi>`.
Chỉ bạn mới khởi chạy được quy trình; mô hình không tự chọn hay mở rộng nó.

## 7. Ngữ cảnh dài và tự động nén

- **Tự nén luôn bật**: khi ngữ cảnh gần đầy (mặc định 80% của 32768 token), hệ thống cắt bớt kết quả
  công cụ cũ rồi tóm tắt các lượt cũ; bản gốc được lưu vào kho lưu trữ. Bạn làm việc liên tục được.
- `/context` cho biết mức dùng ngữ cảnh. `/compact` để nén thủ công.
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
- Chính sách có khóa toàn vẹn; chỉ quản trị viên được thay đổi.

## 9. Cài đặt

Đổi bằng lệnh trong phiên: `/model` (API mô hình), `/write on|off` (tự duyệt thao tác ghi), `/learn
on|off` (lưu dữ liệu fine-tune), `/compact` (nén). Các thiết lập bảo mật không chỉnh được ở đây.

Thứ tự ưu tiên cấu hình (sau thắng): mặc định → `configs/default.yaml` → `~/.laris/config.yaml` →
`.laris/config.yaml` → cài đặt của bạn → biến `LARIS_*` → tham số dòng lệnh.

## 10. Dữ liệu hữu ích để fine-tune sau

- Lượt trả lời tốt (hoàn tất, đúng trích nguồn, không lộ thông tin nhạy cảm) được lưu **chỉ trên máy
  này** ở `artifacts/finetune`: hội thoại, cặp truy vấn–đoạn đúng/sai cho truy hồi, và cặp bản nháp
  bị bác–bản cuối.
- Đánh giá câu trả lời bằng `/rate up|down`. Mẫu 👎 bị loại khi xuất.
- Tắt thu thập: `/learn off`. Xuất hoặc xóa dữ liệu do quản trị viên thực hiện.
- Hệ thống **không** tự huấn luyện gì; dữ liệu chỉ để quản trị viên dùng sau.

## 11. Trí nhớ dự án và bộ não hệ thống

**Vault của dự án (`vault/`)** là thư mục Markdown theo định dạng Obsidian, tự tạo ở lần làm việc đầu
tiên trong codebase của bạn (nạp tài liệu hoặc một lượt hỏi đáp).
Sau đó mỗi lần làm việc sẽ thêm ghi chú có liên kết với nhau:

- `Sources/`: mỗi tài liệu đã nạp, kèm khái niệm chính; `Concepts/`: thuật ngữ và nơi nó xuất hiện;
- `Questions/` và `Sessions/`: câu hỏi, câu trả lời đã được xác minh và buổi làm việc, nối tới nguồn đã dẫn;
- `Knowledge/<lĩnh vực>/`: tri thức mới theo lĩnh vực (từ tài liệu hoặc do bạn dạy), mỗi lĩnh vực có
  một ghi chú danh sách; bộ não hiển thị chúng cạnh hub lĩnh vực khớp, nên suy luận tìm thấy chúng khi
  đi theo cây;
- `_inbox/`: đề xuất đang chờ bạn duyệt (chưa dùng để trả lời).

Mở thư mục `vault/` bằng Obsidian (không bắt buộc) để xem đồ thị liên kết. Bạn có thể sửa ghi chú: hệ
thống chỉ ghi trong khối `laris:begin ... laris:end`; nếu bạn sửa trong khối đó, hệ thống giữ nguyên phần
bạn sửa và báo xung đột thay vì ghi đè.

**Bộ não hệ thống** là cây hướng dẫn suy luận nội bộ (bảo mật, chỉ đọc). Hệ thống không đọc toàn bộ: nó vào
ở ghi chú gốc, theo liên kết cha → con tới đúng hub rồi mở đúng ghi chú cần. Bạn chỉ thấy tên các ghi chú đã
dùng (dòng `◈ bộ não: ...`), không thấy nội dung. Lõi bộ não không bao giờ bị sửa lúc chạy; tri thức mới nằm
trong `vault/Knowledge/` và chỉ được gắn vào cây ở lúc đọc.

## 12. Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| "Không gọi được API mô hình" | Máy chủ mô hình chưa sẵn sàng: dùng `/model` để xem trạng thái, thử lại sau hoặc báo quản trị viên |
| "No documents yet" | Chưa nạp tài liệu: xem mục 2 |
| `[ERROR] protected policy files do not match the integrity lock` | File chính sách bị sửa trên máy chủ; báo quản trị viên |
| PDF không ra chữ | Là PDF scan: cần `tesseract` (OCR `eng+vie`); thử nạp lại dạng ảnh |
| Câu trả lời thiếu mục hoặc cảnh báo chưa dẫn nguồn | Quy trình/kiểm tra nguồn đã yêu cầu viết lại một lần; hỏi lại hẹp hơn hoặc nạp thêm tài liệu |
| "Đã dừng: hết số bước" | Giới hạn tối đa 10 bước mỗi lượt; chia nhỏ yêu cầu hoặc nói "tiếp tục" |

## 13. Tham khảo nhanh lệnh

```text
laris                         mở phiên mới 
laris --resume                chọn một phiên đã lưu
laris --resume <mã-phiên>     mở lại một phiên
laris -p "câu hỏi"            hỏi một câu rồi thoát
/how-to-use /help /sessions /resume /new /skills /workflows /workflow /compact /context
/status /model /write /learn /rate /exit
```
