# Báo cáo thực nghiệm LARIS: tìm khoảng trống nghiên cứu (bản sửa, 2026-11-27)

> Mô hình sinh của hệ thống (Qwen3.5-4B, nhiệt độ 0) **CHƯA ĐƯỢC KIỂM ĐỊNH (NOT QUALIFIED)**. Các số dưới đây là kết
> quả đo một lần trên hai chủ đề, không phải bằng chứng về năng lực khoa học. Chính sách `.laris/gap.toml` 1.1.0. Mọi
> lần chạy chỉ dùng suy luận, không huấn luyện.

Bản này thay báo cáo trước. Lần chạy thử qua chat web về học liên kết chỉ đọc được 3 tài liệu
(`artifacts/gap-eval/web-federated-learning/BAO-CAO.md`), không đủ để đánh giá nên không được đưa vào đây. Toàn bộ thực nghiệm dưới đây
dùng **2 chủ đề, mỗi chủ đề 18 bài**, chạy bằng `laris gap run`. Phần đầu ra tự động và phần do người làm được tách riêng
ở mỗi mục.

## 0. Thiết lập

| Chủ đề | Câu hỏi | Bài | Mốc thời gian | Lần chạy |
|---|---|---|---|---|
| `mpc` | Khoảng trống của MPC/NMPC bám quỹ đạo trên phần cứng nhúng hạn chế tài nguyên | 18 (arXiv, 2021–2026) | ≤2024: 11 bài; 2025–2026: 7 bài | `orig8` (8 bài gốc), `all` (18), `until-2024` (11) |
| `rag-halluc` | Khoảng trống của phát hiện ảo giác trong RAG | 18 (arXiv, 2023–2026) | ≤2024: 6 bài; 2025–2026: 12 bài | `all` (18), `until-2024` (6) |

Thành phần phụ: `ocr-check` (2 bài MPC dựng lại thành PDF chỉ có ảnh, đọc bằng tesseract) và `rag-openalex` (15 tác
phẩm lấy từ OpenAlex, tải được 7 bài mở).

Quy trình gồm 5 bước:

1. Đọc PDF.
2. Trích mục *hạn chế* và *hướng phát triển*, mỗi mục có một câu trích nguyên văn.
3. Gắn khái niệm theo từ vựng trong `topic.toml`. Từ vựng được viết **trước** lần chạy đầu tiên.
4. Sinh ứng viên theo luật G1–G4, lọc rồi xếp hạng.
5. Viết báo cáo và kiểm toán trích dẫn.

Chỉ bước 2 gọi mô hình. Các bước 3–5 là luật tất định.

## 1. Gắn khái niệm: số nhãn và độ chính xác

Đầu ra tự động:

| Lần chạy | Tổng nhãn | method / setting / issue | Nhãn trên mục hạn chế + hướng PT | Khái niệm khác nhau | Bài có nhãn |
|---|---|---|---|---|---|
| MPC – 8 bài | 61 | 15 / 15 / 31 | 22 | 16 | 8/8 |
| MPC – 18 bài | 130 | 29 / 37 / 64 | 38 | 20 | 18/18 |
| RAG – 18 bài | 96 | 18 / 15 / 63 | 46 | 21 | 18/18 |

Một nhãn được gắn khi một từ trong từ vựng xuất hiện nguyên từ trong trường tương ứng của bản trích. Mỗi nhãn ghi kèm
từ khớp (cột "Từ khớp" ở tab *Gắn khái niệm*, ảnh `anh/*-tags.png`).

**Số nhãn gắn sai và precision của bước gắn: chưa có số.** Phần này cần người chấm. Trên web hiện ghi *Đã chấm 0/38*
(MPC) và *0/46* (RAG). Thành viên phụ trách chấm ✓/✗ từng nhãn trên mục hạn chế/hướng phát triển ở tab *Gắn khái
niệm*, rồi bấm *Tính lại số liệu*. Precision = số ✓ / số đã chấm, ghi vào `verdicts.json` và `metrics.json`.

Ví dụ cần chú ý khi chấm, lấy từ chính đầu ra: P15-L1 (RAG) được gắn "Generalization across domains" qua từ
`generalise` và cũng hợp lý. Ngược lại, nhãn "Need for model internals" gắn qua cụm `access to` dễ khớp nhầm, vì
"access to" xuất hiện trong nhiều ngữ cảnh không liên quan.

## 2. Ứng viên khoảng trống: sinh ra → bị loại (lý do) → giữ lại

Đầu ra tự động:

| Lần chạy | Luật | Sinh ra | Bị loại | Lý do loại | Giữ lại |
|---|---|---|---|---|---|
| MPC – 8 bài | G1 | 7 | 5 | đã có bài khác giải quyết: 2; chỉ một bài nêu: 3 | 2 |
| | G2 | 2 | 1 | mâu thuẫn được giải thích: 1 | 1 |
| | G3 | 6 | 2 | hai nhóm bài không chung vấn đề: 2 | 4 |
| | G4 | 1 | 0 | — | 1 |
| | **Tổng** | **16** | **8** | | **8** |
| MPC – 18 bài | G1 | 7 | 6 | đã có bài khác giải quyết: 5; chỉ một bài nêu: 1 | 1 |
| | G2 | 2 | 1 | mâu thuẫn được giải thích: 1 | 1 |
| | G3 | 20 | 10 | hai nhóm bài không chung vấn đề: 10 | 10 |
| | G4 | 1 | 0 | — | 1 |
| | **Tổng** | **30** | **17** | | **13** |
| RAG – 18 bài | G1 | 9 | 7 | đã có bài khác giải quyết: 6; chỉ một bài nêu: 1 | 2 |
| | G2 | 3 | 3 | mâu thuẫn được giải thích: 3 | 0 |
| | G3 | 23 | 15 | hai nhóm bài không chung vấn đề: 15 | 8 |
| | G4 | 1 | 0 | — | 1 |
| | **Tổng** | **36** | **25** | | **11** |

Ý nghĩa các luật:

- **G1:** cùng một vấn đề được ≥ 2 bài nêu là hạn chế hoặc hướng phát triển, và không bài nào khác giải quyết nó.
- **G2:** có mâu thuẫn chưa được giải thích (xem mục 7).
- **G3:** một tổ hợp phương pháp × bối cảnh chưa bài nào thử, trong khi hai nhóm bài chung ít nhất một vấn đề.
- **G4:** bằng chứng cho một phương pháp chỉ đến từ một bài.

Từng ứng viên và lý do bị loại nằm ở tab *Ứng viên & lọc* (`anh/*-candidates.png`).

## 3. Hệ thống so với baseline: số trích dẫn không tồn tại, khẳng định không căn cứ và kết luận "chưa ai làm"

Các nguồn so sánh dùng cùng bài và cùng mô hình Qwen:

- **(a)** hỏi thẳng Qwen, không đưa bài nào;
- **(a2)** đưa thêm trích đoạn các bài, để tham khảo;
- **(b)** RAG thông thường: BM25 với 6 truy vấn, hợp nhất bằng RRF (k = 60), lấy 14 đoạn.

### 3.1 Trên cùng 8 bài (MPC, lần chạy `orig8`)

| Nguồn | Trích dẫn | **Không tồn tại** | Đoạn trích | Trích bịa | Khẳng định | **Không có căn cứ** (không trích nguồn) | **"Chưa ai làm"** | …không giới hạn phạm vi |
|---|---|---|---|---|---|---|---|---|
| Hệ thống LARIS | 164 | **0** | 13 | 0 | 64 | **3** (4,7 %) | **0** | 0 |
| (a) Hỏi thẳng Qwen | 7 | **5** | 10 | 10 | 49 | **49** (100 %) | **0** | 0 |
| (a2) Qwen + trích đoạn | 46 | 0 | 24 | 0 | 46 | 19 (41 %) | 0 | 0 |
| (b) RAG (BM25 + RRF) | 10 | **0** | 10 | 0 | 35 | **24** (69 %) | **1** | 1 |

### 3.2 Trên 18 bài (tham khảo)

| Chủ đề | Nguồn | Trích dẫn | Không tồn tại | Trích bịa | Khẳng định | Không có căn cứ | "Chưa ai làm" |
|---|---|---|---|---|---|---|---|
| MPC | Hệ thống | 418 | 0 | 0 | 146 | 3 | 0 |
| MPC | (a) | 7 | 5 | 10 | 49 | 49 | 0 |
| MPC | (b) RAG | 13 | 0 | 0 | 36 | 34 | 0 |
| RAG | Hệ thống | 256 | 0 | 0 | 103 | 4 | 0 |
| RAG | (a) | 10 | 10 | 11 | 57 | 57 | 1 |
| RAG | (b) RAG | 13 | 0 | 0 | 30 | 28 | 0 |

Chủ đề RAG chỉ có baseline trên 18 bài. Để có bảng 8 bài cho RAG, cần chạy thêm
`laris gap run topics/rag-halluc --label orig8 --only <8 mã bài>`.

Cách đếm:

- **Không tồn tại:** mã bài không có trong danh sách, hoặc tài liệu không khớp tác phẩm nào trên OpenAlex (token-F1 của
  tiêu đề ≥ 0,85 trong 5 kết quả đầu, hoặc cùng họ tác giả và năm). Đây là **cận trên**: chẳng hạn sách thật của
  Rawlings và cộng sự vẫn bị tính là không tìm thấy. Danh sách cần người kiểm lại có ở `artifacts/gap-eval/KET-QUA.md` mục 2.
- **Trích bịa:** đoạn trong ngoặc kép dài ≥ 5 từ mà không có trong bài nào.
- **Không có căn cứ:** câu khẳng định không kèm trích dẫn.
- **"Chưa ai làm":** câu khớp mẫu khẳng định vắng mặt (`absence_patterns`, chẳng hạn "no prior work", "has not been
  studied", "to the best of our knowledge"). "Không giới hạn phạm vi" nghĩa là câu không kèm "among the papers read".

## 4. Đánh giá trích xuất ở mức từng mục

**Đáp án** do một người chú thích khác lập, đọc **toàn văn** từng bài (`fulltext/`), trước khi hệ thống chạy, theo
`gold/GUIDELINE.md`. Mỗi mục có câu trích nguyên văn. Hiện người chú thích là Claude, một mô hình khác Qwen, **chưa phải
thành viên nhóm**. Thành viên 2 cần lập lại độc lập, hoặc ít nhất kiểm một mẫu (mục 10).

**Số mục trong đáp án:**

| Chủ đề | Số bài | Hạn chế | Hướng phát triển | **Tổng** |
|---|---|---|---|---|
| MPC (18 bài) | 18 | 155 | 46 | **201** |
| RAG (18 bài) | 18 | 137 | 46 | **183** |
| MPC – 8 bài | 8 | 51 | 17 | 68 |

**Kết quả:** một mục hệ thống khớp một mục đáp án khi max(token-F1 của đoạn trích, token-F1 của diễn giải) ≥ 0,5, ghép
tham lam một-một.

| Lần chạy | Loại | Mục hệ thống | Mục đáp án | Khớp | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| MPC – 18 bài | **tổng** | 68 | 201 | 39 | **0,57** | **0,19** | 0,29 |
| | hạn chế | 38 | 155 | 11 | 0,29 | 0,07 | 0,11 |
| | hướng PT | 30 | 46 | 21 | 0,70 | 0,46 | 0,55 |
| RAG – 18 bài | **tổng** | 81 | 183 | 62 | **0,77** | **0,34** | 0,47 |
| | hạn chế | 49 | 137 | 33 | 0,67 | 0,24 | 0,35 |
| | hướng PT | 32 | 46 | 25 | 0,78 | 0,54 | 0,64 |
| MPC – 8 bài | tổng | 25 | 68 | 17 | 0,68 | 0,25 | 0,37 |
| MPC – đến 2024 | tổng | 41 | 108 | 24 | 0,59 | 0,22 | 0,32 |
| RAG – đến 2024 | tổng | 31 | 69 | 21 | 0,68 | 0,30 | 0,42 |

Nhận xét: recall của mục *hạn chế* thấp (0,07–0,24). Nguyên nhân chính là bước 2 chỉ đưa vào mô hình các đoạn có dấu
hiệu hạn chế (`limitation_cues`) trong giới hạn 24 000 ký tự, trong khi đáp án lấy hạn chế từ khắp bài. Bảng chi tiết
theo từng bài nằm ở tab *Đánh giá* (`anh/*-eval.png`).

## 5. Chuyên gia chấm khoảng trống (thang 1–5)

Đã chuẩn bị phiếu chấm mù gồm 84 mục tại `/gap/rate` (`anh/phieu-cham.png`): 24 khoảng trống của hệ thống và 60 của
các baseline, xáo trộn và giấu nguồn. Khóa nguồn nằm trong `rating/sheet.json`. Mỗi mục được chấm hai tiêu chí, theo
thang 1–5:

- **mức có căn cứ:** khoảng trống có đúng với các bài không;
- **mức có giá trị:** khoảng trống có đáng nghiên cứu không.

**Chưa có điểm.** Cần 1–2 người am hiểu lĩnh vực chấm (mục 10). Sau khi chấm, chạy
`laris gap score RUN_DIR --ratings FILE --sheet rating/sheet.json` để có điểm trung bình theo nguồn.

## 6. Đánh giá theo mốc thời gian (cắt năm 2024)

Hệ thống chỉ chạy trên các bài ≤ 2024. Sau đó kiểm xem các bài 2025–2026 có mang khái niệm giải quyết từng khoảng trống
hay không:

- **MPC:** 2/5 khoảng trống có bài sau giải quyết. KT3 "Safety and guarantees" được P15 và P18 giải quyết; KT4 "Linear MPC
  trên máy tính nhúng" được P16 giải quyết. Ba khoảng trống còn lại chưa có bài sau.
- **RAG:** 3/4 khoảng trống có bài sau giải quyết. KT1 "Generalization" được P10 và P17 giải quyết; KT2 "Label quality"
  được P7 và P18; KT4 "Fine-tuned detector chỉ một bài" được P14. KT3 "chỉ tiếng Anh" chưa có bài sau.

Đây là tín hiệu tự động và lỏng: bài sau chỉ cần mang khái niệm vấn đề, đây không phải đánh giá của người
(`anh/*-until-2024-eval.png`). Có thể đọc theo hai cách: khoảng trống đã được xác định đúng, vì sau đó có người làm;
hoặc khoảng trống quá chung chung.

## 7. Luật mâu thuẫn G2: cơ chế và xem lại khoảng trống 5

### 7.1 Cách phát hiện r ⊥ r′

1. **r = (p, c, −):** một câu của bài p chứa từ phủ định (`[conflict].negative`, chẳng hạn "not feasible",
   "infeasible", "prohibitive", "computationally expensive", "remains challenging") **và** nêu phương pháp c (khớp từ
   vựng `concepts.method`). Câu được lấy từ trường bài toán/kết quả của bản trích, từ mục hạn chế, hoặc **nguyên văn**
   từ phần tóm tắt/giới thiệu.
2. **r′ = (q, c, +):** bài q ≠ p dùng c (có nhãn c ở trường phương pháp) và trường kết quả có từ khẳng định
   (`[conflict].positive`, chẳng hạn "real-time", "100 Hz", "onboard", "successfully").
3. Mỗi cặp (r, r′) là một ứng viên G2. Ứng viên **được giải thích**, tức không thành khoảng trống, khi gặp một trong ba
   điều kiện:
   - **(a)** p và q không chung khái niệm bối cảnh nào, nên hai bài nói về hai bối cảnh khác nhau;
   - **(b)** chính p báo cáo c chạy được, nên câu phủ định nói về một cấu hình khác;
   - **(c)** không biết bối cảnh của p, nên không so sánh được.
4. Ứng viên không gặp điều kiện nào thì thành khoảng trống G2: "chưa bài nào so sánh hai kết quả trong cùng điều kiện".

Số liệu: MPC có 11 cặp, 10 cặp được giải thích (7 theo (b), 3 theo (a)). RAG có 3 cặp, cả 3 được giải thích (1 theo (a),
2 theo (c)). Toàn bộ các cặp nằm ở tab *Mâu thuẫn (G2)* (`anh/*-conflicts.png`).

### 7.2 Xem lại khoảng trống 5 (MPC – 8 bài: KT5, G2, điểm 4,5; ở lần chạy 18 bài là KT12)

> Among the papers read, P11 say NMPC (online nonlinear optimisation) does not work or is not feasible, while P12 report
> it working in the same setting class; no paper read compares them under the same conditions.

- r (P11, giới thiệu, có trích nguyên văn): "…solving a nonconvex optimal control problem (OCP) at each time step makes
  onboard implementation **infeasible for resource-limited platforms**."
- r′ (P12, kết quả, diễn giải): NMPC đạt "real-time feasibility at 100 Hz".

**Kết luận khi xem lại: đây là mâu thuẫn giả.** Luật coi hai bài là "cùng lớp bối cảnh" vì cả hai cùng mang nhãn
*Aerial vehicle*. Thật ra P11 nói về **vi điều khiển** (nhãn *Microcontroller*), còn P12 chạy trên **máy
tính nhúng** (nhãn *Embedded computer*). Hai lớp phần cứng khác nhau, nên hai câu không mâu thuẫn. Hơn nữa, chính câu
của P11 thừa nhận NMPC đã chạy được trên multirotor cỡ lớn. Điều kiện (a) không bắt được trường hợp này vì nó chỉ đòi
*không chung khái niệm bối cảnh nào*, trong khi chỉ cần chung một khái niệm (loại phương tiện) là cặp bị coi như cùng
bối cảnh.

Đề xuất sửa luật (chưa thực hiện, cần chủ dự án duyệt vì thay đổi chính sách): so sánh bối cảnh **theo từng trục** (nền
tảng phần cứng, loại phương tiện) và coi cặp là được giải thích khi khác nhau ở trục phần cứng. Thêm vào đó, chỉ dùng
mệnh đề phủ định khi nó có cùng chủ ngữ với c, để tránh câu nhượng bộ kiểu "NMPC has been successfully demonstrated…,
but…".

## 8. Trọng số và bảng xếp hạng thực tế

s(g) = w₁·(số bài) + w₂·[G1 ∨ G2] + w₃·(số trích dẫn đã kiểm chứng) − w₄·[chỉ một bài]

**w₁ = 1; w₂ = 2; w₃ = 0,5; w₄ = 1,5.** Các trọng số được đặt tay trước lần chạy đầu, lưu trong `.laris/gap.toml`, và
chỉ dùng để sắp thứ tự trình bày, không đo giá trị khoa học.

**MPC – 18 bài (13 khoảng trống)**

| Hạng | KT | Luật | Bài | w₁·bài | w₂·[G1∨G2] | w₃·trích | −w₄ | s(g) | Tóm tắt |
|---|---|---|---|---|---|---|---|---|---|
| 1 | KT1 | G1 | 4 | 4 | 2 | 3,5 | 0 | **9,5** | Mở rộng sang nền tảng/kịch bản khác: P3, P6, P16, P17 nêu, chưa bài nào giải quyết |
| 2 | KT2 | G3 | 9 | 9 | 0 | 0 | 0 | 9,0 | Approximate MPC × UAV chưa ai thử |
| 3 | KT3 | G3 | 8 | 8 | 0 | 0 | 0 | 8,0 | MPC phân cấp/phân tán × vi điều khiển |
| 4 | KT4 | G3 | 8 | 8 | 0 | 0 | 0 | 8,0 | Learning-based MPC × tàu vũ trụ |
| 5 | KT5 | G3 | 8 | 8 | 0 | 0 | 0 | 8,0 | NMPC × truyền động/công cụ công nghiệp |
| 6 | KT6 | G3 | 8 | 8 | 0 | 0 | 0 | 8,0 | NMPC × tàu vũ trụ |
| 7 | KT7 | G3 | 7 | 7 | 0 | 0 | 0 | 7,0 | Learning-based MPC × ô tô cỡ thật |
| 8 | KT8 | G3 | 6 | 6 | 0 | 0 | 0 | 6,0 | Approximate MPC × máy tính nhúng |
| 9 | KT9 | G3 | 6 | 6 | 0 | 0 | 0 | 6,0 | Sinh mã tự động × tàu vũ trụ |
| 10 | KT10 | G3 | 5 | 5 | 0 | 0 | 0 | 5,0 | Sinh mã tự động × ô tô cỡ thật |
| 11 | KT11 | G3 | 5 | 5 | 0 | 0 | 0 | 5,0 | MPC phân cấp × tàu vũ trụ |
| 12 | KT12 | G2 | 2 | 2 | 2 | 0,5 | 0 | 4,5 | P11 ⊥ P12 về NMPC (mâu thuẫn giả, mục 7.2) |
| 13 | KT13 | G4 | 1 | 1 | 0 | 0 | 1,5 | −0,5 | Approximate MPC chỉ có một bài (P15) |

**RAG – 18 bài (11 khoảng trống)**

| Hạng | KT | Luật | Bài | w₁·bài | w₂·[G1∨G2] | w₃·trích | −w₄ | s(g) | Tóm tắt |
|---|---|---|---|---|---|---|---|---|---|
| 1 | KT1 | G1 | 3 | 3 | 2 | 2,0 | 0 | **7,0** | Chỉ tiếng Anh: P3, P5, P12 nêu, chưa bài nào giải quyết |
| 2 | KT2 | G3 | 7 | 7 | 0 | 0 | 0 | 7,0 | Embedding/similarity × hỏi đáp |
| 3 | KT3 | G3 | 7 | 7 | 0 | 0 | 0 | 7,0 | Bộ phát hiện tinh chỉnh × hỏi đáp |
| 4 | KT4 | G1 | 2 | 2 | 2 | 1,0 | 0 | 5,0 | Ngữ cảnh dài và suy luận phức tạp: P5, P17 |
| 5 | KT5 | G3 | 5 | 5 | 0 | 0 | 0 | 5,0 | Tín hiệu trạng thái trong × LLM đóng (GPT) |
| 6 | KT6 | G3 | 5 | 5 | 0 | 0 | 0 | 5,0 | Bất định/xác suất token × dữ liệu chuyên ngành |
| 7 | KT7 | G3 | 5 | 5 | 0 | 0 | 0 | 5,0 | Bất định/xác suất token × LLM đóng |
| 8 | KT8 | G3 | 3 | 3 | 0 | 0 | 0 | 3,0 | Embedding × dữ liệu chuyên ngành |
| 9 | KT9 | G3 | 3 | 3 | 0 | 0 | 0 | 3,0 | Embedding × LLM đóng |
| 10 | KT10 | G3 | 3 | 3 | 0 | 0 | 0 | 3,0 | Kiểm tra theo đồ thị/thực thể × LLM đóng |
| 11 | KT11 | G4 | 1 | 1 | 0 | 0 | 1,5 | −0,5 | NLI chỉ có một bài (P7) |

Phát biểu đầy đủ bằng tiếng Anh của từng khoảng trống nằm trong phụ lục A và B. Nhận xét: G3 thường đứng cao chỉ vì hai
nhóm bài lớn. Trọng số chưa được hiệu chỉnh theo điểm chuyên gia, nên sau khi có điểm ở mục 5 cần xem lại.

Ở RAG, KT5, KT7, KT9 và KT10 có dạng "phương pháp × LLM đóng". Một số tổ hợp này vô nghĩa về kỹ thuật: tín hiệu trạng
thái trong cần mô hình mở, nên không thể áp dụng cho GPT. Đây là ví dụ cho thấy G3 cần thêm ràng buộc khả thi.

## 9. Ảnh chụp đầu ra thật của hệ thống

Ảnh chụp ngày 2026-11-27 từ web `apps/web` (trang `/gap`), đọc trực tiếp thư mục lần chạy. Tất cả nằm trong `anh/`.

| Ảnh | Nội dung |
|---|---|
| `00-danh-sach-lan-chay.png` | Danh sách các lần chạy |
| `mpc-overview.png`, `rag-halluc-overview.png` | Tổng quan: số liệu từng bước, ứng viên theo luật, kiểm toán trích dẫn |
| `*-papers.png` | Danh sách bài và cách đọc |
| `*-extract.png` | Từng mục hạn chế/hướng PT kèm câu trích và trạng thái kiểm chứng |
| `*-tags.png` | Nhãn khái niệm và từ khớp, có cột chấm ✓/✗ |
| `*-candidates.png` | Ứng viên và lý do bị loại |
| `*-conflicts.png` | Các cặp G2 và kết luận |
| `*-ranking.png` | Bảng xếp hạng có các thành phần của s(g) |
| `*-report.png` | Báo cáo do hệ thống sinh ra (bản Markdown nằm ở phụ lục) |
| `*-baselines.png`, `mpc-orig8-baselines.png` | Câu trả lời của các baseline |
| `*-eval.png`, `*-until-2024-eval.png` | Đánh giá trích xuất và đánh giá theo mốc thời gian |
| `phieu-cham.png` | Phiếu chấm mù 1–5 |

![Hình 1. Danh sách các lần chạy trên web (/gap)](../../../artifacts/gap-eval/bao-cao-v2/anh/00-danh-sach-lan-chay.png)

![Hình 2. MPC – 18 bài, tab Tổng quan: số liệu từng bước, ứng viên theo luật, kiểm toán trích dẫn hệ thống và baseline](../../../artifacts/gap-eval/bao-cao-v2/anh/mpc-overview.png)

![Hình 3. RAG – 18 bài, tab Tổng quan](../../../artifacts/gap-eval/bao-cao-v2/anh/rag-halluc-overview.png)

![Hình 4. MPC – 18 bài, tab Bài báo: danh sách bài, cách đọc, các phần tìm thấy](../../../artifacts/gap-eval/bao-cao-v2/anh/mpc-papers.png)

![Hình 5. MPC – 18 bài, tab Trích xuất: mục hạn chế/hướng phát triển và câu trích đã kiểm chứng (phần đầu)](../../../artifacts/gap-eval/bao-cao-v2/anh/mpc-extract.png)

![Hình 6. RAG – 18 bài, tab Gắn khái niệm: nhãn, từ khớp và cột chấm ✓/✗ (đã chấm 0/46; phần đầu)](../../../artifacts/gap-eval/bao-cao-v2/anh/rag-halluc-tags.png)

![Hình 7. MPC – 18 bài, tab Ứng viên & lọc (phần đầu)](../../../artifacts/gap-eval/bao-cao-v2/anh/mpc-candidates.png)

![Hình 8. MPC – 18 bài, tab Mâu thuẫn (G2): các cặp r ⊥ r′ và kết luận (phần đầu)](../../../artifacts/gap-eval/bao-cao-v2/anh/mpc-conflicts.png)

![Hình 9. MPC – 18 bài, tab Xếp hạng: các thành phần của s(g)](../../../artifacts/gap-eval/bao-cao-v2/anh/mpc-ranking.png)

![Hình 10. RAG – 18 bài, tab Xếp hạng](../../../artifacts/gap-eval/bao-cao-v2/anh/rag-halluc-ranking.png)

![Hình 11. MPC – 18 bài, tab Báo cáo hệ thống (phần đầu; toàn văn ở Phụ lục A)](../../../artifacts/gap-eval/bao-cao-v2/anh/mpc-report.png)

![Hình 12. MPC – 8 bài, tab Baseline: câu trả lời của (a), (a2), (b)](../../../artifacts/gap-eval/bao-cao-v2/anh/mpc-orig8-baselines.png)

![Hình 13. MPC – 18 bài, tab Đánh giá: trích xuất so với đáp án](../../../artifacts/gap-eval/bao-cao-v2/anh/mpc-eval.png)

![Hình 14. RAG – 18 bài, tab Đánh giá](../../../artifacts/gap-eval/bao-cao-v2/anh/rag-halluc-eval.png)

![Hình 15. MPC – đến 2024, đánh giá theo mốc thời gian](../../../artifacts/gap-eval/bao-cao-v2/anh/mpc-until-2024-eval.png)

![Hình 16. Phiếu chấm mù thang 1–5 (/gap/rate)](../../../artifacts/gap-eval/bao-cao-v2/anh/phieu-cham.png)

## 10. Phân công công việc

Tên thành viên để trống, nhóm tự điền.

| Thành viên | Phụ trách | Đầu ra | Trạng thái |
|---|---|---|---|
| **Thành viên 1** (chạy hệ thống) | Chọn bài và viết `topic.toml` trước khi chạy; chạy `laris gap run/collect/score` cho cả hai chủ đề (8 bài, 18 bài, ≤2024, OCR, OpenAlex); thu số liệu, ảnh chụp và báo cáo gốc; tổng hợp báo cáo này | `topics/*/runs/*`, mục 0–3, 6–9 và phụ lục | Xong |
| **Thành viên 2** (đáp án độc lập) | Đọc toàn văn 36 bài và lập đáp án hạn chế/hướng PT theo `gold/GUIDELINE.md` mà không xem đầu ra hệ thống; nếu không kịp thì kiểm một mẫu ≥ 20 % của đáp án hiện có; chấm ✓/✗ 84 nhãn ở tab *Gắn khái niệm* | `gold/*`, `verdicts.json`, precision của bước gắn (mục 1, 4) | **Chưa làm** (đáp án hiện tại do Claude lập) |
| **Thành viên 3** (chuyên gia, điều phối chấm) | Mời 1–2 người am hiểu MPC và RAG chấm phiếu mù 84 mục theo thang 1–5; tự chấm nếu am hiểu; xem lại G2 (mục 7.2) và đề xuất sửa luật | `ratings.json`, điểm trung bình theo nguồn (mục 5) | **Chưa làm** |

## 11. Hạn chế của chính thực nghiệm

- Chỉ có hai chủ đề, mỗi chủ đề 18 bài, và mỗi cấu hình chạy một lần.
- Đáp án chưa do thành viên nhóm lập. Precision của bước gắn và điểm chuyên gia chưa có.
- Số trích dẫn "không tồn tại" là cận trên. Baseline 8 bài mới có cho MPC.
- Đánh giá theo mốc thời gian là tín hiệu tự động, chưa có người kiểm.
- Mô hình chưa được kiểm định.

---

# Phụ lục: báo cáo gốc do hệ thống sinh ra

Ba phụ lục dưới đây được chép nguyên văn từ `topics/<chủ đề>/runs/<lần chạy>/report.md`, không sửa gì. Tiêu đề được hạ
một cấp.

## Phụ lục A. MPC – 18 bài (`topics/mpc/runs/all/report.md`)

### Research gaps: Model predictive control for trajectory tracking on resource-constrained embedded hardware

Papers given: 18; records parsed: 18. Every gap below is a gap among the papers read, not a claim about the whole literature.

#### Paper register

| Id | Title | Year | Read by | Sections found |
|---|---|---|---|---|
| P1 | Embedded Model Predictive Controller on Low-Cost Low-End Microcontroller for Electrical Drives | 2021 | pdftotext | front, abstract, introduction, results, references, conclusion |
| P2 | Development, Implementation, and Experimental Outdoor Evaluation of Quadcopter Controllers for Computationally Limited Embedded Systems | 2021 | pdftotext | front, introduction, method, experiments, method, method, method, method, method, method, experiments, results, discussion, conclusion, references, method |
| P3 | Real-time Nonlinear MPC Strategy with Full Vehicle Validation for Autonomous Driving | 2021 | pdftotext | front, abstract, introduction, related, experiments, conclusion, references |
| P4 | Real-time Neural-MPC: Deep Learning Model Predictive Control for Quadrotors and Agile Robotic Platforms | 2022 | pdftotext | front, abstract, introduction, related, experiments, results, experiments, conclusion, references |
| P5 | Toward smart composites: small-scale, untethered prediction and control for soft sensor/actuator systems | 2022 | pdftotext | front, introduction, related, results, related, references |
| P6 | Aggressive Trajectory Tracking for Nano Quadrotors Using Embedded Nonlinear Model Predictive Control | 2023 | pdftotext | front, abstract, introduction, related, method, results, future_work, references |
| P7 | Code Generation and Conic Constraints for Model-Predictive Control on Microcontrollers with Conic-TinyMPC | 2024 | pdftotext | front, abstract, introduction, related, experiments, future_work, references |
| P8 | Embedded Hierarchical MPC for Autonomous Navigation | 2024 | pdftotext | front, abstract, appendix, introduction, method, method, method, method, results, future_work, references |
| P9 | Model Predictive Control For Multiple Castaway Tracking with an Autonomous Aerial Agent | 2024 | pdftotext | front, abstract, introduction, related, method, experiments, future_work, references |
| P10 | Cooperative distributed model predictive control for embedded systems: Experiments with hovercraft formations | 2024 | pdftotext | front, abstract, introduction, method, experiments, conclusion, references |
| P11 | Tiny Learning-Based MPC for Multirotors: Solver-Aware Learning for Efficient Embedded Predictive Control | 2024 | pdftotext | front, abstract, introduction, method, related, method, experiments, conclusion, references |
| P12 | LoL-NMPC: Low-Level Dynamics Integration in Nonlinear Model Predictive Control for Unmanned Aerial Vehicles | 2025 | pdftotext | front, abstract, appendix, introduction, related, method, method, results, conclusion, references |
| P13 | AutoMPC: A Code Generator for MPC-based Automated Driving | 2025 | pdftotext | front, abstract, introduction, method, method, method, method, method, references |
| P14 | Neural NMPC through Signed Distance Field Encoding for Collision Avoidance | 2025 | pdftotext | front, introduction, related, experiments, references |
| P15 | Learning-based Approximate Model Predictive Control for an Impact Wrench Tool | 2025 | pdftotext | front, abstract, introduction, related, method, results, conclusion, references |
| P16 | Lightweight Model Predictive Control for Spacecraft Rendezvous Attitude Synchronization | 2026 | pdftotext | front, abstract, related, introduction, method, results, conclusion, references, method |
| P17 | Real-time Gaussian Process based Approximate Model Predictive Trajectory Tracking Control for Autonomous Vehicles | 2026 | pdftotext | front, abstract, introduction, method, experiments, conclusion, references |
| P18 | Real-Time Model Predictive Control Algorithms for Autonomous Spacecraft Guidance | 2026 | pdftotext | front, introduction, method, results, method, conclusion, introduction, references |

#### What is known

**method**

- Approximate MPC (learned control law) (P15)
- Automatic code generation for MPC (P1, P13, P5, P7)
- Hierarchical / distributed MPC (P10, P14, P8)
- Learning-based MPC (GP, neural network) (P11, P14, P15, P17, P4, P5)
- Linear / convex MPC (QP, ADMM) (P1, P16, P3, P7)
- NMPC (online nonlinear optimisation) (P12, P13, P14, P3, P6, P8)

**setting**

- Aerial vehicle (quadrotor, UAV) (P11, P12, P14, P2, P4, P7, P8, P9)
- Embedded computer (Raspberry Pi, onboard computer) (P12, P16, P17, P5, P8)
- Full-size road vehicle (P3)
- Industrial drive, tool or engine (P15, P5)
- Microcontroller (P1, P11, P15, P6, P7)
- Small ground or marine robot (P10)
- Spacecraft (P16, P18)

**issue**

- Computational cost and real-time (P1, P16, P2, P3)
- Extension to other platforms and scenarios (P16, P17, P3, P6)
- Multi-agent systems (P16, P6, P9)
- Online learning and adaptation (P11, P15, P17, P6)
- Real-world validation (P8)
- Robustness to model mismatch and disturbances (P11, P13, P14, P16, P17, P18, P2, P7, P8)
- Safety and guarantees (P14, P17, P18, P6, P8)

#### Conflicts

- NMPC (online nonlinear optimisation) — P11 [P11:introduction]: "Nonlinear MPC (NMPC) has been successfully demonstrated on fullscale multirotors for agile flight (Hanover et al., 2022; Tzoumanikas et al., 2020; Bicego et al., 2020; Nan et al., 2022), but solving a nonconvex optimal control problem (OCP) at each time step makes onboard implementation infeasible for resource-limited platforms." — vs P12 [P12:result, paraphrase]: The proposed method achieves an average 21.97% reduction in trajectory tracking error compared to standard methods while maintaining real-time feasibility at 100 Hz. — not explained: both on Aerial vehicle (quadrotor, UAV)
- NMPC (online nonlinear optimisation) — P11 [P11:introduction]: "Nonlinear MPC (NMPC) has been successfully demonstrated on fullscale multirotors for agile flight (Hanover et al., 2022; Tzoumanikas et al., 2020; Bicego et al., 2020; Nan et al., 2022), but solving a nonconvex optimal control problem (OCP) at each time step makes onboard implementation infeasible for resource-limited platforms." — vs P3 [P3:result, paraphrase]: The NMPC controller was successfully deployed at 25Hz for trajectory control, demonstrating capabilities in collision avoidance, automatic collision avoidance, and adaptive cruise control (ACC) at speeds ranging from 10kph to 60kph. — (a) different settings: P11 on Aerial vehicle (quadrotor, UAV), Microcontroller, P3 on Full-size road vehicle
- Learning-based MPC (GP, neural network) — P11 [P11:introduction]: "Despite demonstrated benefits, GP MPC remains computationally expensive, requiring GP inference along the prediction horizon and solving a nonconvex OCP at each time step." — vs P17 [P17:result, paraphrase]: The Gaussian process-based controller achieves a computational speedup of over five times while achieving similar closed-loop tracking performance compared to the real-time iterations implementation. — (b) P11 itself reports Learning-based MPC (GP, neural network) working, so its negative sentence is about another configuration
- Learning-based MPC (GP, neural network) — P11 [P11:introduction]: "Despite demonstrated benefits, GP MPC remains computationally expensive, requiring GP inference along the prediction horizon and solving a nonconvex OCP at each time step." — vs P4 [P4:result, paraphrase]: The framework enables the use of models with over 4000 times larger parametric capacity within a 50Hz real-time window and reduces positional tracking error by up to 82% compared to state-of-the-art MPC approaches. — (b) P11 itself reports Learning-based MPC (GP, neural network) working, so its negative sentence is about another configuration
- Learning-based MPC (GP, neural network) — P11 [P11:introduction]: "Despite demonstrated benefits, GP MPC remains computationally expensive, requiring GP inference along the prediction horizon and solving a nonconvex OCP at each time step." — vs P5 [P5:result, paraphrase]: The approach achieves high-bandwidth tracking (≥ 120 Hz) with a memory footprint of ≤ 6.4% of flash memory, path following errors of ≤ 2mm (tendon) and ≤ 1mm (HASEL), and a mean power consumption of 45.4 mW. — (b) P11 itself reports Learning-based MPC (GP, neural network) working, so its negative sentence is about another configuration
- NMPC (online nonlinear optimisation) — P12 [P12:introduction]: "In contrast, predictive controllers like NMPC [14] leverage modelling of the dynamics to track even partially infeasible trajectories, such as those presented in [10]." — vs P3 [P3:result, paraphrase]: The NMPC controller was successfully deployed at 25Hz for trajectory control, demonstrating capabilities in collision avoidance, automatic collision avoidance, and adaptive cruise control (ACC) at speeds ranging from 10kph to 60kph. — (b) P12 itself reports NMPC (online nonlinear optimisation) working, so its negative sentence is about another configuration
- NMPC (online nonlinear optimisation) — P15 [P15:abstract]: "However, the computational burden of solving the nonlinear optimization problem at each control step is prohibitive for the embedded processor in the power tool, which must execute control updates at 1 kHz." — vs P12 [P12:result, paraphrase]: The proposed method achieves an average 21.97% reduction in trajectory tracking error compared to standard methods while maintaining real-time feasibility at 100 Hz. — (a) different settings: P15 on Industrial drive, tool or engine, Microcontroller, P12 on Aerial vehicle (quadrotor, UAV), Embedded computer (Raspberry Pi, onboard computer)
- NMPC (online nonlinear optimisation) — P15 [P15:abstract]: "However, the computational burden of solving the nonlinear optimization problem at each control step is prohibitive for the embedded processor in the power tool, which must execute control updates at 1 kHz." — vs P3 [P3:result, paraphrase]: The NMPC controller was successfully deployed at 25Hz for trajectory control, demonstrating capabilities in collision avoidance, automatic collision avoidance, and adaptive cruise control (ACC) at speeds ranging from 10kph to 60kph. — (a) different settings: P15 on Industrial drive, tool or engine, Microcontroller, P3 on Full-size road vehicle
- Learning-based MPC (GP, neural network) — P4 [P4:abstract]: "Our experiments, performed in simulation and the real world onboard a highly agile quadrotor platform, demonstrate the capabilities of the described system to run learned models with, previously infeasible, large modeling capacity using gradient-based online optimization MPC." — vs P11 [P11:result, paraphrase]: The method achieves 100 Hz control and demonstrates a 43% average improvement in tracking performance over existing embedded MPC methods under model uncertainty. — (b) P4 itself reports Learning-based MPC (GP, neural network) working, so its negative sentence is about another configuration
- Learning-based MPC (GP, neural network) — P4 [P4:abstract]: "Our experiments, performed in simulation and the real world onboard a highly agile quadrotor platform, demonstrate the capabilities of the described system to run learned models with, previously infeasible, large modeling capacity using gradient-based online optimization MPC." — vs P17 [P17:result, paraphrase]: The Gaussian process-based controller achieves a computational speedup of over five times while achieving similar closed-loop tracking performance compared to the real-time iterations implementation. — (b) P4 itself reports Learning-based MPC (GP, neural network) working, so its negative sentence is about another configuration
- Learning-based MPC (GP, neural network) — P4 [P4:abstract]: "Our experiments, performed in simulation and the real world onboard a highly agile quadrotor platform, demonstrate the capabilities of the described system to run learned models with, previously infeasible, large modeling capacity using gradient-based online optimization MPC." — vs P5 [P5:result, paraphrase]: The approach achieves high-bandwidth tracking (≥ 120 Hz) with a memory footprint of ≤ 6.4% of flash memory, path following errors of ≤ 2mm (tendon) and ≤ 1mm (HASEL), and a mean power consumption of 45.4 mW. — (b) P4 itself reports Learning-based MPC (GP, neural network) working, so its negative sentence is about another configuration

#### Research gaps

##### KT1 (G1, score 9.5)

Among the papers read, the issue **Extension to other platforms and scenarios** is stated as a limitation or future work by 4 papers (P16, P17, P3, P6), and no other paper read addresses it.

- P3 [P3-L2; conclusion] ✓ found in the paper: "Trajectory control is one relevant use case of the applicability of realtime NMPC, however, other use cases could be tested using the same XiL development framework"
- P3 [P3-F1; conclusion] ✓ found in the paper: "applications can be extended to more complex OCP or other optimization based formulations such as optimal planning"
- P6 [P6-L1; future_work] ✓ found in the paper: "Some of the future work directions are the extension to multiple nano-quadrotor crazyflies2.1"
- P6 [P6-F1; future_work] ✓ found in the paper: "Some of the future work directions are the extension to multiple nano-quadrotor crazyflies2.1"
- P16 [P16-F2; conclusion] ✓ found in the paper: "To improve disturbance resilience, it could be extended to a robust MPC formulation"
- P16 [P16-F4; conclusion] ✓ found in the paper: "The controllers could also be extended to the affine group SE(3) including translational motion as in [22], e.g., for close proximity rendezvous with 6 degrees of freedom."
- P17 [P17-L1; abstract] ✓ found in the paper: "the large amount of training data required for successful generalization across distinct reference trajectories poses a significant challenge"

##### KT2 (G3, score 9)

Among the papers read, Approximate MPC (learned control law) (P15) and Aerial vehicle (quadrotor, UAV) (P11, P12, P14, P2, P4, P7, P8, P9) both occur, but no paper read uses Approximate MPC (learned control law) on Aerial vehicle (quadrotor, UAV); both groups state the issue Online learning and adaptation.

- P2 [P2:problem; problem] paraphrase, no verified quotation: Aerial vehicle (quadrotor, UAV) `quadcopter`
- P2 [P2:setting; setting] paraphrase, no verified quotation: Aerial vehicle (quadrotor, UAV) `quadcopter`
- P4 [P4:setting; setting] paraphrase, no verified quotation: Aerial vehicle (quadrotor, UAV) `quadrotor`
- P7 [P7:setting; setting] paraphrase, no verified quotation: Aerial vehicle (quadrotor, UAV) `quadrotor`
- P8 [P8:setting; setting] paraphrase, no verified quotation: Aerial vehicle (quadrotor, UAV) `quadrotor`
- P9 [P9:problem; problem] paraphrase, no verified quotation: Aerial vehicle (quadrotor, UAV) `uav`
- P9 [P9:setting; setting] paraphrase, no verified quotation: Aerial vehicle (quadrotor, UAV) `uav`
- P9 [P9:result; result] paraphrase, no verified quotation: Aerial vehicle (quadrotor, UAV) `uav`

##### KT3 (G3, score 8)

Among the papers read, Hierarchical / distributed MPC (P10, P14, P8) and Microcontroller (P1, P11, P15, P6, P7) both occur, but no paper read uses Hierarchical / distributed MPC on Microcontroller; both groups state the issue Robustness to model mismatch and disturbances, Safety and guarantees.

- P1 [P1:problem; problem] paraphrase, no verified quotation: Microcontroller `microcontrollers`
- P1 [P1:setting; setting] paraphrase, no verified quotation: Microcontroller `microcontroller`
- P6 [P6:setting; setting] paraphrase, no verified quotation: Microcontroller `crazyflie`
- P7 [P7:problem; problem] paraphrase, no verified quotation: Microcontroller `microcontrollers`
- P7 [P7:setting; setting] paraphrase, no verified quotation: Microcontroller `microcontroller`
- P8 [P8:method; method] paraphrase, no verified quotation: Hierarchical / distributed MPC `hierarchical`
- P10 [P10:problem; problem] paraphrase, no verified quotation: Hierarchical / distributed MPC `distributed`
- P11 [P11:setting; setting] paraphrase, no verified quotation: Microcontroller `microcontroller`

##### KT4 (G3, score 8)

Among the papers read, Learning-based MPC (GP, neural network) (P11, P14, P15, P17, P4, P5) and Spacecraft (P16, P18) both occur, but no paper read uses Learning-based MPC (GP, neural network) on Spacecraft; both groups state the issue Extension to other platforms and scenarios, Robustness to model mismatch and disturbances, Safety and guarantees.

- P4 [P4:problem; problem] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `neural network`
- P4 [P4:method; method] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `neural network`
- P5 [P5:problem; problem] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `neural`
- P5 [P5:method; method] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `neural`
- P11 [P11:method; method] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `gaussian process`
- P14 [P14:method; method] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `neural`
- P15 [P15:method; method] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `gaussian process`
- P16 [P16:problem; problem] paraphrase, no verified quotation: Spacecraft `spacecraft`

##### KT5 (G3, score 8)

Among the papers read, NMPC (online nonlinear optimisation) (P12, P13, P14, P3, P6, P8) and Industrial drive, tool or engine (P15, P5) both occur, but no paper read uses NMPC (online nonlinear optimisation) on Industrial drive, tool or engine; both groups state the issue Online learning and adaptation.

- P3 [P3:problem; problem] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nonlinear model predictive control`
- P3 [P3:method; method] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `sequential quadratic programming`
- P5 [P5:problem; problem] paraphrase, no verified quotation: Industrial drive, tool or engine `actuator`
- P6 [P6:method; method] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nonlinear model predictive control`
- P8 [P8:problem; problem] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nonlinear model predictive control`
- P12 [P12:problem; problem] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nmpc`
- P12 [P12:method; method] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nmpc`
- P13 [P13:method; method] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nonlinear mpc`

##### KT6 (G3, score 8)

Among the papers read, NMPC (online nonlinear optimisation) (P12, P13, P14, P3, P6, P8) and Spacecraft (P16, P18) both occur, but no paper read uses NMPC (online nonlinear optimisation) on Spacecraft; both groups state the issue Computational cost and real-time, Extension to other platforms and scenarios, Multi-agent systems, Robustness to model mismatch and disturbances, Safety and guarantees.

- P3 [P3:problem; problem] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nonlinear model predictive control`
- P3 [P3:method; method] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `sequential quadratic programming`
- P6 [P6:method; method] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nonlinear model predictive control`
- P8 [P8:problem; problem] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nonlinear model predictive control`
- P12 [P12:problem; problem] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nmpc`
- P12 [P12:method; method] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nmpc`
- P13 [P13:method; method] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nonlinear mpc`
- P14 [P14:method; method] paraphrase, no verified quotation: NMPC (online nonlinear optimisation) `nonlinear model predictive control`

##### KT7 (G3, score 7)

Among the papers read, Learning-based MPC (GP, neural network) (P11, P14, P15, P17, P4, P5) and Full-size road vehicle (P3) both occur, but no paper read uses Learning-based MPC (GP, neural network) on Full-size road vehicle; both groups state the issue Extension to other platforms and scenarios.

- P3 [P3:problem; problem] paraphrase, no verified quotation: Full-size road vehicle `autonomous driving`
- P3 [P3:setting; setting] paraphrase, no verified quotation: Full-size road vehicle `ford`
- P4 [P4:problem; problem] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `neural network`
- P4 [P4:method; method] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `neural network`
- P5 [P5:problem; problem] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `neural`
- P5 [P5:method; method] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `neural`
- P11 [P11:method; method] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `gaussian process`
- P14 [P14:method; method] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `neural`

##### KT8 (G3, score 6)

Among the papers read, Approximate MPC (learned control law) (P15) and Embedded computer (Raspberry Pi, onboard computer) (P12, P16, P17, P5, P8) both occur, but no paper read uses Approximate MPC (learned control law) on Embedded computer (Raspberry Pi, onboard computer); both groups state the issue Online learning and adaptation.

- P5 [P5:setting; setting] paraphrase, no verified quotation: Embedded computer (Raspberry Pi, onboard computer) `arm`
- P8 [P8:setting; setting] paraphrase, no verified quotation: Embedded computer (Raspberry Pi, onboard computer) `embedded computer`
- P12 [P12:setting; setting] paraphrase, no verified quotation: Embedded computer (Raspberry Pi, onboard computer) `flight computer`
- P15 [P15:method; method] paraphrase, no verified quotation: Approximate MPC (learned control law) `policy approximation`
- P16 [P16:setting; setting] paraphrase, no verified quotation: Embedded computer (Raspberry Pi, onboard computer) `arm`
- P17 [P17:setting; setting] paraphrase, no verified quotation: Embedded computer (Raspberry Pi, onboard computer) `raspberry pi`

##### KT9 (G3, score 6)

Among the papers read, Automatic code generation for MPC (P1, P13, P5, P7) and Spacecraft (P16, P18) both occur, but no paper read uses Automatic code generation for MPC on Spacecraft; both groups state the issue Computational cost and real-time, Robustness to model mismatch and disturbances.

- P1 [P1:method; method] paraphrase, no verified quotation: Automatic code generation for MPC `c code`
- P5 [P5:method; method] paraphrase, no verified quotation: Automatic code generation for MPC `c code`
- P7 [P7:method; method] paraphrase, no verified quotation: Automatic code generation for MPC `code generation`
- P13 [P13:method; method] paraphrase, no verified quotation: Automatic code generation for MPC `c code`
- P16 [P16:problem; problem] paraphrase, no verified quotation: Spacecraft `spacecraft`
- P16 [P16:setting; setting] paraphrase, no verified quotation: Spacecraft `space`
- P18 [P18:problem; problem] paraphrase, no verified quotation: Spacecraft `spacecraft`
- P18 [P18:setting; setting] paraphrase, no verified quotation: Spacecraft `spacecraft`

##### KT10 (G3, score 5)

Among the papers read, Automatic code generation for MPC (P1, P13, P5, P7) and Full-size road vehicle (P3) both occur, but no paper read uses Automatic code generation for MPC on Full-size road vehicle; both groups state the issue Computational cost and real-time.

- P1 [P1:method; method] paraphrase, no verified quotation: Automatic code generation for MPC `c code`
- P3 [P3:problem; problem] paraphrase, no verified quotation: Full-size road vehicle `autonomous driving`
- P3 [P3:setting; setting] paraphrase, no verified quotation: Full-size road vehicle `ford`
- P5 [P5:method; method] paraphrase, no verified quotation: Automatic code generation for MPC `c code`
- P7 [P7:method; method] paraphrase, no verified quotation: Automatic code generation for MPC `code generation`
- P13 [P13:method; method] paraphrase, no verified quotation: Automatic code generation for MPC `c code`

##### KT11 (G3, score 5)

Among the papers read, Hierarchical / distributed MPC (P10, P14, P8) and Spacecraft (P16, P18) both occur, but no paper read uses Hierarchical / distributed MPC on Spacecraft; both groups state the issue Robustness to model mismatch and disturbances, Safety and guarantees.

- P8 [P8:method; method] paraphrase, no verified quotation: Hierarchical / distributed MPC `hierarchical`
- P10 [P10:problem; problem] paraphrase, no verified quotation: Hierarchical / distributed MPC `distributed`
- P14 [P14:method; method] paraphrase, no verified quotation: Hierarchical / distributed MPC `multi-layer`
- P16 [P16:problem; problem] paraphrase, no verified quotation: Spacecraft `spacecraft`
- P16 [P16:setting; setting] paraphrase, no verified quotation: Spacecraft `space`
- P18 [P18:problem; problem] paraphrase, no verified quotation: Spacecraft `spacecraft`
- P18 [P18:setting; setting] paraphrase, no verified quotation: Spacecraft `spacecraft`

##### KT12 (G2, score 4.5)

Among the papers read, P11 say NMPC (online nonlinear optimisation) does not work or is not feasible, while P12 report it working in the same setting class; no paper read compares them under the same conditions.

- P11 [P11:introduction; introduction] ✓ found in the paper: "Nonlinear MPC (NMPC) has been successfully demonstrated on fullscale multirotors for agile flight (Hanover et al., 2022; Tzoumanikas et al., 2020; Bicego et al., 2020; Nan et al., 2022), but solving a nonconvex optimal control problem (OCP) at each time step makes onboard implementation infeasible for resource-limited platforms."
- P12 [P12:result; field] paraphrase, no verified quotation: The proposed method achieves an average 21.97% reduction in trajectory tracking error compared to standard methods while maintaining real-time feasibility at 100 Hz.

##### KT13 (G4, score -0.5)

Among the papers read, the evidence for Approximate MPC (learned control law) comes from one paper only (P15); it is not repeated on another setting.

- P15 [P15:method; method] paraphrase, no verified quotation: Approximate MPC (learned control law) `policy approximation`

#### Not read

Every paper given was read and extracted.


#### Sources

- [P1] Embedded Model Predictive Controller on Low-Cost Low-End Microcontroller for Electrical Drives
- [P2] Development, Implementation, and Experimental Outdoor Evaluation of Quadcopter Controllers for Computationally Limited Embedded Systems
- [P3] Real-time Nonlinear MPC Strategy with Full Vehicle Validation for Autonomous Driving
- [P4] Real-time Neural-MPC: Deep Learning Model Predictive Control for Quadrotors and Agile Robotic Platforms
- [P5] Toward smart composites: small-scale, untethered prediction and control for soft sensor/actuator systems
- [P6] Aggressive Trajectory Tracking for Nano Quadrotors Using Embedded Nonlinear Model Predictive Control
- [P7] Code Generation and Conic Constraints for Model-Predictive Control on Microcontrollers with Conic-TinyMPC
- [P8] Embedded Hierarchical MPC for Autonomous Navigation
- [P9] Model Predictive Control For Multiple Castaway Tracking with an Autonomous Aerial Agent
- [P10] Cooperative distributed model predictive control for embedded systems: Experiments with hovercraft formations
- [P11] Tiny Learning-Based MPC for Multirotors: Solver-Aware Learning for Efficient Embedded Predictive Control
- [P12] LoL-NMPC: Low-Level Dynamics Integration in Nonlinear Model Predictive Control for Unmanned Aerial Vehicles
- [P13] AutoMPC: A Code Generator for MPC-based Automated Driving
- [P14] Neural NMPC through Signed Distance Field Encoding for Collision Avoidance
- [P15] Learning-based Approximate Model Predictive Control for an Impact Wrench Tool
- [P16] Lightweight Model Predictive Control for Spacecraft Rendezvous Attitude Synchronization
- [P17] Real-time Gaussian Process based Approximate Model Predictive Trajectory Tracking Control for Autonomous Vehicles
- [P18] Real-Time Model Predictive Control Algorithms for Autonomous Spacecraft Guidance

## Phụ lục B. RAG – 18 bài (`topics/rag-halluc/runs/all/report.md`)

### Research gaps: Hallucination detection in retrieval-augmented generation

Papers given: 18; records parsed: 18. Every gap below is a gap among the papers read, not a claim about the whole literature.

#### Paper register

| Id | Title | Year | Read by | Sections found |
|---|---|---|---|---|
| P1 | DelucionQA: Detecting Hallucinations in Domain-specific Question Answering | 2023 | pdftotext | front, introduction, related, results, limitations, references, conclusion |
| P2 | RAGTruth: A Hallucination Corpus for Developing Trustworthy Retrieval-Augmented Language Models | 2023 | pdftotext | front, introduction, related, experiments, method, method, results, limitations, references |
| P3 | Detecting Hallucination and Coverage Errors in Retrieval Augmented Generation for Controversial Topics | 2024 | pdftotext | front, introduction, method, results, related, limitations, method, method, method |
| P4 | Luna: An Evaluation Foundation Model to Catch Language Model Hallucinations with High Accuracy and Low Cost | 2024 | pdftotext | front, introduction, related, results, limitations, references, experiments |
| P5 | Lynx: An Open Source Hallucination Evaluation Model | 2024 | pdftotext | front, introduction, related, method, results, limitations, references, experiments |
| P6 | ReDeEP: Detecting Hallucination in Retrieval-Augmented Generation via Mechanistic Interpretability | 2024 | pdftotext | front, introduction, method, method, method, related, method, references, method, results, experiments |
| P7 | Span-Level Hallucination Detection for LLM-Generated Answers | 2025 | pdftotext | front, introduction, related, method, results, references |
| P8 | Faithfulness-Aware Uncertainty Quantification for Fact-Checking the Output of Retrieval Augmented Generation | 2025 | pdftotext | front, introduction, experiments, related, future_work, limitations, references, method, method |
| P9 | Probabilistic distances-based hallucination detection in LLMs with RAG | 2025 | pdftotext | front, method, references |
| P10 | LUMINA: Detecting Hallucinations in RAG System with Context-Knowledge Signals | 2025 | pdftotext | front, method, introduction, related, method, related, method, experiments, results, method, experiments, results |
| P11 | InterpDetect: Interpretable Signals for Detecting Hallucinations in Retrieval-Augmented Generation | 2025 | pdftotext | front, introduction, related, method, limitations, references |
| P12 | TPA: Next Token Probability Attribution for Detecting Hallucinations in RAG | 2025 | pdftotext | front, introduction, method, experiments, related, method, experiments, future_work, limitations, references |
| P13 | The Semantic Illusion: Certified Limits of Embedding-Based Hallucination Detection in RAG Systems | 2025 | pdftotext | front, introduction, related, method, references |
| P14 | RAGognizer: Hallucination-Aware Fine-Tuning via Detection Head Integration | 2026 | pdftotext | front, introduction, related, method, results, conclusion, references |
| P15 | Evidence Graph Consistency in Retrieval-Augmented Generation: A Model-Dependent Analysis of Hallucination Detection | 2026 | pdftotext | front, abstract, introduction, related, method, experiments, results, conclusion, references |
| P16 | CORTEX: Token-Level Hallucination Detection in RAG via Comparative Internal Representations | 2026 | pdftotext | front, introduction, related, results, related, limitations, references |
| P17 | Evidence-Aligned Entity Verification for Hallucination Detection in Retrieval-Augmented Generation | 2026 | pdftotext | front, introduction, method, results, limitations, references, method, related |
| P18 | When Does Uncertainty Measure RAG Hallucination Risk? | 2026 | pdftotext | front, introduction, results, limitations, references |

#### What is known

**method**

- Embedding and similarity (P12, P9)
- Fine-tuned detector (classifier, detection head) (P14, P4)
- Graph and entity-based checking (P15, P17)
- Internal-state signals (hidden states, attention) (P11, P12, P16, P9)
- NLI / entailment (P7)
- Uncertainty and token probability (P12, P18, P7, P8)

**setting**

- Domain-specific data (medical, legal, industrial) (P11)
- Multilingual data (P7)
- Open-weight LLMs (Llama, Mistral, Qwen) (P7)
- Proprietary LLMs (GPT) (P1)
- Question answering (P1, P11, P13, P15, P8)
- RAGTruth benchmark (P12, P15, P2, P4)

**issue**

- Benchmark scope and size (P14, P15, P4)
- Cost and latency (P11, P12, P3)
- Generalization across domains and datasets (P1, P12, P15, P18, P3, P6)
- Label and annotation quality (P14, P15, P16, P2, P3, P4, P8)
- Language coverage (English only) (P12, P3, P5)
- Long context and complex reasoning (P17, P5)
- Need for model internals (white-box access) (P11, P12, P16)
- Retrieval quality and conflicting context (P5)
- Thresholds and calibration (P15, P18)

#### Conflicts

- Internal-state signals (hidden states, attention) — P10 [P10:introduction]: "However, existing methods rely on mechanistic interpretability heuristics—such as selecting specific attention heads or transformer layers to achieve the optimal hallucination detection performance—which require heavy hyperparameter tuning and often fail to generalize across models and datasets." — vs P12 [P12:result, paraphrase]: Extensive experiments demonstrate that TPA achieves state-of-the-art performance in detecting hallucinations across the diverse architectures of the five tested models. — (c) the setting of P10 is unknown, so the claims cannot be compared
- Graph and entity-based checking — P15 [P15:introduction]: "We analyse the structural patterns underlying this split and demonstrate that embedding-based graph consistency alone is not reliable as a model-independent hallucination signal." — vs P17 [P17:result, paraphrase]: EAEV achieves consistent improvements over existing methods with strong generalization capabilities across the evaluated benchmarks. — (a) different settings: P15 on Question answering, RAGTruth benchmark, P17 on 
- Uncertainty and token probability — P18 [P18:introduction]: "Token probabilities offer an appealing measurement: if an answer is poorly supported by the retrieved context, the model may assign lower probability to its tokens." — vs P8 [P8:result, paraphrase]: Extensive experiments show that FRANQ achieves more accurate detection of factual errors in RAG-generated responses compared to unsupervised UQ baselines, RAG-specific methods, and supervised classifiers. — (c) the setting of P18 is unknown, so the claims cannot be compared

#### Research gaps

##### KT1 (G1, score 7)

Among the papers read, the issue **Language coverage (English only)** is stated as a limitation or future work by 3 papers (P12, P3, P5), and no other paper read addresses it.

- P3 [P3-L1; limitations] ✓ found in the paper: "The NPOV Response Generator is trained and evaluated only in English, and our NPOV Response Task does not address how to create the content in the perspectives and their arguments."
- P5 [P5-L1; limitations] ✓ found in the paper: "The bulk of datasets used in HaluBench is in English, which presents a limitation in real-world applications that include multilingual inputs and contexts."
- P5 [P5-F1; limitations] ✓ found in the paper: "We hope to enhance coverage and diversity in HaluBench and training data by incorporating non-English and low resource languages in future extensions."
- P12 [P12-F4; future_work] ✓ found in the paper: "Fourth, extending POS-based aggregation to non-English and specialized domains (code, scientific text) via multilingual spaCy or AST node types."

##### KT2 (G3, score 7)

Among the papers read, Embedding and similarity (P12, P9) and Question answering (P1, P11, P13, P15, P8) both occur, but no paper read uses Embedding and similarity on Question answering; both groups state the issue Cost and latency, Generalization across domains and datasets, Need for model internals (white-box access).

- P1 [P1:problem; problem] paraphrase, no verified quotation: Question answering `question answering`
- P1 [P1:setting; setting] paraphrase, no verified quotation: Question answering `question answering`
- P1 [P1:result; result] paraphrase, no verified quotation: Question answering `qa`
- P8 [P8:setting; setting] paraphrase, no verified quotation: Question answering `question answering`
- P9 [P9:method; method] paraphrase, no verified quotation: Embedding and similarity `distances`
- P11 [P11:setting; setting] paraphrase, no verified quotation: Question answering `question answering`
- P12 [P12:method; method] paraphrase, no verified quotation: Embedding and similarity `embedding`
- P13 [P13:setting; setting] paraphrase, no verified quotation: Question answering `questions`

##### KT3 (G3, score 7)

Among the papers read, Fine-tuned detector (classifier, detection head) (P14, P4) and Question answering (P1, P11, P13, P15, P8) both occur, but no paper read uses Fine-tuned detector (classifier, detection head) on Question answering; both groups state the issue Benchmark scope and size, Label and annotation quality.

- P1 [P1:problem; problem] paraphrase, no verified quotation: Question answering `question answering`
- P1 [P1:setting; setting] paraphrase, no verified quotation: Question answering `question answering`
- P1 [P1:result; result] paraphrase, no verified quotation: Question answering `qa`
- P4 [P4:method; method] paraphrase, no verified quotation: Fine-tuned detector (classifier, detection head) `finetuned`
- P8 [P8:setting; setting] paraphrase, no verified quotation: Question answering `question answering`
- P11 [P11:setting; setting] paraphrase, no verified quotation: Question answering `question answering`
- P13 [P13:setting; setting] paraphrase, no verified quotation: Question answering `questions`
- P14 [P14:method; method] paraphrase, no verified quotation: Fine-tuned detector (classifier, detection head) `detection head`

##### KT4 (G1, score 5)

Among the papers read, the issue **Long context and complex reasoning** is stated as a limitation or future work by 2 papers (P17, P5), and no other paper read addresses it.

- P5 [P5-F4; limitations] ✓ found in the paper: "An interesting area for future work involves applying LYNX to NLI tasks. Since the problem of hallucination detection is closely related to NLI, a strong hallucination detection model is likely capable of performing reasoning in other NLP domains."
- P17 [P17-L2; limitations] ✓ found in the paper: "LLM outputs can exhibit instability across different runs, particularly for complex queries that require multi-step reasoning"

##### KT5 (G3, score 5)

Among the papers read, Internal-state signals (hidden states, attention) (P11, P12, P16, P9) and Proprietary LLMs (GPT) (P1) both occur, but no paper read uses Internal-state signals (hidden states, attention) on Proprietary LLMs (GPT); both groups state the issue Generalization across domains and datasets.

- P1 [P1:setting; setting] paraphrase, no verified quotation: Proprietary LLMs (GPT) `chatgpt`
- P9 [P9:method; method] paraphrase, no verified quotation: Internal-state signals (hidden states, attention) `hidden states`
- P11 [P11:method; method] paraphrase, no verified quotation: Internal-state signals (hidden states, attention) `attention`
- P12 [P12:method; method] paraphrase, no verified quotation: Internal-state signals (hidden states, attention) `ffn`
- P16 [P16:method; method] paraphrase, no verified quotation: Internal-state signals (hidden states, attention) `internal representations`

##### KT6 (G3, score 5)

Among the papers read, Uncertainty and token probability (P12, P18, P7, P8) and Domain-specific data (medical, legal, industrial) (P11) both occur, but no paper read uses Uncertainty and token probability on Domain-specific data (medical, legal, industrial); both groups state the issue Cost and latency, Need for model internals (white-box access).

- P7 [P7:method; method] paraphrase, no verified quotation: Uncertainty and token probability `confidence`
- P8 [P8:method; method] paraphrase, no verified quotation: Uncertainty and token probability `uncertainty`
- P11 [P11:setting; setting] paraphrase, no verified quotation: Domain-specific data (medical, legal, industrial) `financial`
- P12 [P12:problem; problem] paraphrase, no verified quotation: Uncertainty and token probability `token probabilities`
- P18 [P18:problem; problem] paraphrase, no verified quotation: Uncertainty and token probability `uncertainty`
- P18 [P18:method; method] paraphrase, no verified quotation: Uncertainty and token probability `perplexity`

##### KT7 (G3, score 5)

Among the papers read, Uncertainty and token probability (P12, P18, P7, P8) and Proprietary LLMs (GPT) (P1) both occur, but no paper read uses Uncertainty and token probability on Proprietary LLMs (GPT); both groups state the issue Generalization across domains and datasets.

- P1 [P1:setting; setting] paraphrase, no verified quotation: Proprietary LLMs (GPT) `chatgpt`
- P7 [P7:method; method] paraphrase, no verified quotation: Uncertainty and token probability `confidence`
- P8 [P8:method; method] paraphrase, no verified quotation: Uncertainty and token probability `uncertainty`
- P12 [P12:problem; problem] paraphrase, no verified quotation: Uncertainty and token probability `token probabilities`
- P18 [P18:problem; problem] paraphrase, no verified quotation: Uncertainty and token probability `uncertainty`
- P18 [P18:method; method] paraphrase, no verified quotation: Uncertainty and token probability `perplexity`

##### KT8 (G3, score 3)

Among the papers read, Embedding and similarity (P12, P9) and Domain-specific data (medical, legal, industrial) (P11) both occur, but no paper read uses Embedding and similarity on Domain-specific data (medical, legal, industrial); both groups state the issue Cost and latency, Need for model internals (white-box access).

- P9 [P9:method; method] paraphrase, no verified quotation: Embedding and similarity `distances`
- P11 [P11:setting; setting] paraphrase, no verified quotation: Domain-specific data (medical, legal, industrial) `financial`
- P12 [P12:method; method] paraphrase, no verified quotation: Embedding and similarity `embedding`

##### KT9 (G3, score 3)

Among the papers read, Embedding and similarity (P12, P9) and Proprietary LLMs (GPT) (P1) both occur, but no paper read uses Embedding and similarity on Proprietary LLMs (GPT); both groups state the issue Generalization across domains and datasets.

- P1 [P1:setting; setting] paraphrase, no verified quotation: Proprietary LLMs (GPT) `chatgpt`
- P9 [P9:method; method] paraphrase, no verified quotation: Embedding and similarity `distances`
- P12 [P12:method; method] paraphrase, no verified quotation: Embedding and similarity `embedding`

##### KT10 (G3, score 3)

Among the papers read, Graph and entity-based checking (P15, P17) and Proprietary LLMs (GPT) (P1) both occur, but no paper read uses Graph and entity-based checking on Proprietary LLMs (GPT); both groups state the issue Generalization across domains and datasets.

- P1 [P1:setting; setting] paraphrase, no verified quotation: Proprietary LLMs (GPT) `chatgpt`
- P15 [P15:problem; problem] paraphrase, no verified quotation: Graph and entity-based checking `graph`
- P15 [P15:method; method] paraphrase, no verified quotation: Graph and entity-based checking `graph`
- P17 [P17:problem; problem] paraphrase, no verified quotation: Graph and entity-based checking `entity`
- P17 [P17:method; method] paraphrase, no verified quotation: Graph and entity-based checking `entity`

##### KT11 (G4, score -0.5)

Among the papers read, the evidence for NLI / entailment comes from one paper only (P7); it is not repeated on another setting.

- P7 [P7:method; method] paraphrase, no verified quotation: NLI / entailment `entailment`

#### Not read

Every paper given was read and extracted.


#### Sources

- [P1] DelucionQA: Detecting Hallucinations in Domain-specific Question Answering
- [P2] RAGTruth: A Hallucination Corpus for Developing Trustworthy Retrieval-Augmented Language Models
- [P3] Detecting Hallucination and Coverage Errors in Retrieval Augmented Generation for Controversial Topics
- [P4] Luna: An Evaluation Foundation Model to Catch Language Model Hallucinations with High Accuracy and Low Cost
- [P5] Lynx: An Open Source Hallucination Evaluation Model
- [P6] ReDeEP: Detecting Hallucination in Retrieval-Augmented Generation via Mechanistic Interpretability
- [P7] Span-Level Hallucination Detection for LLM-Generated Answers
- [P8] Faithfulness-Aware Uncertainty Quantification for Fact-Checking the Output of Retrieval Augmented Generation
- [P9] Probabilistic distances-based hallucination detection in LLMs with RAG
- [P10] LUMINA: Detecting Hallucinations in RAG System with Context-Knowledge Signals
- [P11] InterpDetect: Interpretable Signals for Detecting Hallucinations in Retrieval-Augmented Generation
- [P12] TPA: Next Token Probability Attribution for Detecting Hallucinations in RAG
- [P13] The Semantic Illusion: Certified Limits of Embedding-Based Hallucination Detection in RAG Systems
- [P14] RAGognizer: Hallucination-Aware Fine-Tuning via Detection Head Integration
- [P15] Evidence Graph Consistency in Retrieval-Augmented Generation: A Model-Dependent Analysis of Hallucination Detection
- [P16] CORTEX: Token-Level Hallucination Detection in RAG via Comparative Internal Representations
- [P17] Evidence-Aligned Entity Verification for Hallucination Detection in Retrieval-Augmented Generation
- [P18] When Does Uncertainty Measure RAG Hallucination Risk?

## Phụ lục C. MPC – 8 bài (baseline mục 3.1, khoảng trống 5) (`topics/mpc/runs/orig8/report.md`)

### Research gaps: Model predictive control for trajectory tracking on resource-constrained embedded hardware

Papers given: 8; records parsed: 8. Every gap below is a gap among the papers read, not a claim about the whole literature.

#### Paper register

| Id | Title | Year | Read by | Sections found |
|---|---|---|---|---|
| P3 | Real-time Nonlinear MPC Strategy with Full Vehicle Validation for Autonomous Driving | 2021 | pdftotext | front, abstract, introduction, related, experiments, conclusion, references |
| P6 | Aggressive Trajectory Tracking for Nano Quadrotors Using Embedded Nonlinear Model Predictive Control | 2023 | pdftotext | front, abstract, introduction, related, method, results, future_work, references |
| P7 | Code Generation and Conic Constraints for Model-Predictive Control on Microcontrollers with Conic-TinyMPC | 2024 | pdftotext | front, abstract, introduction, related, experiments, future_work, references |
| P8 | Embedded Hierarchical MPC for Autonomous Navigation | 2024 | pdftotext | front, abstract, appendix, introduction, method, method, method, method, results, future_work, references |
| P11 | Tiny Learning-Based MPC for Multirotors: Solver-Aware Learning for Efficient Embedded Predictive Control | 2024 | pdftotext | front, abstract, introduction, method, related, method, experiments, conclusion, references |
| P12 | LoL-NMPC: Low-Level Dynamics Integration in Nonlinear Model Predictive Control for Unmanned Aerial Vehicles | 2025 | pdftotext | front, abstract, appendix, introduction, related, method, method, results, conclusion, references |
| P13 | AutoMPC: A Code Generator for MPC-based Automated Driving | 2025 | pdftotext | front, abstract, introduction, method, method, method, method, method, references |
| P17 | Real-time Gaussian Process based Approximate Model Predictive Trajectory Tracking Control for Autonomous Vehicles | 2026 | pdftotext | front, abstract, introduction, method, experiments, conclusion, references |

#### What is known

**method**

- Automatic code generation for MPC (P13, P7)
- Hierarchical / distributed MPC (P8)
- Learning-based MPC (GP, neural network) (P11, P17)
- Linear / convex MPC (QP, ADMM) (P3, P7)
- NMPC (online nonlinear optimisation) (P12, P13, P3, P6, P8)

**setting**

- Aerial vehicle (quadrotor, UAV) (P11, P12, P7, P8)
- Embedded computer (Raspberry Pi, onboard computer) (P12, P17, P8)
- Full-size road vehicle (P3)
- Microcontroller (P11, P6, P7)

**issue**

- Computational cost and real-time (P3)
- Extension to other platforms and scenarios (P17, P3, P6)
- Multi-agent systems (P6)
- Online learning and adaptation (P11, P17, P6)
- Real-world validation (P8)
- Robustness to model mismatch and disturbances (P11, P13, P17, P7, P8)
- Safety and guarantees (P17, P6, P8)

#### Conflicts

- NMPC (online nonlinear optimisation) — P11 [P11:introduction]: "Nonlinear MPC (NMPC) has been successfully demonstrated on fullscale multirotors for agile flight (Hanover et al., 2022; Tzoumanikas et al., 2020; Bicego et al., 2020; Nan et al., 2022), but solving a nonconvex optimal control problem (OCP) at each time step makes onboard implementation infeasible for resource-limited platforms." — vs P12 [P12:result, paraphrase]: The proposed method achieves an average 21.97% reduction in trajectory tracking error compared to standard methods while maintaining real-time feasibility at 100 Hz. — not explained: both on Aerial vehicle (quadrotor, UAV)
- NMPC (online nonlinear optimisation) — P11 [P11:introduction]: "Nonlinear MPC (NMPC) has been successfully demonstrated on fullscale multirotors for agile flight (Hanover et al., 2022; Tzoumanikas et al., 2020; Bicego et al., 2020; Nan et al., 2022), but solving a nonconvex optimal control problem (OCP) at each time step makes onboard implementation infeasible for resource-limited platforms." — vs P3 [P3:result, paraphrase]: The NMPC controller was successfully deployed at 25Hz for trajectory control, demonstrating capabilities in collision avoidance, automatic collision avoidance, and adaptive cruise control (ACC) at speeds ranging from 10kph to 60kph. — (a) different settings: P11 on Aerial vehicle (quadrotor, UAV), Microcontroller, P3 on Full-size road vehicle
- Learning-based MPC (GP, neural network) — P11 [P11:introduction]: "Despite demonstrated benefits, GP MPC remains computationally expensive, requiring GP inference along the prediction horizon and solving a nonconvex OCP at each time step." — vs P17 [P17:result, paraphrase]: The Gaussian process-based controller achieves a computational speedup of over five times while achieving similar closed-loop tracking performance compared to the real-time iterations implementation. — (b) P11 itself reports Learning-based MPC (GP, neural network) working, so its negative sentence is about another configuration
- NMPC (online nonlinear optimisation) — P12 [P12:introduction]: "In contrast, predictive controllers like NMPC [14] leverage modelling of the dynamics to track even partially infeasible trajectories, such as those presented in [10]." — vs P3 [P3:result, paraphrase]: The NMPC controller was successfully deployed at 25Hz for trajectory control, demonstrating capabilities in collision avoidance, automatic collision avoidance, and adaptive cruise control (ACC) at speeds ranging from 10kph to 60kph. — (b) P12 itself reports NMPC (online nonlinear optimisation) working, so its negative sentence is about another configuration

#### Research gaps

##### KT1 (G1, score 7.5)

Among the papers read, the issue **Extension to other platforms and scenarios** is stated as a limitation or future work by 3 papers (P17, P3, P6), and no other paper read addresses it.

- P3 [P3-L2; conclusion] ✓ found in the paper: "Trajectory control is one relevant use case of the applicability of realtime NMPC, however, other use cases could be tested using the same XiL development framework"
- P3 [P3-F1; conclusion] ✓ found in the paper: "applications can be extended to more complex OCP or other optimization based formulations such as optimal planning"
- P6 [P6-L1; future_work] ✓ found in the paper: "Some of the future work directions are the extension to multiple nano-quadrotor crazyflies2.1"
- P6 [P6-F1; future_work] ✓ found in the paper: "Some of the future work directions are the extension to multiple nano-quadrotor crazyflies2.1"
- P17 [P17-L1; abstract] ✓ found in the paper: "the large amount of training data required for successful generalization across distinct reference trajectories poses a significant challenge"

##### KT2 (G1, score 6.5)

Among the papers read, the issue **Safety and guarantees** is stated as a limitation or future work by 3 papers (P17, P6, P8), and no other paper read addresses it.

- P6 [P6-F3; future_work] ✓ found in the paper: "integration with other control techniques such as reinforcement learning and human-in-the-loop can be added to the control loop to increase the safety and reliability of the UAVs and UGVs"
- P8 [P8-L1; future_work] ✓ found in the paper: "the derived theoretical guarantees are only valid in the absence of model mismatch."
- P17 [P17-F1; conclusion] ✓ found in the paper: "exploiting uncertainty estimates that Gaussian processes provide to guide online refinement or enhance safety"

##### KT3 (G3, score 5)

Among the papers read, Automatic code generation for MPC (P13, P7) and Embedded computer (Raspberry Pi, onboard computer) (P12, P17, P8) both occur, but no paper read uses Automatic code generation for MPC on Embedded computer (Raspberry Pi, onboard computer); both groups state the issue Robustness to model mismatch and disturbances.

- P7 [P7:method; method] paraphrase, no verified quotation: Automatic code generation for MPC `code generation`
- P8 [P8:setting; setting] paraphrase, no verified quotation: Embedded computer (Raspberry Pi, onboard computer) `embedded computer`
- P12 [P12:setting; setting] paraphrase, no verified quotation: Embedded computer (Raspberry Pi, onboard computer) `flight computer`
- P13 [P13:method; method] paraphrase, no verified quotation: Automatic code generation for MPC `c code`
- P17 [P17:setting; setting] paraphrase, no verified quotation: Embedded computer (Raspberry Pi, onboard computer) `raspberry pi`

##### KT4 (G3, score 5)

Among the papers read, Linear / convex MPC (QP, ADMM) (P3, P7) and Embedded computer (Raspberry Pi, onboard computer) (P12, P17, P8) both occur, but no paper read uses Linear / convex MPC (QP, ADMM) on Embedded computer (Raspberry Pi, onboard computer); both groups state the issue Extension to other platforms and scenarios, Robustness to model mismatch and disturbances.

- P3 [P3:method; method] paraphrase, no verified quotation: Linear / convex MPC (QP, ADMM) `quadratic programming`
- P7 [P7:problem; problem] paraphrase, no verified quotation: Linear / convex MPC (QP, ADMM) `conic`
- P7 [P7:method; method] paraphrase, no verified quotation: Linear / convex MPC (QP, ADMM) `admm`
- P8 [P8:setting; setting] paraphrase, no verified quotation: Embedded computer (Raspberry Pi, onboard computer) `embedded computer`
- P12 [P12:setting; setting] paraphrase, no verified quotation: Embedded computer (Raspberry Pi, onboard computer) `flight computer`
- P17 [P17:setting; setting] paraphrase, no verified quotation: Embedded computer (Raspberry Pi, onboard computer) `raspberry pi`

##### KT5 (G2, score 4.5)

Among the papers read, P11 say NMPC (online nonlinear optimisation) does not work or is not feasible, while P12 report it working in the same setting class; no paper read compares them under the same conditions.

- P11 [P11:introduction; introduction] ✓ found in the paper: "Nonlinear MPC (NMPC) has been successfully demonstrated on fullscale multirotors for agile flight (Hanover et al., 2022; Tzoumanikas et al., 2020; Bicego et al., 2020; Nan et al., 2022), but solving a nonconvex optimal control problem (OCP) at each time step makes onboard implementation infeasible for resource-limited platforms."
- P12 [P12:result; field] paraphrase, no verified quotation: The proposed method achieves an average 21.97% reduction in trajectory tracking error compared to standard methods while maintaining real-time feasibility at 100 Hz.

##### KT6 (G3, score 4)

Among the papers read, Hierarchical / distributed MPC (P8) and Microcontroller (P11, P6, P7) both occur, but no paper read uses Hierarchical / distributed MPC on Microcontroller; both groups state the issue Robustness to model mismatch and disturbances, Safety and guarantees.

- P6 [P6:setting; setting] paraphrase, no verified quotation: Microcontroller `crazyflie`
- P7 [P7:problem; problem] paraphrase, no verified quotation: Microcontroller `microcontrollers`
- P7 [P7:setting; setting] paraphrase, no verified quotation: Microcontroller `microcontroller`
- P8 [P8:method; method] paraphrase, no verified quotation: Hierarchical / distributed MPC `hierarchical`
- P11 [P11:setting; setting] paraphrase, no verified quotation: Microcontroller `microcontroller`

##### KT7 (G3, score 3)

Among the papers read, Learning-based MPC (GP, neural network) (P11, P17) and Full-size road vehicle (P3) both occur, but no paper read uses Learning-based MPC (GP, neural network) on Full-size road vehicle; both groups state the issue Extension to other platforms and scenarios.

- P3 [P3:problem; problem] paraphrase, no verified quotation: Full-size road vehicle `autonomous driving`
- P3 [P3:setting; setting] paraphrase, no verified quotation: Full-size road vehicle `ford`
- P11 [P11:method; method] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `gaussian process`
- P17 [P17:method; method] paraphrase, no verified quotation: Learning-based MPC (GP, neural network) `gaussian process`

##### KT8 (G4, score -0.5)

Among the papers read, the evidence for Hierarchical / distributed MPC comes from one paper only (P8); it is not repeated on another setting.

- P8 [P8:method; method] paraphrase, no verified quotation: Hierarchical / distributed MPC `hierarchical`

#### Not read

Every paper given was read and extracted.


#### Sources

- [P3] Real-time Nonlinear MPC Strategy with Full Vehicle Validation for Autonomous Driving
- [P6] Aggressive Trajectory Tracking for Nano Quadrotors Using Embedded Nonlinear Model Predictive Control
- [P7] Code Generation and Conic Constraints for Model-Predictive Control on Microcontrollers with Conic-TinyMPC
- [P8] Embedded Hierarchical MPC for Autonomous Navigation
- [P11] Tiny Learning-Based MPC for Multirotors: Solver-Aware Learning for Efficient Embedded Predictive Control
- [P12] LoL-NMPC: Low-Level Dynamics Integration in Nonlinear Model Predictive Control for Unmanned Aerial Vehicles
- [P13] AutoMPC: A Code Generator for MPC-based Automated Driving
- [P17] Real-time Gaussian Process based Approximate Model Predictive Trajectory Tracking Control for Autonomous Vehicles
