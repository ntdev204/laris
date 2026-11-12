---
document_id: "DOC-DEV-CLIENT-GUIDE-DRAFT-001"
title: "Draft: user guide section for the terminal client"
document_type: "plan"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-12"
updated_at: "2026-11-12"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/development/CLI.md"
decision_references:
  - "ADR-013"
change_summary: "Draft of the Ink, plain and headless guide section for the owner's approval (T82); not applied to the locked guide."
---

# Draft: user guide section for the terminal client (T82)

Status: **draft for owner approval.** The user guide `.laris/help/how-to-use.md` is locked policy
(covered by `integrity.lock`). Nothing here has been applied to it. After approval the owner (or a task
with the owner's approval) merges the section below into the guide, then runs `laris harness verify`
and `laris harness lock`.

Every statement below is exercised by the client acceptance suite (`tests/acceptance`, and
`packaging/npm/test/acceptance.test.tsx` for the Ink front end), except where marked "not tested".
The foundation model is not qualified; the suite uses a scripted model and says nothing about answer
quality.

Proposed text (Vietnamese, same register as the guide), to follow section 1:

---

## 1b. Ba cách chạy `laris`

| Cách | Lệnh | Khi nào dùng |
|---|---|---|
| Giao diện đầy đủ (Ink) | `laris` | Dùng hằng ngày: nhập nhiều dòng, lịch sử, tô màu mã, hộp thoại cho phép có diff, dòng trạng thái |
| Văn bản thuần | `laris --plain` | Terminal đơn giản, ghi lại màn hình, không cần Node |
| Không giao diện | `laris -p "câu hỏi"` | Chạy trong script: một việc rồi thoát |

Cả ba dùng chung một "engine", nên cùng một phiên cho cùng kết quả: cùng lời gọi công cụ, cùng kết
quả công cụ, cùng câu trả lời.

**Giao diện Ink** (cần Node 22 trở lên)

- Enter gửi tin; `\` rồi Enter (hoặc Shift+Enter / Meta+Enter) xuống dòng. Lên/Xuống duyệt lịch sử,
  Ctrl+R tìm trong lịch sử, Tab nhận gợi ý `/lệnh` hoặc `@đường-dẫn`.
- Esc ngắt lượt đang chạy (cuộc trò chuyện đã lưu vẫn hợp lệ). Ctrl+C xóa phần đang gõ, nếu không thì
  ngắt; Ctrl+C lần hai trong 2 giây, hoặc Ctrl+D ở dòng trống, thoát.
- Đang chạy vẫn gõ được tin tiếp theo: nó xếp hàng (`⧗ queued`) và chạy ngay sau lượt hiện tại.
- Khi công cụ cần phép, hộp thoại hiện diff: `y` cho lần này, `a` cho phiên này, `p` cho dự án này,
  `e` ở mọi nơi, `n` hoặc Esc từ chối. Shift+Tab đổi chế độ cho phép.

**Văn bản thuần**: cùng lệnh gạch chéo và cùng câu hỏi cho phép (`y / a / p / e / N`); Ctrl+C ngắt lượt.

**Không giao diện**

```bash
laris -p "tóm tắt tài liệu" --output-format text        # chỉ in câu trả lời
laris -p "..." --output-format json                      # một đối tượng kết quả
laris -p "..." --output-format stream-json               # từng sự kiện E1, mỗi dòng một JSON
echo "nội dung" | laris -p "đọc rồi tóm tắt"
laris -p "..." --allowed-tools "Write(notes/**)"         # cho phép trước, vì không ai trả lời được
```

Không thể hỏi trong chế độ này, nên việc cần phép mà chưa có luật cho phép sẽ bị từ chối (ghi trong
`permission_denials`). Mã thoát: `0` xong; `1` không xong (model hoặc công cụ lỗi); `2` dùng sai (cờ,
phiên không có, chế độ không được phép); `3` dừng vì việc cần thiết không được phép; `130` bị ngắt
(Ctrl+C, phiên đã lưu).

**Hook** (khai báo ở `~/.laris/settings.json`, không bao giờ ở thư mục dự án): một hook
`PreToolUse` thoát với mã 2 sẽ chặn công cụ và lý do hiện ra như kết quả công cụ, ở cả ba cách chạy.

---

## Not covered by this draft

- Windows and macOS terminals (CI runs Linux only; not tested).
- Pasted images and OCR in the Ink front end (unit-tested in the engine; not part of the scripted sessions).
