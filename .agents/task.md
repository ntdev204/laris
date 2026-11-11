---
schema_version: 2
no_training: true
stage_order:
- governance
- foundation
- scientific_language
- ocr
- manuscript
- integration
- specialists
- product
next_task: F06-R1
models:
  foundation:
    status: not_qualified
    qualification_task: F07
    owner_approved: false
  scientific_language:
    status: not_implemented
    qualification_task: S05
    owner_approved: false
  ocr:
    status: not_implemented
    qualification_task: O04
    owner_approved: false
  manuscript:
    status: not_implemented
    qualification_task: M03
    owner_approved: false
  integration:
    status: not_qualified
    qualification_task: I04
    owner_approved: false
  specialists:
    status: not_qualified
    qualification_task: R04
    owner_approved: false
document: task
scope: Sổ nhiệm vụ toàn dự án; G00–G03 và F01–F05 hoàn thành, task kế tiếp là F06-R1; D05 human gold bị
  owner bỏ qua.
tasks:
- id: G00
  requirement: REQ-GOV
  title: Chuẩn bị repository và gate nền tảng
  status: done
  note: 'Đã commit và merge PR #314 vào develop tại 873dd91; 41 test không training và bằng chứng chuẩn
    bị đã lưu.'
  evidence:
  - reports/verification/reorganization.json
  - configs/evaluation/foundation.yaml
- id: G01
  requirement: REQ-GOV
  title: Viết đặc tả hệ thống, kế hoạch và task dự án
  status: done
  note: Đã viết ba file Markdown đúng phạm vi hệ thống/dự án; cập nhật validator và tham chiếu; chưa thực
    hiện các task triển khai tiếp theo.
  evidence:
  - .agents/spec.md
  - .agents/plan.md
  - .agents/task.md
  - AGENTS.md
  - scripts/validate_work_plan.py
  - tests/contract/test_work_plan.py
- id: G02
  requirement: REQ-GOV
  title: Đối chiếu baseline, PR cũ và môi trường kiểm tra
  status: done
  note: Đã đối chiếu GitHub, 22 module và môi trường; sửa mô tả fertility/stage theo nguồn chuẩn; check-no-training
    PASS (49 test); không training, cài dependency hay đổi gate.
  evidence:
  - reports/verification/baseline-reconciliation.json
  - docs/plans/ROADMAP.md
  - docs/testing/BENCHMARK_PROTOCOL.md
  - docs/research/LANGUAGE_AND_MODEL_STRATEGY.md
  - docs/research/EMPIRICAL_STATUS.md
- id: G03
  requirement: REQ-GOV
  title: Chốt chính sách gate, quyền dữ liệu, gold và tiền điều kiện của owner
  status: done
  note: 'D01–D04, D06 đã xử lý: ViPubmed (STEM-VI) được owner cho dùng 2026-11-11 bất chấp license chưa rõ (dịch máy, không phải gold, chưa có quyền training), SciFact tải làm nguồn G12 EN (chờ owner ghi nhận license), DocLayNet chọn nguồn, OCR EN/VI đã cài. Owner mở lại
    D05 (2026-11-11) bắt đầu từ D05-a retrieval relevance; chưa có annotator được chỉ định nên chưa có
    nhãn, S01A/O01A/M01A vẫn blocked, F03 chỉ dùng relevance có sẵn; không training hay đổi gate.'
  evidence:
  - docs/training/PROJECT_PREREQUISITES.md
  - reports/verification/prerequisite-setup.json
- id: F01
  requirement: REQ-FND-EVAL
  title: Hoàn thiện metric QA và hợp đồng báo cáo
  status: done
  note: Đã thêm EM/F1 answer-text chuẩn hóa (đa đáp án, no-answer, truncation giữ và đếm), tách khỏi token-span;
    15 test mới, check-no-training PASS; chạy inference trên val mẫu, chưa phải bằng chứng qualification;
    không training.
  evidence:
  - src/laris/language/evaluation/evaluator.py
  - src/laris/language/evaluation/metrics.py
  - tests/unit/language/test_answer_metrics.py
  - reports/language_encoder/answer-text-validation-sample.json
- id: F02
  requirement: REQ-FND-EVAL
  title: Đo tokenizer fertility EN/VI trên dữ liệu unseen
  status: done
  note: 'Đã đo fertility EN/VI trên 4 nguồn test unseen (seed 42, kiểm trùng corpus fit, bootstrap CI):
    EN 1,420 và VI 1,363 đều FAIL G10/G11 (≤1,35); báo cáo hợp lệ cho readiness; 10 test mới, check-no-training
    PASS; không fit tokenizer hay training.'
  evidence:
  - src/laris/language/benchmarks/fertility.py
  - tests/unit/language/test_fertility.py
  - reports/tokenizer/fertility.json
- id: F03
  requirement: REQ-FND-EVAL
  title: Xây benchmark retrieval nền tảng độc lập
  status: done
  note: 'Đã đóng băng benchmark (SQuAD EN 7284 query/1338 đoạn; ViQuAD VI 1429/288, tách theo bài viết)
    và đo BM25/dense/hybrid: dense MRR 0,034 EN và 0,116 VI so với BM25 0,783 và 0,813; nguồn general-domain
    nên G12 vẫn MISSING; 16 test mới, check-no-training PASS; không training.'
  evidence:
  - src/laris/language/benchmarks/retrieval.py
  - configs/evaluation/foundation_retrieval.yaml
  - tests/unit/language/test_retrieval_benchmark.py
  - reports/retrieval/foundation.json
- id: F04
  requirement: REQ-FND-DATA
  title: Phân tích lỗi và chuẩn bị dữ liệu model 01
  status: done
  note: Đã đo lỗi validation trên 6 dataset và đối chiếu 18 shard với manifest. Phát hiện 5 cặp STS-B
    trùng train/test và 9 dòng ViQuAD có offset lệch. Đã ghi đối chiếu 12 gate và phương án sampling có
    SHA-256. 49 test không training và 42 test metric/retrieval PASS.
  evidence:
  - reports/language_encoder/foundation-error-analysis.json
  - configs/data/foundation_sampling.yaml
  - experiments/language_encoder/foundation_error_analysis.py
- id: F04A
  requirement: REQ-FND-TRAIN
  title: Chốt ngân sách compute, điều kiện dừng và nhánh tokenizer
  status: done
  note: Owner chốt tối đa 2 giờ GPU, 2 vòng × 2.000 bước, validation mỗi 500 bước, patience 3 theo loss
    validation trung bình và giữ tokenizer hiện tại cho chẩn đoán. Profiling đạt peak 3,64 GiB.
  evidence:
  - docs/training/FOUNDATION_BUDGET.md
  - reports/language_encoder/foundation-error-analysis.json
  - configs/data/foundation_sampling.yaml
- id: F05
  requirement: REQ-FND-TRAIN
  title: Chuẩn bị curriculum và lệnh train model 01
  status: done
  note: Đã nối sampler train và loss contrastive QA tùy chọn, kiểm khởi tạo từ checkpoint theo SHA-256
    và bàn giao hai vòng đối chứng sampling theo F04A. 49 test không training và 47 test tập trung PASS.
  evidence:
  - configs/language_encoder/compact.yaml
  - src/laris/cli/commands/language_encoder.py
  - src/laris/language/training/objectives.py
  - tests/unit/language/test_retrieval_objective.py
  - tests/cli/test_owner_runbook.py
  - docs/training/OWNER_RUNBOOK.md
- id: F06
  requirement: REQ-FND-TRAIN
  title: Chủ dự án train candidate model 01
  status: done
  note: Owner ủy quyền trực tiếp chạy F06. Hai smoke 10 bước và hai vòng chính 1.990 bước đã hoàn tất,
    peak log 3,9 GiB và tổng 37 phút 26 giây gồm validation. Checkpoint và validation đã đối chiếu SHA-256.
    Sampling có loss validation tốt nhất 0,221779 tại bước 1.500, baseline 0,222040 tại bước 1.990.
  evidence:
  - reports/language_encoder/foundation-owner-run.json
- id: F05-R1
  requirement: REQ-FND-TRAIN
  title: Chuẩn bị corpus và phép đo development cho tokenizer mới
  status: done
  note: 'Đã chuẩn bị 3.999.993 mục train từ bốn nguồn có SHA-256 và khóa 9.748 văn bản validation dùng
    chung. Fertility development của tokenizer cũ: EN 1,4417, VI 1,3442. Đã kiểm parser lệnh owner, 49
    test không training và 47 test tập trung PASS.'
  evidence:
  - docs/training/FOUNDATION_TOKENIZER_REMEDIATION.md
  - experiments/language_encoder/prepare_tokenizer_remediation.py
  - reports/tokenizer/foundation-r1-preparation.json
- id: F06-R1
  requirement: REQ-FND-TRAIN
  title: Fit tokenizer mới và chạy candidate foundation theo ngân sách mới
  status: blocked
  note: Chờ owner duyệt fit nhánh BPE 32k và ngân sách CPU. Sau so sánh validation, cần chốt tokenizer
    và ngân sách GPU mới trước khi huấn luyện encoder. Đo inference 2026-11-11, dense MRR 0,012 so với BM25 0,636 trên SciFact train; embedding CLS chưa học retrieval (trọng số 0), nên ngân sách GPU phải có giai đoạn contrastive (retrieval-loss-weight > 0) để G12 khả thi. Tokenizer 48k không tách chữ số đã fit và qua gate trên mẫu development (EN 1,300, VI 1,185); còn lại đổi vocab encoder lên 48000, đo lại profiling và chốt ngân sách GPU có giai đoạn contrastive.
  evidence:
  - docs/training/FOUNDATION_TOKENIZER_REMEDIATION.md
  - reports/tokenizer/foundation-r1-preparation.json
- id: F07
  requirement: REQ-FND-QUAL
  title: Nghiệm thu model 01 trên held-out test
  status: blocked
  note: Chưa qualified. G10 EN 1,420 và G11 VI 1,363 vượt 1,35. G12 có nguồn SciFact (relevance chuyên gia, 300 query) đã đóng băng digest nhưng chưa chấm; chưa có nguồn VI người gán. F06
    cung cấp validation cho G01–G09. Mở F05-R1 và F06-R1 trước khi nghiệm thu lại.
  evidence:
  - reports/language_encoder/foundation-qualification.json
  - reports/tokenizer/foundation-f07.json
- id: S01
  requirement: REQ-SCI
  title: Chuẩn bị corpus ngôn ngữ khoa học EN/VI
  status: pending
  note: ''
  evidence: []
- id: S01A
  requirement: REQ-SCI
  title: Gán nhãn gold khoa học và đo đồng thuận
  status: blocked
  note: 'D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định
    người gán và protocol rồi mới mở task.'
  evidence: []
- id: S02
  requirement: REQ-SCI
  title: Triển khai adaptation và inference model 02
  status: pending
  note: ''
  evidence: []
- id: S03
  requirement: REQ-SCI
  title: Chuẩn bị training/evaluation khoa học và evidence
  status: pending
  note: ''
  evidence: []
- id: S04
  requirement: REQ-SCI
  title: Chủ dự án train model 02
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
  evidence: []
- id: S05
  requirement: REQ-SCI
  title: Nghiệm thu ngôn ngữ khoa học
  status: pending
  note: ''
  evidence: []
- id: O01
  requirement: REQ-OCR
  title: Chuẩn hóa document schema và ánh xạ tọa độ
  status: pending
  note: ''
  evidence: []
- id: O01A
  requirement: REQ-OCR
  title: Chuẩn bị gold OCR/layout và toolchain đã duyệt
  status: blocked
  note: 'D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định
    người gán và protocol rồi mới mở task.'
  evidence: []
- id: O02
  requirement: REQ-OCR
  title: Triển khai dữ liệu, parser và OCR pipeline
  status: pending
  note: ''
  evidence: []
- id: O03
  requirement: REQ-OCR
  title: Chủ dự án train thành phần OCR cần học
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
  evidence: []
- id: O04
  requirement: REQ-OCR
  title: Nghiệm thu OCR và provenance vật lý
  status: pending
  note: ''
  evidence: []
- id: M01A
  requirement: REQ-MANUSCRIPT
  title: Gán nhãn gold discourse trên đầu ra OCR
  status: blocked
  note: 'D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định
    người gán và protocol rồi mới mở task.'
  evidence: []
- id: M01
  requirement: REQ-MANUSCRIPT
  title: Triển khai học cấu trúc bản thảo gắn OCR
  status: pending
  note: ''
  evidence: []
- id: M02
  requirement: REQ-MANUSCRIPT
  title: Chủ dự án train manuscript/discourse model
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
  evidence: []
- id: M03
  requirement: REQ-MANUSCRIPT
  title: Nghiệm thu discourse bản thảo
  status: pending
  note: ''
  evidence: []
- id: I01
  requirement: REQ-INTEGRATION
  title: Nối model thật, corpus, graph và hybrid retrieval
  status: pending
  note: ''
  evidence: []
- id: I02
  requirement: REQ-INTEGRATION
  title: Hoàn thiện orchestration và quản lý tài nguyên thật
  status: pending
  note: ''
  evidence: []
- id: I03
  requirement: REQ-INTEGRATION
  title: Tích hợp report và kiểm chứng evidence
  status: pending
  note: ''
  evidence: []
- id: I04
  requirement: REQ-INTEGRATION
  title: Nghiệm thu hệ thống tích hợp local
  status: pending
  note: ''
  evidence: []
- id: R01
  requirement: REQ-SPECIALISTS
  title: Hoàn thiện so sánh nghiên cứu và counter-evidence
  status: pending
  note: ''
  evidence: []
- id: R02
  requirement: REQ-SPECIALISTS
  title: Chuẩn bị specialist reasoning/generation và gold
  status: pending
  note: ''
  evidence: []
- id: R03
  requirement: REQ-SPECIALISTS
  title: Chủ dự án train specialist được duyệt
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
  evidence: []
- id: R04
  requirement: REQ-SPECIALISTS
  title: Nghiệm thu research gap và generation có kiểm chứng
  status: pending
  note: ''
  evidence: []
- id: P01
  requirement: REQ-PRODUCT
  title: Hoàn thiện giao diện và workflow người dùng
  status: pending
  note: ''
  evidence: []
- id: P02
  requirement: REQ-PRODUCT
  title: Thiết lập regression, feedback và vận hành
  status: pending
  note: ''
  evidence: []
- id: P03
  requirement: REQ-RELEASE
  title: Nghiệm thu và phát hành theo Git Flow
  status: pending
  note: ''
  evidence: []
---

# Nhiệm vụ dự án LARIS

## Quy ước

Nguồn yêu cầu: [spec.md](spec.md). Thứ tự/gate: [plan.md](plan.md). Mỗi task bên dưới
có owner, dependency, đầu ra và tiêu chí nghiệm thu trong YAML của plan; phần đọc
được ở đây lặp lại các thông tin thực thi quan trọng để review.

- `pending`: chưa làm; không có nghĩa đã đủ dependency để bắt đầu.
- `blocked`: chờ chủ dự án/thực thi training hoặc điều kiện ngoài quyền agent.
- `in_progress`: đang làm sau khi các dependency và stage gate hợp lệ.
- `done`: đã nghiệm thu task, có evidence/note, đã gạch và đối chứng ba file PASS.

G00–G03 và F01–F04 done. Các dòng chưa gạch là công việc dự án còn lại, không phải hứa
đã có model. G03 đã đóng; D05 human gold bị owner bỏ qua nên S01A, O01A, M01A blocked đến khi có annotator. F06 đã hoàn tất. Task kế tiếp là F06-R1. Task có hậu tố A (F04A, S01A, O01A, M01A) là bước bổ sung phát hiện khi thẩm định khả thi.

## Quản trị và baseline

- [x] ~~G00 — Chuẩn bị repository và gate nền tảng~~ — Note: Đã commit và merge PR #314 vào develop tại 873dd91; 41 test không training và bằng chứng chuẩn bị đã lưu.

  Người thực hiện: **agent**. Trạng thái: `done`. Phụ thuộc: không.

  Đầu ra: `reports/verification/reorganization.json`, `configs/evaluation/foundation.yaml`.

  Nghiệm thu: Đã merge #314 vào develop; cấu trúc và báo cáo baseline được bảo toàn.

- [x] ~~G01 — Viết đặc tả hệ thống, kế hoạch và task dự án~~ — Note: Đã viết ba file Markdown đúng phạm vi hệ thống/dự án; cập nhật validator và tham chiếu; chưa thực hiện các task triển khai tiếp theo.

  Người thực hiện: **agent**. Trạng thái: `done`. Phụ thuộc: G00.

  Đầu ra: `.agents/spec.md`, `.agents/plan.md`, `.agents/task.md`, `AGENTS.md`, `scripts/validate_work_plan.py`, `tests/contract/test_work_plan.py`.

  Nghiệm thu: Ba file Markdown đúng vai trò; validator, tham chiếu và các kiểm tra không training pass.

- [x] ~~G02 — Đối chiếu baseline, PR cũ và môi trường kiểm tra~~ — Note: Đã đối chiếu GitHub, 22 module và môi trường; sửa mô tả fertility/stage theo nguồn chuẩn; check-no-training PASS (49 test); không training, cài dependency hay đổi gate.

  Người thực hiện: **agent**. Trạng thái: `done`. Phụ thuộc: G01.

  Đầu ra: `reports/verification/baseline-reconciliation.json`.

  Nghiệm thu: Kiểm trạng thái GitHub thực tế của #310/#312 và các branch liên quan; liệt kê module benchmark/retrieval trùng chức năng; chốt nguồn chuẩn giữa ROADMAP.md và .agents (fertility 1,35 so với 1,4, milestone so với stage) và sửa tài liệu lệch; ghi môi trường (.venv, torch, sentencepiece, poppler) và thư viện OCR/PDF còn thiếu; chạy check-no-training; không đổi gate.

- [x] ~~G03 — Chốt chính sách gate, quyền dữ liệu, gold và tiền điều kiện của owner~~ — Note: D01–D04, D06 đã xử lý: ViPubmed (STEM-VI) được owner cho dùng 2026-11-11 bất chấp license chưa rõ (dịch máy, không phải gold, chưa có quyền training), SciFact tải làm nguồn G12 EN (chờ owner ghi nhận license), DocLayNet chọn nguồn, OCR EN/VI đã cài. Owner mở lại D05 (2026-11-11) bắt đầu từ D05-a retrieval relevance; chưa có annotator được chỉ định nên chưa có nhãn, S01A/O01A/M01A vẫn blocked, F03 chỉ dùng relevance có sẵn; không training hay đổi gate.

  Người thực hiện: **joint**. Trạng thái: `done`. Phụ thuộc: G02.

  Đầu ra: `docs/training/PROJECT_PREREQUISITES.md`.

  Nghiệm thu: Ghi chính sách mặc định: giữ nguyên 12 gate và ADR-002, agent không nới gate; liệt kê theo stage nguồn dữ liệu cần có (SciFact, khóa S2ORC, dữ liệu STEM tiếng Việt, dữ liệu OCR), đối chiếu approval dùng đã có (ViNLI, ViQuAD, CC-100) và phần NEEDS_LICENSE_REVIEW còn thiếu, không hủy hoặc mở rộng approval hiện có, người gán nhãn và ngưỡng đồng thuận cho gold, thư viện OCR/PDF được phép cài; owner xác nhận từng mục hoặc ghi rõ mục bị chặn.


## Model 01 — ngôn ngữ tự nhiên

- [x] ~~F01 — Hoàn thiện metric QA và hợp đồng báo cáo~~ — Note: Đã thêm EM/F1 answer-text chuẩn hóa (đa đáp án, no-answer, truncation giữ và đếm), tách khỏi token-span; 15 test mới, check-no-training PASS; chạy inference trên val mẫu, chưa phải bằng chứng qualification; không training.

  Người thực hiện: **agent**. Trạng thái: `done`. Phụ thuộc: G03.

  Đầu ra: `src/laris/language/evaluation/evaluator.py`, `src/laris/language/evaluation/metrics.py`, `tests/unit/language/test_answer_metrics.py`.

  Nghiệm thu: EM/F1 theo answer-text chuẩn hóa; xử lý đa đáp án, no-answer, truncation; không nhầm token-span với answer-text; provenance/protocol được ghi.

- [x] ~~F02 — Đo tokenizer fertility EN/VI trên dữ liệu unseen~~ — Note: Đã đo fertility EN/VI trên 4 nguồn test unseen (seed 42, kiểm trùng corpus fit, bootstrap CI): EN 1,420 và VI 1,363 đều FAIL G10/G11 (≤1,35); báo cáo hợp lệ cho readiness; 10 test mới, check-no-training PASS; không fit tokenizer hay training.

  Người thực hiện: **agent**. Trạng thái: `done`. Phụ thuộc: F01.

  Đầu ra: `src/laris/language/benchmarks/fertility.py`, `tests/unit/language/test_fertility.py`, `reports/tokenizer/fertility.json`.

  Nghiệm thu: Tách EN/VI; định nghĩa word/token rõ ràng; corpus unseen có manifest, chống leakage và report tương thích readiness. Nếu fertility vượt gate, ghi đề xuất tokenizer cho F04A; agent không fit tokenizer.

- [x] ~~F03 — Xây benchmark retrieval nền tảng độc lập~~ — Note: Đã đóng băng benchmark (SQuAD EN 7284 query/1338 đoạn; ViQuAD VI 1429/288, tách theo bài viết) và đo BM25/dense/hybrid: dense MRR 0,034 EN và 0,116 VI so với BM25 0,783 và 0,813; nguồn general-domain nên G12 vẫn MISSING; 16 test mới, check-no-training PASS; không training.

  Người thực hiện: **agent**. Trạng thái: `done`. Phụ thuộc: F02.

  Đầu ra: `src/laris/language/benchmarks/retrieval.py`, `configs/evaluation/foundation_retrieval.yaml`, `tests/unit/language/test_retrieval_benchmark.py`, `reports/retrieval/foundation.json`.

  Nghiệm thu: Đóng băng query/relevance và split; đo MRR/nDCG, BM25/dense/hybrid, hard negatives; không dùng pilot sáu query để thay gate. Băng hash query/relevance trước khi đo model; ngưỡng không chỉnh sau khi thấy kết quả; query không lấy từ dữ liệu train. D05 bị owner bỏ qua nên không có annotator: chỉ dùng relevance do người gán đã có sẵn từ nguồn công khai đã xác minh quyền sử dụng; không tự sinh relevance. Nếu không có nguồn như vậy, G12 giữ MISSING và F07 không qualify.

- [x] ~~F04 — Phân tích lỗi và chuẩn bị dữ liệu model 01~~ — Note: Đã đo lỗi validation trên 6 dataset và đối chiếu 18 shard với manifest. Phát hiện 5 cặp STS-B trùng train/test và 9 dòng ViQuAD có offset lệch. Đã ghi đối chiếu 12 gate và phương án sampling có SHA-256. 49 test không training và 42 test metric/retrieval PASS.

  Người thực hiện: **agent**. Trạng thái: `done`. Phụ thuộc: F03.

  Đầu ra: `reports/language_encoder/foundation-error-analysis.json`, `configs/data/foundation_sampling.yaml`.

  Nghiệm thu: Lỗi ANLI, ViNLI, PAWS, STS, QA phân theo dataset/ngôn ngữ; kiểm nhãn, phân bố, leakage; thay đổi dữ liệu có checksum và lý do. Đánh giá khả thi từng gate dựa trên số đã đo, không dự đoán không có căn cứ.

- [x] ~~F04A — Chốt ngân sách compute, điều kiện dừng và nhánh tokenizer~~ — Note: Owner chốt tối đa 2 giờ GPU, 2 vòng × 2.000 bước, validation mỗi 500 bước, patience 3 theo loss validation trung bình và giữ tokenizer hiện tại cho chẩn đoán. Profiling đạt peak 3,64 GiB.

  Người thực hiện: **joint**. Trạng thái: `done`. Phụ thuộc: F04.

  Đầu ra: `docs/training/FOUNDATION_BUDGET.md`.

  Nghiệm thu: Owner cung cấp throughput và VRAM đo thật từ profiling do owner chạy; chốt số bước/giờ GPU tối đa, số vòng thử tối đa và điều kiện dừng; quyết định giữ hay fit lại tokenizer (fit lại làm vô hiệu checkpoint hiện có và phải ghi vào lineage); đánh giá khả thi từng gate từ learning curve đã đo; nếu gate không đạt trong ngân sách, owner chọn tiếp tục, dừng hoặc mở sửa gate qua ADR có lý do, agent không tự giảm gate. Đầu vào bắt buộc: fertility F02 hiện FAIL cả EN (1,420) và VI (1,363) theo định nghĩa macro-source đã cố định trước khi đo; quyết định tokenizer dựa trên số này, không đổi định nghĩa để qua gate.


- [x] ~~F05 — Chuẩn bị curriculum và lệnh train model 01~~ — Note: Đã nối sampler train và loss contrastive QA tùy chọn, kiểm khởi tạo từ checkpoint theo SHA-256 và bàn giao hai vòng đối chứng sampling theo F04A. 49 test không training và 47 test tập trung PASS.

  Người thực hiện: **agent**. Trạng thái: `done`. Phụ thuộc: F04A.

  Đầu ra: `configs/language_encoder/compact.yaml`, `src/laris/language/training/objectives.py`, `tests/unit/language/test_retrieval_objective.py`, `docs/training/OWNER_RUNBOOK.md`.

  Nghiệm thu: Chốt objective/sampling/loss, ablation và ngân sách theo F04A; thêm objective contrastive cho retrieval (G12 cần vượt BM25) kèm test chỉ tính giá trị loss, không backward; cấu hình khớp parser/checkpoint; chỉ xuất lệnh, không fitting/backward/optimizer. Đầu vào bắt buộc từ F03: dense MRR hiện 0,034 (EN) và 0,116 (VI), thấp hơn BM25 (0,783 và 0,813); kiểm tra đối chứng cho thấy pipeline đúng, nên cần objective retrieval, không phải sửa đo lường.

- [x] ~~F06 — Chủ dự án train candidate model 01~~ — Note: Owner ủy quyền trực tiếp chạy F06. Hai smoke 10 bước và hai vòng chính 1.990 bước đã hoàn tất, peak log 3,9 GiB và tổng 37 phút 26 giây gồm validation. Checkpoint và validation đã đối chiếu SHA-256. Sampling có loss validation tốt nhất 0,221779 tại bước 1.500, baseline 0,222040 tại bước 1.990.

  Người thực hiện: **owner**. Trạng thái: `done`. Phụ thuộc: F05.

  Đầu ra: `reports/language_encoder/foundation-owner-run.json`.

  Nghiệm thu: Chạy smoke ngắn và trả kết quả trước khi chạy dài; chủ dự án tự profile/train; trả manifest, cấu hình, log, checkpoint digest và validation; không commit weights.


- [x] ~~F05-R1 — Chuẩn bị corpus và phép đo development cho tokenizer mới~~ — Note: Đã chuẩn bị 3.999.993 mục train từ bốn nguồn có SHA-256 và khóa 9.748 văn bản validation dùng chung. Fertility development của tokenizer cũ: EN 1,4417, VI 1,3442. Đã kiểm parser lệnh owner, 49 test không training và 47 test tập trung PASS.

  Người thực hiện: **agent**. Trạng thái: `done`. Phụ thuộc: F06.

  Đầu ra: `docs/training/FOUNDATION_TOKENIZER_REMEDIATION.md`, `experiments/language_encoder/prepare_tokenizer_remediation.py`, `reports/tokenizer/foundation-r1-preparation.json`.

  Nghiệm thu: Chuẩn bị corpus từ train đã xác minh checksum, giữ tokenizer/checkpoint gốc. Khóa protocol validation để so ứng viên cùng 32k trước khi dùng test. Ghi rõ gate, lineage, nguồn dữ liệu còn thiếu và quyết định ngân sách cần owner.

- [ ] F06-R1 — Fit tokenizer mới và chạy candidate foundation theo ngân sách mới

  Người thực hiện: **owner**. Trạng thái: `blocked`. Phụ thuộc: F05-R1.

  Đầu ra: `reports/language_encoder/foundation-owner-run-r1.json`.

  Nghiệm thu: Owner chọn nhánh và duyệt ngân sách mới. Fit tokenizer từ train, so trên validation, chốt tokenizer trước khi chấm test. Huấn luyện encoder với lineage mới và bàn giao manifest, log, checksum, validation.

  Note: Chờ owner duyệt fit nhánh BPE 32k và ngân sách CPU. Sau so sánh validation, cần chốt tokenizer và ngân sách GPU mới trước khi huấn luyện encoder. Đo inference 2026-11-11, dense MRR 0,012 so với BM25 0,636 trên SciFact train; embedding CLS chưa học retrieval (trọng số 0), nên ngân sách GPU phải có giai đoạn contrastive (retrieval-loss-weight > 0) để G12 khả thi. Tokenizer 48k không tách chữ số đã fit và qua gate trên mẫu development (EN 1,300, VI 1,185); còn lại đổi vocab encoder lên 48000, đo lại profiling và chốt ngân sách GPU có giai đoạn contrastive.

- [ ] F07 — Nghiệm thu model 01 trên held-out test

  Người thực hiện: **joint**. Trạng thái: `blocked`. Phụ thuộc: F06 và F06-R1.

  Đầu ra: `reports/language_encoder/foundation-qualification.json`.

  Nghiệm thu: Đủ 12 gate, protocol đúng, cùng model/tokenizer, nguồn test độc lập và được chủ dự án duyệt; thiếu bất kỳ gate nào thì không promote. Nếu gate fail, mở vòng sửa theo mục 7 của plan; không gạch F07. G12 dùng nguồn STEM có relevance do người gán (SciFact, đã đóng băng, chờ owner ghi nhận license; VI chưa có): nguồn general-domain của F03 không được dùng thay.

  Note: Chưa qualified. G10 EN 1,420 và G11 VI 1,363 vượt 1,35. G12 có nguồn SciFact (relevance chuyên gia, 300 query) đã đóng băng digest nhưng chưa chấm; chưa có nguồn VI người gán. F06 cung cấp validation cho G01–G09. Mở F05-R1 và F06-R1 trước khi nghiệm thu lại.


## Model 02 — ngôn ngữ khoa học

- [ ] S01 — Chuẩn bị corpus ngôn ngữ khoa học EN/VI

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: F07.

  Đầu ra: `docs/specifications/SCIENTIFIC_LANGUAGE_SPECIFICATION.md`, `reports/scientific_language/data-readiness.json`.

  Nghiệm thu: Nguồn/quyền sử dụng rõ, split theo document/family, nhãn NLI/evidence/discourse có audit; ghi thiếu dữ liệu VI thay vì giả định đủ. Gồm thu thập SciFact và nguồn STEM theo G03; ghi chặn nếu thiếu quyền truy cập thay vì dùng dữ liệu thay thế.

- [ ] S01A — Gán nhãn gold khoa học và đo đồng thuận

  Người thực hiện: **joint**. Trạng thái: `blocked`. Phụ thuộc: S01.

  Đầu ra: `reports/scientific_language/gold-audit.json`.

  Nghiệm thu: Nhãn NLI/evidence/discourse khoa học do người gán theo guideline; có inter-annotator agreement, split theo document/family và tách khỏi dữ liệu train; agent không tự sinh nhãn gold.

  Note: D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định người gán và protocol rồi mới mở task.

- [ ] S02 — Triển khai adaptation và inference model 02

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: S01A.

  Đầu ra: `src/laris/scientific/language/model.py`, `tests/contract/test_scientific_language.py`.

  Nghiệm thu: Khởi tạo từ foundation đã qualified theo thiết kế được duyệt; tokenizer lineage, thuật ngữ, phủ định, số/đơn vị và điều kiện được giữ; không dùng foundation pretrained bên ngoài.

- [ ] S03 — Chuẩn bị training/evaluation khoa học và evidence

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: S02.

  Đầu ra: `src/laris/scientific/training/runner.py`, `configs/evaluation/scientific_language.yaml`, `docs/training/SCIENTIFIC_LANGUAGE_RUNBOOK.md`.

  Nghiệm thu: Code/lệnh train và evaluator SciFact/evidence/discourse có contract và fixture; không optimizer do agent; labels và phép đo độc lập với model.

- [ ] S04 — Chủ dự án train model 02

  Người thực hiện: **owner**. Trạng thái: `blocked`. Phụ thuộc: S03.

  Đầu ra: `reports/scientific_language/owner-run.json`.

  Nghiệm thu: Chạy smoke ngắn và trả kết quả trước khi chạy dài; chủ dự án tự train, trả artifacts/provenance và validation theo cấu hình đã chốt.

  Note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.

- [ ] S05 — Nghiệm thu ngôn ngữ khoa học

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: S04.

  Đầu ra: `reports/scientific_language/qualification.json`.

  Nghiệm thu: SciFact NLI macro F1 >= 0.82; evidence precision và recall >= 0.80 theo đặc tả; kiểm phủ định/điều kiện/đơn vị và regression foundation.


## Scientific OCR và document intelligence

- [ ] O01 — Chuẩn hóa document schema và ánh xạ tọa độ

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: S05.

  Đầu ra: `docs/specifications/DOCUMENT_INTELLIGENCE_SPECIFICATION.md`.

  Nghiệm thu: Chốt page/block/paragraph/sentence/char coordinates, reading order, hash nguồn và canonical text; không nhận diện layout chỉ bằng heading.

- [ ] O01A — Chuẩn bị gold OCR/layout và toolchain đã duyệt

  Người thực hiện: **joint**. Trạng thái: `blocked`. Phụ thuộc: O01.

  Đầu ra: `reports/documents/ocr-gold-audit.json`.

  Nghiệm thu: Gold text/layout clean và degraded do người kiểm; toolchain OCR/PDF đã được owner duyệt ở G03 và cài vào môi trường; có audit/agreement; không dùng output OCR làm gold.

  Note: D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định người gán và protocol rồi mới mở task.

- [ ] O02 — Triển khai dữ liệu, parser và OCR pipeline

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: O01A.

  Đầu ra: `src/laris/documents/parsing.py`, `src/laris/documents/ocr.py`, `docs/training/OCR_RUNBOOK.md`.

  Nghiệm thu: Dữ liệu clean/degraded có gold; phân biệt text-native/scanned; giữ order, công thức, bảng/hình và đánh dấu phần chưa hỗ trợ; code và lệnh, không train.

- [ ] O03 — Chủ dự án train thành phần OCR cần học

  Người thực hiện: **owner**. Trạng thái: `blocked`. Phụ thuộc: O02.

  Đầu ra: `reports/documents/ocr-owner-run.json`.

  Nghiệm thu: Chạy smoke ngắn và trả kết quả trước khi chạy dài; chủ dự án thực thi training đã duyệt; trả checkpoint/dataset lineage và measurements.

  Note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.

- [ ] O04 — Nghiệm thu OCR và provenance vật lý

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: O03.

  Đầu ra: `reports/documents/ocr-qualification.json`.

  Nghiệm thu: CER <= 1.5% clean, <= 3.0% degraded; layout IoU >= 0.88; audit reading order và span mapping, gồm lỗi hai cột đã thấy ở pilot.


## Manuscript/discourse learning

- [ ] M01A — Gán nhãn gold discourse trên đầu ra OCR

  Người thực hiện: **joint**. Trạng thái: `blocked`. Phụ thuộc: O04.

  Đầu ra: `reports/documents/discourse-gold-audit.json`.

  Nghiệm thu: Gold discourse-role có tọa độ do người gán trên đầu ra OCR; có agreement, split theo document và heading-stripped subset; agent không tự sinh nhãn gold.

  Note: D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định người gán và protocol rồi mới mở task.

- [ ] M01 — Triển khai học cấu trúc bản thảo gắn OCR

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: M01A.

  Đầu ra: `src/laris/documents/discourse.py`, `docs/training/MANUSCRIPT_LEARNING_RUNBOOK.md`.

  Nghiệm thu: Dữ liệu discourse-role có gold/coordinate; code học claim/method/result/limitation trên đầu ra OCR; heading-stripped tests; không lẫn với viết manuscript.

- [ ] M02 — Chủ dự án train manuscript/discourse model

  Người thực hiện: **owner**. Trạng thái: `blocked`. Phụ thuộc: M01.

  Đầu ra: `reports/documents/manuscript-owner-run.json`.

  Nghiệm thu: Chạy smoke ngắn và trả kết quả trước khi chạy dài; chủ dự án tự train theo lệnh, trả log, provenance và validation.

  Note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.

- [ ] M03 — Nghiệm thu discourse bản thảo

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: M02.

  Đầu ra: `reports/documents/manuscript-qualification.json`.

  Nghiệm thu: Discourse-role macro F1 >= 0.82; audit lỗi OCR truyền xuống, heading-independent extraction và giữ giá trị/số/đơn vị.


## Tích hợp hệ thống local

- [ ] I01 — Nối model thật, corpus, graph và hybrid retrieval

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: M03.

  Đầu ra: `tests/integration/test_qualified_model_pipeline.py`.

  Nghiệm thu: Dùng artifacts đã qualified, adapters đúng dimension/provenance; SQLite persistence/cache hoạt động; không synthetic executor trong đường chạy chứng nhận.

- [ ] I02 — Hoàn thiện orchestration và quản lý tài nguyên thật

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: I01.

  Đầu ra: `tests/integration/test_real_specialist_execution.py`.

  Nghiệm thu: DAG có budget/cycle/cancellation/failure propagation; model loader/offload thật và telemetry thực; simulation phải được gắn nhãn.

- [ ] I03 — Tích hợp report và kiểm chứng evidence

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: I02.

  Đầu ra: `tests/integration/test_supported_research_report.py`.

  Nghiệm thu: Mỗi assertion có nguồn và phạm vi hỗ trợ; kiểm hash/span, mức hỗ trợ và abstention; trích đúng nguồn không tự đồng nghĩa kết luận đúng.

- [ ] I04 — Nghiệm thu hệ thống tích hợp local

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: I03.

  Đầu ra: `reports/integration/qualification.json`.

  Nghiệm thu: Chạy end-to-end trên bộ bài báo thật sau các stage trước; VRAM full-load <= 15.0 GB; có audit chất lượng/latency/lỗi, không lấy synthetic benchmark làm chứng nhận.


## Reasoning, verification và generation specialists

- [ ] R01 — Hoàn thiện so sánh nghiên cứu và counter-evidence

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: I04.

  Đầu ra: `tests/integration/test_cross_paper_counter_evidence.py`.

  Nghiệm thu: So sánh chỉ khi điều kiện/đơn vị/metric tương thích; tách mâu thuẫn thực với khác setup; truy xuất phản chứng và giới hạn phạm vi.

- [ ] R02 — Chuẩn bị specialist reasoning/generation và gold

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: R01.

  Đầu ra: `docs/specifications/SPECIALIST_LEARNING_SPECIFICATION.md`, `docs/training/SPECIALIST_RUNBOOK.md`.

  Nghiệm thu: Chốt từng specialist, dữ liệu/gold, objective, protocol, gate và lệnh owner; nguồn synthetic phải tách benchmark độc lập; không mặc định benchmark score. Gold do người gán theo D05; nếu D05 vẫn bị bỏ qua, specialist cần gold ghi blocked, không dùng gold tự sinh.

- [ ] R03 — Chủ dự án train specialist được duyệt

  Người thực hiện: **owner**. Trạng thái: `blocked`. Phụ thuộc: R02.

  Đầu ra: `reports/specialists/owner-runs.json`.

  Nghiệm thu: Chạy smoke ngắn và trả kết quả trước khi chạy dài; chủ dự án thực thi từng run được duyệt và trả artifacts/validation; không train tự phát hoặc cập nhật online khi chạy nghiên cứu.

  Note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.

- [ ] R04 — Nghiệm thu research gap và generation có kiểm chứng

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: R03.

  Đầu ra: `reports/specialists/qualification.json`.

  Nghiệm thu: Đạt gate đã chốt ở R02; bác gap đã được giải/không đủ chứng cứ; tách author limitation, candidate và reviewed gap; manuscript chỉ tạo khi yêu cầu.


## Sản phẩm, vận hành và phát hành

- [ ] P01 — Hoàn thiện giao diện và workflow người dùng

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: R04.

  Đầu ra: `docs/development/USER_GUIDE.md`.

  Nghiệm thu: Tạo project, nhập corpus/query, xem nguồn/counter-evidence/caveat, xuất report, resume; UI không che uncertainty hoặc bịa tiến độ capability.

- [ ] P02 — Thiết lập regression, feedback và vận hành

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: P01.

  Đầu ra: `docs/development/OPERATIONS.md`.

  Nghiệm thu: Corpus/checkpoint/report lineage, cache invalidation, recovery, regression và feedback có provenance; không đưa test vào training hoặc học online trái phép.

- [ ] P03 — Nghiệm thu và phát hành theo Git Flow

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: P02.

  Đầu ra: `reports/release/acceptance.json`.

  Nghiệm thu: Cài mới/smoke/E2E/quality/resource gates pass; tài liệu/user commands đủ; đóng issue/PR theo evidence; release/main chỉ khi chủ dự án phê duyệt.
