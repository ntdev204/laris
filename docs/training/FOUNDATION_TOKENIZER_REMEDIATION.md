---
document_id: "DOC-PLAN-FOUNDATION-TOKENIZER-R1-001"
title: "Foundation Tokenizer Remediation R1"
document_type: "plan"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Project Owner"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/training/FOUNDATION_BUDGET.md"
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
decision_references:
  - "ADR-002"
  - "ADR-008"
change_summary: "Prepares a train-only corpus and freezes validation for an owner-approved tokenizer trial."
---

# Vòng sửa tokenizer foundation

F06 đã dùng hết hai vòng chẩn đoán được duyệt. Checkpoint sampling tại bước
1.500 có loss validation trung bình 0,221779, thấp hơn 0,222040 của baseline.
Kết quả theo dataset đổi chiều. ANLI và ViNLI tăng macro F1 so với baseline,
còn PAWS giảm. F07 đo lại fertility với cùng tokenizer được dùng trong checkpoint
sampling. EN đạt 1,420 và VI đạt 1,363 so với ngưỡng 1,35.
[Báo cáo F06](../../reports/language_encoder/foundation-owner-run.json) ·
[Báo cáo F07](../../reports/language_encoder/foundation-qualification.json)

## Corpus và mẫu validation đã khóa

Ứng viên đề xuất giữ SentencePiece BPE 32k và các ID đặc biệt của encoder.
Corpus thử lấy từ bốn nguồn train đã ghi trong manifest. Mỗi nguồn có seed cố
định, mẫu tối đa 80.000 dòng và giới hạn một triệu mục phân tách bằng khoảng
trắng sau khi chuẩn hóa và khử trùng. Bốn nguồn gồm Wikipedia EN, All-NLI EN,
Wikipedia VI và CC-100 VI. Cách lấy mẫu này kiểm tra giả thuyết rằng thêm văn
bản ngoài Wikipedia và cân bằng quy mô nguồn giúp giảm fragmentation. Chưa có
số đo cho ứng viên mới.

Mẫu so sánh development lấy từ đúng bốn nguồn trên ở split val. Loại văn bản
trùng toàn phần hoặc tiền tố 200 ký tự với một trong hai corpus fit. Hai
tokenizer được so trên cùng các văn bản đã khóa và dùng cùng cách tính macro
theo nguồn. Giữ test cho lần đánh giá ứng viên đã chốt.
[Bằng chứng chuẩn bị](../../reports/tokenizer/foundation-r1-preparation.json)

Có thể tái tạo corpus và mẫu development trên workspace chưa có thư mục
`artifacts/tokenizer/foundation-r1`.

```bash
.venv/bin/python experiments/language_encoder/prepare_tokenizer_remediation.py
```

## Lệnh cho F06-R1 sau khi owner duyệt

Chọn ngân sách CPU cho fit và ngân sách GPU mới cho encoder. Lệnh fit tạo model
trong thư mục R1 riêng. Dùng output corpus thực tế để kiểm checksum trước khi
so trên validation.

```bash
.venv/bin/laris-server train tokenizer --authorized --vocab-size 32000 \
  --train-shards artifacts/tokenizer/foundation-r1/train.parquet \
  --corpus-text-out artifacts/tokenizer/foundation-r1/fit-actual.txt \
  --output-dir artifacts/tokenizer/foundation-r1/candidate \
  --model-prefix laris_spm_32k_r1

.venv/bin/python experiments/language_encoder/prepare_tokenizer_remediation.py \
  --compare artifacts/tokenizer/foundation-r1/candidate/laris_spm_32k_r1.model \
  --fit-corpus artifacts/tokenizer/foundation-r1/fit-actual.txt
```

Xem macro fertility EN/VI, từng nguồn và tỷ lệ UNK trong `comparison.json`.
Chốt tokenizer sau khi xem validation. Nếu chọn tokenizer mới, chạy encoder
từ đầu với lineage mới vì token ID đã đổi. Cần đo profiling của cấu hình mới
và chốt số bước, số vòng, lịch validation và giới hạn thời gian trước run đó.

G12 còn thiếu relevance STEM do người gán và kết quả BM25 tương ứng. F07 cũng
cần xử lý các cặp trùng STS-B và rà lại offset ViQuAD trước khi đóng băng bản
test dùng nghiệm thu. Ghi bản sửa dữ liệu thành revision riêng với checksum
và giữ các split lịch sử để đối chiếu.

## Điều kiện retrieval cho ngân sách GPU (đo inference 2026-11-11)

Checkpoint F06 (sampling) trên SciFact train claims, tập development: dense MRR 0,012 so
với BM25 0,636. Trên cặp EN-VI dịch máy STEM-VI: dense 0,019 so với BM25 0,484. Kết quả giống
đo SQuAD trước đó (0,034 so với 0,783). Chi tiết ở `OWNER_RUNBOOK.md` mục 5b.

Hệ quả cho F06-R1, để owner cân nhắc khi chốt ngân sách (agent không thay gate và không chạy):

1. F06 train với `--retrieval-loss-weight 0`, nên embedding CLS chưa học retrieval. Một encoder
   mới với tokenizer mới vẫn thất bại G12 nếu không có giai đoạn contrastive trên cặp
   query-passage. Cần ngân sách và profiling riêng với trọng số dương.
2. G12 yêu cầu MRR ≥ 0,82 **và** vượt BM25. BM25 đã đạt 0,636 MRR trên SciFact train; ngưỡng
   0,82 trên một corpus y sinh 5.183 abstract với encoder compact là mục tiêu rất khó. Owner
   cần xác nhận ngưỡng này áp dụng cho nguồn SciFact trước khi cam kết ngân sách. Tôi không
   đổi ngưỡng.
3. Nếu dùng SciFact train claims để train contrastive, nguồn đó mất tính "chưa từng thấy"
   trong kiểm cô lập; ghi rõ trong lineage. Test claims phải giữ nguyên niêm phong.
4. STEM-VI (đã được owner cho dùng) là dữ liệu dịch máy; chỉ dùng như tín hiệu bổ trợ, không
   là nhãn người.

## Kết quả fit tokenizer (2026-11-11, CPU, chỉ split train và mẫu validation đã khóa)

Owner ủy quyền fit trực tiếp. Bằng chứng: `reports/tokenizer/foundation-r1-candidates.json`; test chưa đọc.
Corpus nâng từ 4 triệu lên 74 triệu từ (siêu tập 172 triệu từ). Fit chỉ mất khoảng 1 đến 2 phút.

| Cấu hình (SentencePiece BPE) | EN | VI | Qua 1,35? |
| --- | --- | --- | --- |
| Tokenizer cũ | 1,441 | 1,344 | không |
| 32k, tách chữ số, 74 triệu từ | 1,430 | 1,282 | EN không |
| 32k, tách chữ số, đổi trọng số EN (3 biến thể) | 1,419 đến 1,430 | 1,287 đến 1,299 | EN không |
| 48k, tách chữ số | 1,379 | 1,275 | EN không |
| 64k, tách chữ số | 1,355 | 1,263 | EN không |
| **32k, không tách chữ số** (3 biến thể corpus) | **1,337 đến 1,348** | **1,207 đến 1,220** | **cả hai qua** |
| 48k, không tách chữ số | 1,293 | 1,193 | cả hai qua |

Chữ số chiếm khoảng 5% số từ của Wikipedia EN; mỗi chữ số thành một token nên EN không xuống dưới
khoảng 1,42 bằng cách chỉnh dữ liệu. Biên của cấu hình 32k không tách chữ số rất mỏng (0,002 đến 0,013).
`split_digits` chỉ là giá trị mặc định trong `TokenizerTrainerConfig`; chưa có spec hay ADR quy định nó,
và lệnh `laris-server train tokenizer` chưa có tham số để đổi nó. Owner cần chọn: bỏ tách chữ số (đánh đổi:
số trong văn bản khoa học thành token dài hơn), hoặc tăng từ vựng.

### Lựa chọn của owner và tokenizer ứng viên (2026-11-11)

Owner chọn phương án B: từ vựng 48k, không tách chữ số. Đã fit bằng
`laris-server train tokenizer --authorized --vocab-size 48000 --no-split-digits` trên siêu tập đầy đủ (172 triệu từ,
mất 1 phút 52 giây, RSS đỉnh 6 GB). Mô hình: `artifacts/tokenizer/foundation-r1-super/candidate/laris_spm_48k_r1.model`.

| Mẫu validation đã khóa | Tokenizer cũ 32k | Ứng viên 48k |
| --- | --- | --- |
| Fertility EN | 1,441 | **1,300** (biên 0,050) |
| Fertility VI | 1,344 | **1,185** (biên 0,165) |
| UNK Wikipedia EN | 0,60% | 0,69% |
| UNK CC-100 VI | 1,30% | 0,83% |

ID đặc biệt (PAD, UNK, CLS, SEP, MASK) giữ nguyên vị trí. Đây là số đo trên mẫu development; fertility
trên test của F07 chưa đo. Hai việc còn lại trước khi huấn luyện encoder (việc của owner, cần training nên agent
không chạy): (1) đổi `vocab_size` từ 32000 lên 48000 trong cấu hình encoder và đo lại profiling bộ nhớ, vì
embedding lớn thêm 16k hàng; (2) chốt ngân sách GPU gồm giai đoạn contrastive cho G12.

### Chuẩn hóa đầu vào (đã sửa, 2026-11-11)

UNK trên văn bản thô là 0,7 đến 0,8% ở Wikipedia EN và CC-100 VI, cả với tokenizer cũ. Nguyên nhân: corpus fit
đã chuẩn hóa (ngoặc kép cong, gạch ngang, dấu ba chấm được đưa về ASCII) nên từ vựng không chứa các ký tự này,
trong khi dataloader và suy luận đưa văn bản thô vào SentencePiece. Chữ Việt viết hoa có dấu **không** bị UNK
(đọc ban đầu của tôi sai). Sửa bằng `NormalizedSentencePiece`
(`src/language/tokenization/normalized.py`): cùng phép chuẩn hóa với corpus fit, ở một ranh giới mã hóa.

- Bật khi train bằng `--normalize-input`; checkpoint ghi `text_normalization` trong provenance và bộ nạp suy
  luận tự bao tokenizer khi thấy khóa này, nên checkpoint cũ không đổi hành vi.
- Trên 6.000 dòng đầu của dữ liệu train thật: Wikipedia EN 0,76% xuống 0,086%, CC-100 VI 0,73% xuống 0,11%,
  SQuAD 0,32% xuống 0,11%. Phần còn lại là ký tự hiếm (®, «, ►, ký tự private-use).
- Lệnh train F06-R1 của owner phải có `--normalize-input`, và đo fertility test của F07 phải dùng cùng phép
  chuẩn hóa. Checkpoint F06 cũ được train trên văn bản thô nên không đổi.

## Ngân sách GPU cho F06-R1 (số đo và quyết định của owner, 2026-11-11)

**Số đo từ F06** (`reports/language_encoder/foundation-owner-run.json`, log `artifacts/profiles/foundation-f05-sampling-run.log`):

| Đại lượng | Giá trị |
| --- | --- |
| Tốc độ | khoảng 0,5 giây mỗi bước, batch hiệu dụng 64 |
| Bộ nhớ GPU đỉnh | 3,9 GiB trên RTX 5070 Ti 16 GB (từ vựng 32k) |
| Một vòng 2.000 bước | khoảng 15 phút 37 giây, cả F06 (hai vòng cộng validation) 37 phút 26 giây |
| Dữ liệu train | 7.216.454 dòng; một epoch là khoảng 113.000 bước |
| Model gốc `compact-1024-04` | 50.600 bước (khoảng 0,45 epoch) mới đạt validation tốt nhất |

**Ý nghĩa:** 2.000 bước chỉ bằng khoảng 0,018 epoch, chỉ đủ tinh chỉnh chẩn đoán. Từ vựng 48k làm đổi embedding
nên không dùng lại trọng số cũ (`--init-from` yêu cầu cùng cấu hình và cùng tokenizer), vì vậy lượt R1 train từ
khởi tạo ngẫu nhiên. Cấu hình hiện tại cũng dành 2.000 bước cho warmup.

**Các mức ngân sách** (ước tính từ 0,5 giây mỗi bước, chưa đo cho từ vựng 48k):

| Mức | Số bước | Epoch | Thời gian GPU |
| --- | --- | --- | --- |
| Ngang model gốc | 50.600 | 0,45 | khoảng 7 giờ |
| 1 epoch | khoảng 113.000 | 1 | khoảng 16 giờ |
| 3 epoch | khoảng 340.000 | 3 | khoảng 47 giờ |
| Giai đoạn contrastive cho G12 (thêm) | 5.000 đến 10.000 | không áp dụng | khoảng 1 đến 1,5 giờ |

"Giới hạn GPU" là tổng thời gian GPU của cả lượt F06-R1 (train cộng validation định kỳ); suy luận F07 tính riêng
và chỉ mất vài phút.

**Quyết định của owner:** chạy 10.000 bước trước (vòng 1, khoảng 1,4 giờ), sau đó xem đường học rồi quyết định
mở các vòng tiếp tới 50.600 bước và 3 epoch. Mỗi vòng sau dùng `--init-from` với lịch học mới.

