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
next_task: G02
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
scope: Sổ nhiệm vụ toàn dự án; chỉ G00/G01 hoàn thành, chưa khởi chạy G02.
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
  status: pending
  note: ''
  evidence: []
- id: G03
  requirement: REQ-GOV
  title: Chốt chính sách gate, quyền dữ liệu, gold và tiền điều kiện của owner
  status: pending
  note: ''
  evidence: []
- id: F01
  requirement: REQ-FND-EVAL
  title: Hoàn thiện metric QA và hợp đồng báo cáo
  status: pending
  note: ''
  evidence: []
- id: F02
  requirement: REQ-FND-EVAL
  title: Đo tokenizer fertility EN/VI trên dữ liệu unseen
  status: pending
  note: ''
  evidence: []
- id: F03
  requirement: REQ-FND-EVAL
  title: Xây benchmark retrieval nền tảng độc lập
  status: pending
  note: ''
  evidence: []
- id: F04
  requirement: REQ-FND-DATA
  title: Phân tích lỗi và chuẩn bị dữ liệu model 01
  status: pending
  note: ''
  evidence: []
- id: F04A
  requirement: REQ-FND-TRAIN
  title: Chốt ngân sách compute, điều kiện dừng và nhánh tokenizer
  status: pending
  note: ''
  evidence: []
- id: F05
  requirement: REQ-FND-TRAIN
  title: Chuẩn bị curriculum và lệnh train model 01
  status: pending
  note: ''
  evidence: []
- id: F06
  requirement: REQ-FND-TRAIN
  title: Chủ dự án train candidate model 01
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
  evidence: []
- id: F07
  requirement: REQ-FND-QUAL
  title: Nghiệm thu model 01 trên held-out test
  status: pending
  note: ''
  evidence: []
- id: S01
  requirement: REQ-SCI
  title: Chuẩn bị corpus ngôn ngữ khoa học EN/VI
  status: pending
  note: ''
  evidence: []
- id: S01A
  requirement: REQ-SCI
  title: Gán nhãn gold khoa học và đo đồng thuận
  status: pending
  note: ''
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
  status: pending
  note: ''
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
  status: pending
  note: ''
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

Chỉ G00/G01 done. Các dòng chưa gạch là công việc dự án còn lại, không phải hứa
đã có model. Lần này chỉ sửa tài liệu; chưa bắt đầu G02 hay F01 và không chạy training. Task có hậu tố A (F04A, S01A, O01A, M01A) là bước bổ sung phát hiện khi thẩm định khả thi.

## Quản trị và baseline

- [x] ~~G00 — Chuẩn bị repository và gate nền tảng~~ — Note: Đã commit và merge PR #314 vào develop tại 873dd91; 41 test không training và bằng chứng chuẩn bị đã lưu.

  Người thực hiện: **agent**. Trạng thái: `done`. Phụ thuộc: không.

  Đầu ra: `reports/verification/reorganization.json`, `configs/evaluation/foundation.yaml`.

  Nghiệm thu: Đã merge #314 vào develop; cấu trúc và báo cáo baseline được bảo toàn.

- [x] ~~G01 — Viết đặc tả hệ thống, kế hoạch và task dự án~~ — Note: Đã viết ba file Markdown đúng phạm vi hệ thống/dự án; cập nhật validator và tham chiếu; chưa thực hiện các task triển khai tiếp theo.

  Người thực hiện: **agent**. Trạng thái: `done`. Phụ thuộc: G00.

  Đầu ra: `.agents/spec.md`, `.agents/plan.md`, `.agents/task.md`, `AGENTS.md`, `scripts/validate_work_plan.py`, `tests/contract/test_work_plan.py`.

  Nghiệm thu: Ba file Markdown đúng vai trò; validator, tham chiếu và các kiểm tra không training pass.

- [ ] G02 — Đối chiếu baseline, PR cũ và môi trường kiểm tra

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: G01.

  Đầu ra: `reports/verification/baseline-reconciliation.json`.

  Nghiệm thu: Kiểm trạng thái GitHub thực tế của #310/#312 và các branch liên quan; liệt kê module benchmark/retrieval trùng chức năng; chốt nguồn chuẩn giữa ROADMAP.md và .agents (fertility 1,35 so với 1,4, milestone so với stage) và sửa tài liệu lệch; ghi môi trường (.venv, torch, sentencepiece, poppler) và thư viện OCR/PDF còn thiếu; chạy check-no-training; không đổi gate.

- [ ] G03 — Chốt chính sách gate, quyền dữ liệu, gold và tiền điều kiện của owner

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: G02.

  Đầu ra: `docs/training/PROJECT_PREREQUISITES.md`.

  Nghiệm thu: Ghi chính sách mặc định: giữ nguyên 12 gate và ADR-002, agent không nới gate; liệt kê theo stage nguồn dữ liệu cần có (SciFact, khóa S2ORC, dữ liệu STEM tiếng Việt, dữ liệu OCR), quyết định giấy phép đang NEEDS_LICENSE_REVIEW (ViNLI, ViQuAD, CC-100), người gán nhãn và ngưỡng đồng thuận cho gold, thư viện OCR/PDF được phép cài; owner xác nhận từng mục hoặc ghi rõ mục bị chặn.


## Model 01 — ngôn ngữ tự nhiên

- [ ] F01 — Hoàn thiện metric QA và hợp đồng báo cáo

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: G03.

  Đầu ra: `src/laris/language/evaluation/evaluator.py`, `tests/unit/language/test_answer_metrics.py`.

  Nghiệm thu: EM/F1 theo answer-text chuẩn hóa; xử lý đa đáp án, no-answer, truncation; không nhầm token-span với answer-text; provenance/protocol được ghi.

- [ ] F02 — Đo tokenizer fertility EN/VI trên dữ liệu unseen

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: F01.

  Đầu ra: `src/laris/language/benchmarks/fertility.py`, `reports/tokenizer/fertility.json`.

  Nghiệm thu: Tách EN/VI; định nghĩa word/token rõ ràng; corpus unseen có manifest, chống leakage và report tương thích readiness. Nếu fertility vượt gate, ghi đề xuất tokenizer cho F04A; agent không fit tokenizer.

- [ ] F03 — Xây benchmark retrieval nền tảng độc lập

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: F02.

  Đầu ra: `src/laris/language/benchmarks/retrieval.py`, `configs/evaluation/foundation_retrieval.yaml`.

  Nghiệm thu: Đóng băng query/relevance và split; đo MRR/nDCG, BM25/dense/hybrid, hard negatives; không dùng pilot sáu query để thay gate. Băng hash query/relevance trước khi đo model; ngưỡng không chỉnh sau khi thấy kết quả; query không lấy từ dữ liệu train.

- [ ] F04 — Phân tích lỗi và chuẩn bị dữ liệu model 01

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: F03.

  Đầu ra: `reports/language_encoder/foundation-error-analysis.json`, `configs/data/foundation_sampling.yaml`.

  Nghiệm thu: Lỗi ANLI, ViNLI, PAWS, STS, QA phân theo dataset/ngôn ngữ; kiểm nhãn, phân bố, leakage; thay đổi dữ liệu có checksum và lý do. Đánh giá khả thi từng gate dựa trên số đã đo, không dự đoán không có căn cứ.

- [ ] F04A — Chốt ngân sách compute, điều kiện dừng và nhánh tokenizer

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: F04.

  Đầu ra: `docs/training/FOUNDATION_BUDGET.md`.

  Nghiệm thu: Owner cung cấp throughput và VRAM đo thật từ profiling do owner chạy; chốt số bước/giờ GPU tối đa, số vòng thử tối đa và điều kiện dừng; quyết định giữ hay fit lại tokenizer (fit lại làm vô hiệu checkpoint hiện có và phải ghi vào lineage); đánh giá khả thi từng gate từ learning curve đã đo; nếu gate không đạt trong ngân sách, owner chọn tiếp tục, dừng hoặc mở sửa gate qua ADR có lý do, agent không tự giảm gate.

- [ ] F05 — Chuẩn bị curriculum và lệnh train model 01

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: F04A.

  Đầu ra: `configs/language_encoder/compact.yaml`, `src/laris/language/training/objectives.py`, `tests/unit/language/test_retrieval_objective.py`, `docs/training/OWNER_RUNBOOK.md`.

  Nghiệm thu: Chốt objective/sampling/loss, ablation và ngân sách theo F04A; thêm objective contrastive cho retrieval (G12 cần vượt BM25) kèm test chỉ tính giá trị loss, không backward; cấu hình khớp parser/checkpoint; chỉ xuất lệnh, không fitting/backward/optimizer.

- [ ] F06 — Chủ dự án train candidate model 01

  Người thực hiện: **owner**. Trạng thái: `blocked`. Phụ thuộc: F05.

  Đầu ra: `reports/language_encoder/foundation-owner-run.json`.

  Nghiệm thu: Chạy smoke ngắn và trả kết quả trước khi chạy dài; chủ dự án tự profile/train; trả manifest, cấu hình, log, checkpoint digest và validation; không commit weights.

  Note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.

- [ ] F07 — Nghiệm thu model 01 trên held-out test

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: F06.

  Đầu ra: `reports/language_encoder/foundation-qualification.json`.

  Nghiệm thu: Đủ 12 gate, protocol đúng, cùng model/tokenizer, nguồn test độc lập và được chủ dự án duyệt; thiếu bất kỳ gate nào thì không promote. Nếu gate fail, mở vòng sửa theo mục 7 của plan; không gạch F07.


## Model 02 — ngôn ngữ khoa học

- [ ] S01 — Chuẩn bị corpus ngôn ngữ khoa học EN/VI

  Người thực hiện: **agent**. Trạng thái: `pending`. Phụ thuộc: F07.

  Đầu ra: `docs/specifications/SCIENTIFIC_LANGUAGE_SPECIFICATION.md`, `reports/scientific_language/data-readiness.json`.

  Nghiệm thu: Nguồn/quyền sử dụng rõ, split theo document/family, nhãn NLI/evidence/discourse có audit; ghi thiếu dữ liệu VI thay vì giả định đủ. Gồm thu thập SciFact và nguồn STEM theo G03; ghi chặn nếu thiếu quyền truy cập thay vì dùng dữ liệu thay thế.

- [ ] S01A — Gán nhãn gold khoa học và đo đồng thuận

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: S01.

  Đầu ra: `reports/scientific_language/gold-audit.json`.

  Nghiệm thu: Nhãn NLI/evidence/discourse khoa học do người gán theo guideline; có inter-annotator agreement, split theo document/family và tách khỏi dữ liệu train; agent không tự sinh nhãn gold.

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

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: O01.

  Đầu ra: `reports/documents/ocr-gold-audit.json`.

  Nghiệm thu: Gold text/layout clean và degraded do người kiểm; toolchain OCR/PDF đã được owner duyệt ở G03 và cài vào môi trường; có audit/agreement; không dùng output OCR làm gold.

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

  Người thực hiện: **joint**. Trạng thái: `pending`. Phụ thuộc: O04.

  Đầu ra: `reports/documents/discourse-gold-audit.json`.

  Nghiệm thu: Gold discourse-role có tọa độ do người gán trên đầu ra OCR; có agreement, split theo document và heading-stripped subset; agent không tự sinh nhãn gold.

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

  Nghiệm thu: Chốt từng specialist, dữ liệu/gold, objective, protocol, gate và lệnh owner; nguồn synthetic phải tách benchmark độc lập; không mặc định benchmark score.

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
