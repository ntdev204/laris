---
document_id: DOC-PLAN-HUMAN-GOLD-D05-001
title: Proposed Human Gold Protocol
document_type: plan
status: PROPOSED
version: 0.1.0
created_at: '2026-11-11'
updated_at: '2026-11-11'
owner: LARIS Project Owner
reviewers: []
source_of_truth: false
related_documents:
- docs/training/PROJECT_PREREQUISITES.md
- docs/specifications/LARIS_GOLD_SPECIFICATION.md
decision_references:
- ADR-008
change_summary: Adds repository metadata to the existing draft.
---

# D05 — Thiết kế quy trình human gold (PROPOSED)

> **Trạng thái: PROPOSED — chưa có hiệu lực.** Owner đã đánh dấu D05 là `SKIPPED_BY_OWNER`
> (2026-11-11). Tài liệu này là thiết kế để owner xem xét khi muốn mở lại D05. Nó không chỉ
> định người gán, không tạo nhãn nào, không đổi ngưỡng gate và không đổi trạng thái task
> nào. Mọi con số ghi "đề xuất" cần owner duyệt. Nguồn quy tắc nền:
> [LARIS-GOLD](../specifications/LARIS_GOLD_SPECIFICATION.md) §4–§5 và
> [PROJECT_PREREQUISITES](PROJECT_PREREQUISITES.md) §5.

## 1. Vấn đề D05 phải giải quyết

Năm gate hiện chưa thể đo hợp lệ vì thiếu nhãn do người gán:

| Gate | Task bị chặn | Thiếu gì |
| --- | --- | --- |
| G12 retrieval STEM (MRR/nDCG, thắng BM25) | F03 → **F07** | relevance query–passage do người gán |
| Evidence precision/recall ≥ 0,80 | S01A → S05 | span bằng chứng + nhãn SUPPORT/CONTRADICT/INSUFFICIENT |
| CER ≤ 1,5% / layout IoU ≥ 0,88 | O01A → O04 | transcript và box/lớp layout chuẩn |
| Discourse macro F1 ≥ 0,82 | M01A → M03 | vai trò discourse trên đầu ra OCR |
| Specialist reasoning | R02 → R04 | gold reasoning theo topic |

**Hệ quả thực tế:** F07 (task kế tiếp) không thể qualify model 01 nếu thiếu relevance STEM
do người gán. Vì vậy thiết kế chia theo **giai đoạn**, không bắt owner cam kết toàn bộ
cùng lúc.

## 2. Nguyên tắc bất biến

1. Agent không sinh, không "gợi ý trước" nhãn gold. Không dùng đầu ra model làm pre-label
   (tránh anchoring và rò rỉ vòng tròn).
2. Guideline, đơn vị annotation, metric, ngưỡng, quy tắc phân xử và split được **đóng băng
   và băm trước khi gán**, và trước khi xem bất kỳ kết quả model nào.
3. Test split được niêm phong (`FROZEN`) và không dùng để tuning, hard-negative mining hay
   chọn checkpoint.
4. Split theo topic/paper cluster; bài trích dẫn nhau hoặc chung tác giả cùng một phân vùng.
5. Mỗi mục có provenance: `corpus_id`, SHA-256 của văn bản nguồn, định danh annotator nội bộ.
6. Bỏ qua D05 là hoãn quyết định, không phải miễn gate.

## 3. Vai trò (owner điền)

| Vai trò | Số lượng | Yêu cầu | Định danh nội bộ |
| --- | --- | --- | --- |
| Annotator A1 | 1 | chuyên môn STEM; EN, và VI nếu gán phần VI | _owner điền_ |
| Annotator A2 | 1 | như A1, làm độc lập, không thấy nhãn A1 | _owner điền_ |
| Adjudicator | 1 | senior, không gán lượt đầu | _owner điền_ |

Ràng buộc: A1/A2 không trao đổi nhãn trước khi nộp; adjudicator không là A1/A2 của chính
batch đó; ghi rõ giờ khả dụng. Nếu owner tự gán thì ghi rõ và không tự làm adjudicator
trên chính nhãn của mình.

## 4. Đặc tả theo loại gold

Đây là điểm cốt lõi: **không dùng Cohen's κ cho dữ liệu liên tục** (PROJECT_PREREQUISITES §5).

| Loại | Đơn vị | Nhãn | Metric đồng thuận | Ngưỡng đề xuất | Task |
| --- | --- | --- | --- | --- | --- |
| Retrieval relevance | cặp (query, passage) | 0 không liên quan / 1 một phần / 2 trả lời được | weighted κ (bậc hai) | ≥ 0,85 | F03 |
| Evidence / claim | (claim, passage) + span | SUPPORT / CONTRADICT / INSUFFICIENT_EVIDENCE | κ cho nhãn; F1 chồng lấp token cho span | κ ≥ 0,85; span F1 ≥ 0,85 | S01A |
| OCR text | vùng trang | transcript chuẩn hóa | CER giữa A1 và A2 | ≤ 0,5% (thấp hơn gate 1,5% để gold đáng tin) | O01A |
| OCR layout | box + lớp | lớp layout, thứ tự đọc | IoU trung bình của box ghép cặp; κ lớp sau khi ghép IoU ≥ 0,5; Kendall τ thứ tự đọc | IoU ≥ 0,92 (cao hơn gate 0,88); κ ≥ 0,85 | O01A |
| Discourse trên OCR | đoạn/câu | vai trò discourse | κ nhãn; macro F1 giữa hai người | κ ≥ 0,85 | M01A |
| Specialist reasoning | mục theo topic | theo đặc tả R02 | chốt tại R02 | chốt tại R02 | R02 |

**Điểm mơ hồ cần owner xác nhận.** LARIS-GOLD §4 viết "cases with Cohen's κ < 0,85 được phân
xử", nhưng κ là thống kê của cả tập, không phải của từng mẫu. Đề xuất cách đọc:
(a) mọi mẫu hai người bất đồng đều chuyển cho adjudicator; (b) κ của từng batch phải ≥ 0,85,
nếu không thì batch bị trả lại để sửa guideline, không phân xử gượng. Agent không tự chọn
cách đọc này; cần owner chốt.

## 5. Quy trình

1. **Soạn guideline** (agent viết bản nháp, owner duyệt): định nghĩa nhãn, ví dụ biên, quy tắc
   "không chắc thì chọn gì", chuẩn hóa văn bản OCR.
2. **Pilot hiệu chỉnh** (~30 mục/loại, **không tính vào gold**): hai người gán, đo agreement,
   sửa guideline, lặp tối đa 2 vòng. Pilot bị loại khỏi tập đánh giá.
3. **Đóng băng**: băm guideline, danh sách mục và split. Ghi manifest.
4. **Gán độc lập mù** (A1, A2) trên công cụ xuất từ agent, mỗi người một tệp riêng.
5. **Đo agreement** theo bảng §4; nếu dưới ngưỡng thì trả batch.
6. **Phân xử**: adjudicator xử lý mẫu bất đồng; mẫu không giải quyết được gắn
   `UNRESOLVED_CONFLICT` và loại khỏi gate (báo cáo tỉ lệ loại).
7. **Kiểm nguồn tự động**: span khớp từng ký tự với nguồn, băm trùng SHA-256.
8. **Niêm phong test** (20%), ghi digest vào config đánh giá trước khi chạy model.

## 6. Quy mô đề xuất (cần owner xác nhận)

Chưa có số bắt buộc trong gate cho từng loại; con số dưới đây là điểm khởi đầu, nên tính lại
bằng độ rộng khoảng tin cậy mong muốn (±0,05 ở 95% cần khoảng 385 phán đoán độc lập cho một
tỉ lệ).

| Giai đoạn | Nội dung | Quy mô khởi đầu | Mở khóa |
| --- | --- | --- | --- |
| **D05-a** | Retrieval relevance STEM, EN trước | ≥ 200 query, mỗi query chấm top-k gộp từ BM25 + dense (pooling) | G12 → **F07** |
| D05-b | Evidence/NLI khoa học EN/VI | ≥ 400 claim, 80% EN / 20% VI theo LARIS-GOLD | S01A → S05 |
| D05-c | OCR text/layout | ≥ 100 trang từ DocLayNet subset đã chọn | O01A → O04 |
| D05-d | Discourse trên OCR | sau khi O04 có đầu ra OCR | M01A → M03 |

**Pooling cho retrieval:** passage cần chấm lấy từ hợp top-k của BM25 và nhiều hệ thống,
trộn thứ tự và ẩn tên hệ thống, để không thiên vị dense hay BM25. Việc pooling này không
chạy training; chỉ dùng embedding suy luận.

## 7. Phần agent có thể làm sau khi owner duyệt (không cần training)

- Schema JSONL cho từng loại gold, trường provenance và định danh annotator.
- Bộ xuất tệp gán nhãn mù cho A1/A2 và bộ nhập lại.
- Máy tính agreement: weighted κ, κ, span F1, CER, IoU, Kendall τ; có test đơn vị.
- Bộ kiểm nguồn (khớp ký tự, SHA-256), bộ băm/niêm phong split, bộ xác thực manifest.

## 8. Việc owner cần quyết định

- [ ] Có mở lại D05 không, và bắt đầu từ D05-a (khuyến nghị, vì chặn F07) hay toàn bộ?
- [ ] Tên/định danh A1, A2, adjudicator và chuyên môn/ngôn ngữ từng người.
- [ ] Chốt cách đọc ngưỡng κ ở §4 (batch-level + phân xử mọi bất đồng).
- [ ] Duyệt ngưỡng đề xuất cho CER/IoU gold và quy mô §6.
- [ ] Thời gian khả dụng của annotator (ảnh hưởng quy mô thực tế).
- [ ] Nếu **không** mở lại: xác nhận chấp nhận rằng G12 giữ MISSING và model 01 không thể qualify.

## 9. Khi owner duyệt

1. Ghi quyết định owner vào `PROJECT_PREREQUISITES.md` §7–§8 (D05: chuyển khỏi
   `SKIPPED_BY_OWNER`).
2. Chạy lại các kiểm tra (`make check-no-training`) trước khi dùng bộ gold cho đánh giá.

## Phụ lục A — Guideline gán relevance retrieval STEM (DRAFT v0.1)

> **DRAFT chưa đóng băng.** Owner duyệt, chạy pilot, sửa, rồi băm SHA-256 của bản cuối trước
> khi gán thật. Quy trình tổng thể: các mục 1–9 phía trên.
> Công cụ: `src/evaluation/human_gold.py`.

### 1. Nhiệm vụ

Mỗi mục gồm một **câu hỏi (query)** và một **đoạn (passage)**. Bạn chỉ đánh giá đoạn đó với
câu hỏi đó. Không tìm thêm tài liệu, không tra cứu để suy luận ngoài đoạn.

### 2. Thang nhãn

| Nhãn | Ý nghĩa | Dấu hiệu |
| --- | --- | --- |
| **2** | Trả lời được | Đoạn chứa thông tin đủ để người đọc trả lời câu hỏi mà không cần nguồn khác. |
| **1** | Một phần | Đoạn đúng chủ đề và cung cấp một phần câu trả lời, hoặc cần thêm nguồn khác để đủ. |
| **0** | Không liên quan | Khác chủ đề, hoặc chỉ trùng từ khóa mà không giúp trả lời. |

### 3. Quy tắc biên

1. Chỉ trùng thuật ngữ nhưng khác ý nghĩa (ví dụ cùng từ viết tắt, khác lĩnh vực) → **0**.
2. Đoạn nêu câu hỏi nhưng không nêu đáp án → **1** nếu cung cấp bối cảnh trực tiếp cần cho đáp
   án, ngược lại **0**.
3. Đáp án nằm trong đoạn nhưng diễn đạt khác từ hoàn toàn (paraphrase, EN↔VI cùng nghĩa) →
   **2**; không đánh theo mức trùng từ.
4. Đoạn mâu thuẫn với đáp án mà câu hỏi hướng tới nhưng vẫn bàn đúng vấn đề → **2**
   (đoạn trả lời được câu hỏi, dù đáp án khác kỳ vọng). Ghi chú nếu cần.
5. Đoạn có số liệu/đơn vị sai lệch so với câu hỏi (ví dụ khác đơn vị) → **1** nếu có thể quy
   đổi, **0** nếu không.
6. Không chắc giữa hai nhãn → chọn nhãn **thấp hơn**, và ghi chú ngắn. Không để trống.
7. Không dùng điểm của bất kỳ hệ thống nào, không đoán đoạn đến từ hệ thống nào. Thứ tự đoạn
   là ngẫu nhiên.
8. Không trao đổi nhãn với người gán khác trước khi nộp.

### 4. Tệp gán nhãn

Công cụ xuất mỗi người một tệp JSONL: `item_id`, `query`, `passage`, `label` (rỗng). Điền
`label` là 0, 1 hoặc 2 cho **mọi** dòng; không đổi `item_id`; không thêm hay xóa dòng.
Tệp thiếu mục, trùng mục hoặc nhãn ngoài {0,1,2} sẽ bị từ chối.

### 5. Phân xử

Mọi mục hai người bất đồng được chuyển cho adjudicator, người chỉ thấy query, passage và hai
nhãn. Mục không giải quyết được gắn `UNRESOLVED_CONFLICT` và bị loại khỏi gold; tỉ lệ loại được
báo cáo. Batch có weighted κ (bậc hai) dưới ngưỡng bị trả lại để sửa guideline, không phân xử
để vượt ngưỡng.

### 6. Mục cần owner chốt trước khi đóng băng

- Ngưỡng κ (đề xuất 0,85) và cách đọc batch-level.
- Ngôn ngữ phần gán đầu tiên (đề xuất EN trước, VI sau).
- Nguồn STEM và quyền dữ liệu của corpus được gán (xem PROJECT_PREREQUISITES §3).
