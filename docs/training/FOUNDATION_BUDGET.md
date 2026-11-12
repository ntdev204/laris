---
document_id: "DOC-PLAN-FOUNDATION-BUDGET-001"
title: "Foundation Training Budget and Tokenizer Decision"
document_type: "plan"
status: "APPROVED"
version: "1.0.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Project Owner"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/training/OWNER_RUNBOOK.md"
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
decision_references:
  - "ADR-002"
  - "ADR-008"
change_summary: "Records the owner profiling result and approved diagnostic budget."
---

# Ngân sách foundation và quyết định tokenizer

Owner đã chạy profiling và chốt ngân sách chẩn đoán cho F04A. Các số model dưới đây lấy từ 512 dòng validation mỗi dataset theo thứ
tự đọc hiện tại. Kết quả phụ thuộc mẫu và cần phép đo held-out đúng protocol tại F07.
[Báo cáo F04](../../reports/language_encoder/foundation-error-analysis.json)

| Gate | Bằng chứng hiện tại | Mục tiêu | Việc cần giải quyết |
| --- | --- | --- | --- |
| G01 ANLI macro F1 | 0,447 val | ≥ 0,85 | Recall contradiction 58/190. Đo lại theo lớp sau thay đổi sampling. |
| G02 ViNLI macro F1 | 0,546 val | ≥ 0,78 | Recall contradiction 70/172. ViNLI chiếm 1,52% hàng train của NLI theo sampler hiện tại. |
| G03 PAWS accuracy | 0,699 val | ≥ 0,88 | Kiểm hiệu quả sampling PAWS trên validation. |
| G04 PAWS macro F1 | 0,679 val | ≥ 0,88 | 113/228 cặp paraphrase bị gán lớp âm. Theo dõi confusion matrix. |
| G05 STS-B Spearman | 0,825 val | ≥ 0,82 | 5 cặp train/test trùng sau chuẩn hóa. Cần bản split được kiểm lại trước nghiệm thu. |
| G06 SQuAD EM | 0,645 val | ≥ 0,72 | Theo dõi lỗi khớp chính xác ở câu có đáp án. |
| G07 SQuAD F1 | 0,738 val | ≥ 0,83 | Theo dõi điểm chồng lấp văn bản sau thay đổi curriculum. |
| G08 ViQuAD EM | 0,383 val | ≥ 0,65 | Kiểm lại 5 offset validation và 4 offset test bị lệch với nguồn. |
| G09 ViQuAD F1 | 0,414 val | ≥ 0,78 | F1 câu có đáp án 0,247 và câu không đáp án 0,749. Theo dõi riêng hai nhóm. |
| G10 Fertility EN | 1,420 | ≤ 1,35 | Giữ tokenizer hiện tại thì phép đo này vẫn vượt ngưỡng. |
| G11 Fertility VI | 1,363 | ≤ 1,35 | So sánh ứng viên bằng cùng định nghĩa và protocol. |
| G12 STEM retrieval | Thiếu phép đo đủ điều kiện | MRR ≥ 0,82 và vượt BM25 | Cần STEM relevance do người gán. F03 general-domain đo dense 0,034 EN và 0,116 VI, BM25 0,783 EN và 0,813 VI. |

Hai checkpoint best/last hiện có chỉ cho ảnh chụp loss tổng hợp. Chưa có chuỗi
metric validation theo số bước đủ để dự báo thời điểm đạt gate. Báo cáo F04 chỉ
quét trùng cặp và context trong từng dataset. Kế hoạch sửa dữ liệu cần giữ lineage,
đóng băng bản sửa riêng và ghi checksum trước khi dùng để nghiệm thu.
[Sampling đề xuất](../../configs/data/foundation_sampling.yaml)

## Phép đo do owner chạy

Log cục bộ `artifacts/profiles/foundation-f04a.log`, SHA-256 `60d4d96e2e25e2014a4326a18df8d37aa890e96d152dca85f8e7d3a5decc0a8c`.
RTX 5070 Ti, compact 1.024 token, BF16, batch hiệu dụng 64 (4 × 16), AdamW chuẩn.
Peak CUDA cấp phát **3,64 GiB** trên giới hạn **14,5 GiB**. Loss hữu hạn ở cả năm
task. Đo **0,06 giây/micro-batch** và CLI quy đổi thành **khoảng 0,9
giây/bước optimizer** từ latency của micro-batch. Ước tính này chưa cộng thời
gian optimizer update, validation và ghi checkpoint.

| Bước optimizer | Thời gian tính từ 0,9 giây/bước |
| --- | --- |
| 1.000 | khoảng 15 phút |
| 2.000 | khoảng 30 phút |
| 10.000 | khoảng 2 giờ 30 phút |

Lệnh tái lập phép đo


Chạy từ thư mục gốc repository. Lệnh đo một cấu hình tham chiếu compact 1.024
token, BF16, micro-batch 4 và accumulation 16. Dùng AdamW chuẩn vì môi trường
hiện thiếu bitsandbytes. Nếu đổi cấu hình ứng viên thì đo lại cấu hình đó.

```bash
mkdir -p artifacts/profiles
set -o pipefail
LARIS_TRAINING_AUTHORIZED=1 .venv/bin/laris-server train language-encoder \
  --profile-only --model-size compact --max-seq-len 1024 \
  --training-config configs/language_encoder/compact.yaml \
  --micro-batch-size 4 --grad-accum-steps 16 --precision bf16 \
  --no-8bit-adam --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  2>&1 | tee artifacts/profiles/foundation-f04a.log
```

Profiler chạy backward và optimizer trên model tạm. Log in peak cấp phát CUDA,
thời gian mỗi micro-batch và ước tính thời gian mỗi optimizer step. Phép đo ngắn
chưa bao gồm đầy đủ chi phí validation, checkpoint và dao động của một run dài.
Dùng thời gian optimizer step đo trong smoke run của owner để cập nhật dự toán.
Mốc peak cấp phát là 14,5 GiB theo runbook.
[Runbook của owner](OWNER_RUNBOOK.md)

## Quyết định đã chốt cho F05

| Mục | Quyết định của owner |
| --- | --- |
| Profiling | Đã nhận và đối chiếu log. |
| Compute | Tối đa 2 giờ GPU, 2 vòng và 2.000 bước optimizer mỗi vòng. |
| Dừng | Validation mỗi 500 bước. Dừng sau 3 lần loss validation trung bình liên tiếp không cải thiện hoặc khi chạm giới hạn bước hay thời gian. |
| Tokenizer | Giữ tokenizer hiện tại và khởi tạo từ trọng số checkpoint hiện tại cho chẩn đoán. Fertility vẫn vượt ngưỡng ở cả EN và VI. |
| Khi hết ngân sách | Dừng và xem lại kết quả trước khi duyệt vòng mới. Fit tokenizer mới cần dự toán riêng. |

Nếu chọn thử sampler F04, giữ task exponent 0,7 và đối chứng với sampler hiện tại
ở cùng số bước. Chỉ thay phân bố nguồn trong NLI, paraphrase và QA cho vòng
đối chứng này. Điều chỉnh objective retrieval là một thay đổi riêng ở F05.
