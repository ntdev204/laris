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
document: plan
scope: Kế hoạch tiếp tục dự án theo phụ thuộc và gate nghiệm thu.
steps:
- id: G00
  requirement: REQ-GOV
  stage: governance
  owner: agent
  operation: engineering
  title: Chuẩn bị repository và gate nền tảng
  depends_on: []
  deliverables:
  - reports/verification/reorganization.json
  - configs/evaluation/foundation.yaml
  acceptance: 'Đã merge #314 vào develop; cấu trúc và báo cáo baseline được bảo toàn.'
  status: done
  note: 'Đã commit và merge PR #314 vào develop tại 873dd91; 41 test không training và bằng chứng chuẩn
    bị đã lưu.'
- id: G01
  requirement: REQ-GOV
  stage: governance
  owner: agent
  operation: documentation
  title: Viết đặc tả hệ thống, kế hoạch và task dự án
  depends_on:
  - G00
  deliverables:
  - .agents/spec.md
  - .agents/plan.md
  - .agents/task.md
  - AGENTS.md
  - scripts/validate_work_plan.py
  - tests/contract/test_work_plan.py
  acceptance: Ba file Markdown đúng vai trò; validator, tham chiếu và các kiểm tra không training pass.
  status: done
  note: Đã viết ba file Markdown đúng phạm vi hệ thống/dự án; cập nhật validator và tham chiếu; chưa thực
    hiện các task triển khai tiếp theo.
- id: G02
  requirement: REQ-GOV
  stage: governance
  owner: agent
  operation: engineering
  title: Đối chiếu baseline, PR cũ và môi trường kiểm tra
  depends_on:
  - G01
  deliverables:
  - reports/verification/baseline-reconciliation.json
  acceptance: 'Kiểm trạng thái GitHub thực tế của #310/#312 và các branch liên quan; liệt kê module benchmark/retrieval
    trùng chức năng; chốt nguồn chuẩn giữa ROADMAP.md và .agents (fertility 1,35 so với 1,4, milestone
    so với stage) và sửa tài liệu lệch; ghi môi trường (.venv, torch, sentencepiece, poppler) và thư viện
    OCR/PDF còn thiếu; chạy check-no-training; không đổi gate.'
  status: done
  note: Đã đối chiếu GitHub, 22 module và môi trường; sửa mô tả fertility/stage theo nguồn chuẩn; check-no-training
    PASS (49 test); không training, cài dependency hay đổi gate.
- id: G03
  requirement: REQ-GOV
  stage: governance
  owner: joint
  operation: documentation
  title: Chốt chính sách gate, quyền dữ liệu, gold và tiền điều kiện của owner
  depends_on:
  - G02
  deliverables:
  - docs/training/PROJECT_PREREQUISITES.md
  acceptance: 'Ghi chính sách mặc định: giữ nguyên 12 gate và ADR-002, agent không nới gate; liệt kê theo
    stage nguồn dữ liệu cần có (SciFact, khóa S2ORC, dữ liệu STEM tiếng Việt, dữ liệu OCR), đối chiếu
    approval dùng đã có (ViNLI, ViQuAD, CC-100) và phần NEEDS_LICENSE_REVIEW còn thiếu, không hủy hoặc
    mở rộng approval hiện có, người gán nhãn và ngưỡng đồng thuận cho gold, thư viện OCR/PDF được phép
    cài; owner xác nhận từng mục hoặc ghi rõ mục bị chặn.'
  status: done
  note: 'D01–D04, D06 đã xử lý: ViPubmed (STEM-VI) được owner cho dùng 2026-11-11 bất chấp license chưa rõ (dịch máy, không phải gold, chưa có quyền training), SciFact tải làm nguồn G12 EN (chờ owner ghi nhận license), DocLayNet chọn nguồn, OCR EN/VI đã cài. Owner mở lại
    D05 (2026-11-11) bắt đầu từ D05-a retrieval relevance; chưa có annotator được chỉ định nên chưa có
    nhãn, S01A/O01A/M01A vẫn blocked, F03 chỉ dùng relevance có sẵn; không training hay đổi gate.'
- id: F01
  requirement: REQ-FND-EVAL
  stage: foundation
  owner: agent
  operation: implementation
  title: Hoàn thiện metric QA và hợp đồng báo cáo
  depends_on:
  - G03
  deliverables:
  - src/language/evaluation/evaluator.py
  - src/language/evaluation/metrics.py
  - tests/unit/language/test_answer_metrics.py
  acceptance: EM/F1 theo answer-text chuẩn hóa; xử lý đa đáp án, no-answer, truncation; không nhầm token-span
    với answer-text; provenance/protocol được ghi.
  status: done
  note: Đã thêm EM/F1 answer-text chuẩn hóa (đa đáp án, no-answer, truncation giữ và đếm), tách khỏi token-span;
    15 test mới, check-no-training PASS; chạy inference trên val mẫu, chưa phải bằng chứng qualification;
    không training.
- id: F02
  requirement: REQ-FND-EVAL
  stage: foundation
  owner: agent
  operation: implementation
  title: Đo tokenizer fertility EN/VI trên dữ liệu unseen
  depends_on:
  - F01
  deliverables:
  - src/language/benchmarks/fertility.py
  - tests/unit/language/test_fertility.py
  - reports/tokenizer/fertility.json
  acceptance: Tách EN/VI; định nghĩa word/token rõ ràng; corpus unseen có manifest, chống leakage và report
    tương thích readiness. Nếu fertility vượt gate, ghi đề xuất tokenizer cho F04A; agent không fit tokenizer.
  status: done
  note: 'Đã đo fertility EN/VI trên 4 nguồn test unseen (seed 42, kiểm trùng corpus fit, bootstrap CI):
    EN 1,420 và VI 1,363 đều FAIL G10/G11 (≤1,35); báo cáo hợp lệ cho readiness; 10 test mới, check-no-training
    PASS; không fit tokenizer hay training.'
- id: F03
  requirement: REQ-FND-EVAL
  stage: foundation
  owner: agent
  operation: implementation
  title: Xây benchmark retrieval nền tảng độc lập
  depends_on:
  - F02
  deliverables:
  - src/language/benchmarks/retrieval.py
  - configs/evaluation/foundation_retrieval.yaml
  - tests/unit/language/test_retrieval_benchmark.py
  - reports/retrieval/foundation.json
  acceptance: 'Đóng băng query/relevance và split; đo MRR/nDCG, BM25/dense/hybrid, hard negatives; không
    dùng pilot sáu query để thay gate. Băng hash query/relevance trước khi đo model; ngưỡng không chỉnh
    sau khi thấy kết quả; query không lấy từ dữ liệu train. D05 bị owner bỏ qua nên không có annotator:
    chỉ dùng relevance do người gán đã có sẵn từ nguồn công khai đã xác minh quyền sử dụng; không tự sinh
    relevance. Nếu không có nguồn như vậy, G12 giữ MISSING và F07 không qualify.'
  status: done
  note: 'Đã đóng băng benchmark (SQuAD EN 7284 query/1338 đoạn; ViQuAD VI 1429/288, tách theo bài viết)
    và đo BM25/dense/hybrid: dense MRR 0,034 EN và 0,116 VI so với BM25 0,783 và 0,813; nguồn general-domain
    nên G12 vẫn MISSING; 16 test mới, check-no-training PASS; không training.'
- id: F04
  requirement: REQ-FND-DATA
  stage: foundation
  owner: agent
  operation: implementation
  title: Phân tích lỗi và chuẩn bị dữ liệu model 01
  depends_on:
  - F03
  deliverables:
  - reports/language_encoder/foundation-error-analysis.json
  - configs/data/foundation_sampling.yaml
  acceptance: Lỗi ANLI, ViNLI, PAWS, STS, QA phân theo dataset/ngôn ngữ; kiểm nhãn, phân bố, leakage;
    thay đổi dữ liệu có checksum và lý do. Đánh giá khả thi từng gate dựa trên số đã đo, không dự đoán
    không có căn cứ.
  status: done
  note: Đã đo lỗi validation trên 6 dataset và đối chiếu 18 shard với manifest. Phát hiện 5 cặp STS-B
    trùng train/test và 9 dòng ViQuAD có offset lệch. Đã ghi đối chiếu 12 gate và phương án sampling có
    SHA-256. 49 test không training và 42 test metric/retrieval PASS.
- id: F04A
  requirement: REQ-FND-TRAIN
  stage: foundation
  owner: joint
  operation: documentation
  title: Chốt ngân sách compute, điều kiện dừng và nhánh tokenizer
  depends_on:
  - F04
  deliverables:
  - docs/training/FOUNDATION_BUDGET.md
  acceptance: 'Owner cung cấp throughput và VRAM đo thật từ profiling do owner chạy; chốt số bước/giờ
    GPU tối đa, số vòng thử tối đa và điều kiện dừng; quyết định giữ hay fit lại tokenizer (fit lại làm
    vô hiệu checkpoint hiện có và phải ghi vào lineage); đánh giá khả thi từng gate từ learning curve
    đã đo; nếu gate không đạt trong ngân sách, owner chọn tiếp tục, dừng hoặc mở sửa gate qua ADR có lý
    do, agent không tự giảm gate. Đầu vào bắt buộc: fertility F02 hiện FAIL cả EN (1,420) và VI (1,363)
    theo định nghĩa macro-source đã cố định trước khi đo; quyết định tokenizer dựa trên số này, không
    đổi định nghĩa để qua gate.'
  status: done
  note: Owner chốt tối đa 2 giờ GPU, 2 vòng × 2.000 bước, validation mỗi 500 bước, patience 3 theo loss
    validation trung bình và giữ tokenizer hiện tại cho chẩn đoán. Profiling đạt peak 3,64 GiB.
- id: F05
  requirement: REQ-FND-TRAIN
  stage: foundation
  owner: agent
  operation: implementation
  title: Chuẩn bị curriculum và lệnh train model 01
  depends_on:
  - F04A
  deliverables:
  - configs/language_encoder/compact.yaml
  - src/language/training/objectives.py
  - tests/unit/language/test_retrieval_objective.py
  - docs/training/OWNER_RUNBOOK.md
  acceptance: 'Chốt objective/sampling/loss, ablation và ngân sách theo F04A; thêm objective contrastive
    cho retrieval (G12 cần vượt BM25) kèm test chỉ tính giá trị loss, không backward; cấu hình khớp parser/checkpoint;
    chỉ xuất lệnh, không fitting/backward/optimizer. Đầu vào bắt buộc từ F03: dense MRR hiện 0,034 (EN)
    và 0,116 (VI), thấp hơn BM25 (0,783 và 0,813); kiểm tra đối chứng cho thấy pipeline đúng, nên cần
    objective retrieval, không phải sửa đo lường.'
  status: done
  note: Đã nối sampler train và loss contrastive QA tùy chọn, kiểm khởi tạo từ checkpoint theo SHA-256
    và bàn giao hai vòng đối chứng sampling theo F04A. 49 test không training và 47 test tập trung PASS.
- id: F06
  requirement: REQ-FND-TRAIN
  stage: foundation
  owner: owner
  operation: training
  title: Chủ dự án train candidate model 01
  depends_on:
  - F05
  deliverables:
  - reports/language_encoder/foundation-owner-run.json
  acceptance: Chạy smoke ngắn và trả kết quả trước khi chạy dài; chủ dự án tự profile/train; trả manifest,
    cấu hình, log, checkpoint digest và validation; không commit weights.
  status: done
  note: Owner ủy quyền trực tiếp chạy F06. Hai smoke 10 bước và hai vòng chính 1.990 bước đã hoàn tất,
    peak log 3,9 GiB và tổng 37 phút 26 giây gồm validation. Checkpoint và validation đã đối chiếu SHA-256.
    Sampling có loss validation tốt nhất 0,221779 tại bước 1.500, baseline 0,222040 tại bước 1.990.
- id: F05-R1
  requirement: REQ-FND-TRAIN
  stage: foundation
  owner: agent
  operation: engineering
  title: Chuẩn bị corpus và phép đo development cho tokenizer mới
  depends_on:
  - F06
  deliverables:
  - docs/training/FOUNDATION_TOKENIZER_REMEDIATION.md
  - experiments/language_encoder/prepare_tokenizer_remediation.py
  - reports/tokenizer/foundation-r1-preparation.json
  acceptance: Chuẩn bị corpus từ train đã xác minh checksum, giữ tokenizer/checkpoint gốc. Khóa protocol
    validation để so ứng viên cùng 32k trước khi dùng test. Ghi rõ gate, lineage, nguồn dữ liệu còn thiếu
    và quyết định ngân sách cần owner.
  status: done
  note: 'Đã chuẩn bị 3.999.993 mục train từ bốn nguồn có SHA-256 và khóa 9.748 văn bản validation dùng
    chung. Fertility development của tokenizer cũ: EN 1,4417, VI 1,3442. Đã kiểm parser lệnh owner, 49
    test không training và 47 test tập trung PASS.'
- id: F06-R1
  requirement: REQ-FND-TRAIN
  stage: foundation
  owner: owner
  operation: training
  title: Fit tokenizer mới và chạy candidate foundation theo ngân sách mới
  depends_on:
  - F05-R1
  deliverables:
  - reports/language_encoder/foundation-owner-run-r1.json
  acceptance: Owner chọn nhánh và duyệt ngân sách mới. Fit tokenizer từ train, so trên validation, chốt
    tokenizer trước khi chấm test. Huấn luyện encoder với lineage mới và bàn giao manifest, log, checksum,
    validation.
  status: blocked
  note: Chờ owner duyệt fit nhánh BPE 32k và ngân sách CPU. Sau so sánh validation, cần chốt tokenizer
    và ngân sách GPU mới trước khi huấn luyện encoder. Đo inference 2026-11-11, dense MRR 0,012 so với BM25 0,636 trên SciFact train; embedding CLS chưa học retrieval (trọng số 0), nên ngân sách GPU phải có giai đoạn contrastive (retrieval-loss-weight > 0) để G12 khả thi. Tokenizer 48k không tách chữ số đã fit và qua gate trên mẫu development (EN 1,300, VI 1,185); còn lại đổi vocab encoder lên 48000, đo lại profiling và chốt ngân sách GPU có giai đoạn contrastive.
- id: F07
  requirement: REQ-FND-QUAL
  stage: foundation
  owner: joint
  operation: qualification
  title: Nghiệm thu model 01 trên held-out test
  depends_on:
  - F06
  - F06-R1
  deliverables:
  - reports/language_encoder/foundation-qualification.json
  acceptance: 'Đủ 12 gate, protocol đúng, cùng model/tokenizer, nguồn test độc lập và được chủ dự án duyệt;
    thiếu bất kỳ gate nào thì không promote. Nếu gate fail, mở vòng sửa theo mục 7 của plan; không gạch
    F07. G12 dùng nguồn STEM có relevance do người gán (SciFact, đã đóng băng, chờ owner ghi nhận license; VI chưa có): nguồn general-domain của
    F03 không được dùng thay.'
  status: blocked
  note: Chưa qualified. G10 EN 1,420 và G11 VI 1,363 vượt 1,35. G12 có nguồn SciFact (relevance chuyên gia, 300 query) đã đóng băng digest nhưng chưa chấm; chưa có nguồn VI người gán. F06
    cung cấp validation cho G01–G09. Mở F05-R1 và F06-R1 trước khi nghiệm thu lại.
- id: S01
  requirement: REQ-SCI
  stage: scientific_language
  owner: agent
  operation: implementation
  title: Chuẩn bị corpus ngôn ngữ khoa học EN/VI
  depends_on:
  - F07
  deliverables:
  - docs/specifications/SCIENTIFIC_LANGUAGE_SPECIFICATION.md
  - reports/scientific_language/data-readiness.json
  acceptance: Nguồn/quyền sử dụng rõ, split theo document/family, nhãn NLI/evidence/discourse có audit;
    ghi thiếu dữ liệu VI thay vì giả định đủ. Gồm thu thập SciFact và nguồn STEM theo G03; ghi chặn nếu
    thiếu quyền truy cập thay vì dùng dữ liệu thay thế.
  status: pending
  note: ''
- id: S01A
  requirement: REQ-SCI
  stage: scientific_language
  owner: joint
  operation: implementation
  title: Gán nhãn gold khoa học và đo đồng thuận
  depends_on:
  - S01
  deliverables:
  - reports/scientific_language/gold-audit.json
  acceptance: Nhãn NLI/evidence/discourse khoa học do người gán theo guideline; có inter-annotator agreement,
    split theo document/family và tách khỏi dữ liệu train; agent không tự sinh nhãn gold.
  status: blocked
  note: 'D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định
    người gán và protocol rồi mới mở task.'
- id: S02
  requirement: REQ-SCI
  stage: scientific_language
  owner: agent
  operation: implementation
  title: Triển khai adaptation và inference model 02
  depends_on:
  - S01A
  deliverables:
  - src/scientific/language/model.py
  - tests/contract/test_scientific_language.py
  acceptance: Khởi tạo từ foundation đã qualified theo thiết kế được duyệt; tokenizer lineage, thuật ngữ,
    phủ định, số/đơn vị và điều kiện được giữ; không dùng foundation pretrained bên ngoài.
  status: pending
  note: ''
- id: S03
  requirement: REQ-SCI
  stage: scientific_language
  owner: agent
  operation: implementation
  title: Chuẩn bị training/evaluation khoa học và evidence
  depends_on:
  - S02
  deliverables:
  - src/scientific/training/runner.py
  - configs/evaluation/scientific_language.yaml
  - docs/training/SCIENTIFIC_LANGUAGE_RUNBOOK.md
  acceptance: Code/lệnh train và evaluator SciFact/evidence/discourse có contract và fixture; không optimizer
    do agent; labels và phép đo độc lập với model.
  status: pending
  note: ''
- id: S04
  requirement: REQ-SCI
  stage: scientific_language
  owner: owner
  operation: training
  title: Chủ dự án train model 02
  depends_on:
  - S03
  deliverables:
  - reports/scientific_language/owner-run.json
  acceptance: Chạy smoke ngắn và trả kết quả trước khi chạy dài; chủ dự án tự train, trả artifacts/provenance
    và validation theo cấu hình đã chốt.
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
- id: S05
  requirement: REQ-SCI
  stage: scientific_language
  owner: joint
  operation: qualification
  title: Nghiệm thu ngôn ngữ khoa học
  depends_on:
  - S04
  deliverables:
  - reports/scientific_language/qualification.json
  acceptance: SciFact NLI macro F1 >= 0.82; evidence precision và recall >= 0.80 theo đặc tả; kiểm phủ
    định/điều kiện/đơn vị và regression foundation.
  status: pending
  note: ''
- id: O01
  requirement: REQ-OCR
  stage: ocr
  owner: agent
  operation: implementation
  title: Chuẩn hóa document schema và ánh xạ tọa độ
  depends_on:
  - S05
  deliverables:
  - docs/specifications/DOCUMENT_INTELLIGENCE_SPECIFICATION.md
  acceptance: Chốt page/block/paragraph/sentence/char coordinates, reading order, hash nguồn và canonical
    text; không nhận diện layout chỉ bằng heading.
  status: pending
  note: ''
- id: O01A
  requirement: REQ-OCR
  stage: ocr
  owner: joint
  operation: implementation
  title: Chuẩn bị gold OCR/layout và toolchain đã duyệt
  depends_on:
  - O01
  deliverables:
  - reports/documents/ocr-gold-audit.json
  acceptance: Gold text/layout clean và degraded do người kiểm; toolchain OCR/PDF đã được owner duyệt
    ở G03 và cài vào môi trường; có audit/agreement; không dùng output OCR làm gold.
  status: blocked
  note: 'D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định
    người gán và protocol rồi mới mở task.'
- id: O02
  requirement: REQ-OCR
  stage: ocr
  owner: agent
  operation: implementation
  title: Triển khai dữ liệu, parser và OCR pipeline
  depends_on:
  - O01A
  deliverables:
  - src/documents/parsing.py
  - src/documents/ocr.py
  - docs/training/OCR_RUNBOOK.md
  acceptance: Dữ liệu clean/degraded có gold; phân biệt text-native/scanned; giữ order, công thức, bảng/hình
    và đánh dấu phần chưa hỗ trợ; code và lệnh, không train.
  status: pending
  note: ''
- id: O03
  requirement: REQ-OCR
  stage: ocr
  owner: owner
  operation: training
  title: Chủ dự án train thành phần OCR cần học
  depends_on:
  - O02
  deliverables:
  - reports/documents/ocr-owner-run.json
  acceptance: Chạy smoke ngắn và trả kết quả trước khi chạy dài; chủ dự án thực thi training đã duyệt;
    trả checkpoint/dataset lineage và measurements.
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
- id: O04
  requirement: REQ-OCR
  stage: ocr
  owner: joint
  operation: qualification
  title: Nghiệm thu OCR và provenance vật lý
  depends_on:
  - O03
  deliverables:
  - reports/documents/ocr-qualification.json
  acceptance: CER <= 1.5% clean, <= 3.0% degraded; layout IoU >= 0.88; audit reading order và span mapping,
    gồm lỗi hai cột đã thấy ở pilot.
  status: pending
  note: ''
- id: M01A
  requirement: REQ-MANUSCRIPT
  stage: manuscript
  owner: joint
  operation: implementation
  title: Gán nhãn gold discourse trên đầu ra OCR
  depends_on:
  - O04
  deliverables:
  - reports/documents/discourse-gold-audit.json
  acceptance: Gold discourse-role có tọa độ do người gán trên đầu ra OCR; có agreement, split theo document
    và heading-stripped subset; agent không tự sinh nhãn gold.
  status: blocked
  note: 'D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định
    người gán và protocol rồi mới mở task.'
- id: M01
  requirement: REQ-MANUSCRIPT
  stage: manuscript
  owner: agent
  operation: implementation
  title: Triển khai học cấu trúc bản thảo gắn OCR
  depends_on:
  - M01A
  deliverables:
  - src/documents/discourse.py
  - docs/training/MANUSCRIPT_LEARNING_RUNBOOK.md
  acceptance: Dữ liệu discourse-role có gold/coordinate; code học claim/method/result/limitation trên
    đầu ra OCR; heading-stripped tests; không lẫn với viết manuscript.
  status: pending
  note: ''
- id: M02
  requirement: REQ-MANUSCRIPT
  stage: manuscript
  owner: owner
  operation: training
  title: Chủ dự án train manuscript/discourse model
  depends_on:
  - M01
  deliverables:
  - reports/documents/manuscript-owner-run.json
  acceptance: Chạy smoke ngắn và trả kết quả trước khi chạy dài; chủ dự án tự train theo lệnh, trả log,
    provenance và validation.
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
- id: M03
  requirement: REQ-MANUSCRIPT
  stage: manuscript
  owner: joint
  operation: qualification
  title: Nghiệm thu discourse bản thảo
  depends_on:
  - M02
  deliverables:
  - reports/documents/manuscript-qualification.json
  acceptance: Discourse-role macro F1 >= 0.82; audit lỗi OCR truyền xuống, heading-independent extraction
    và giữ giá trị/số/đơn vị.
  status: pending
  note: ''
- id: I01
  requirement: REQ-INTEGRATION
  stage: integration
  owner: agent
  operation: implementation
  title: Nối model thật, corpus, graph và hybrid retrieval
  depends_on:
  - M03
  deliverables:
  - tests/integration/test_qualified_model_pipeline.py
  acceptance: Dùng artifacts đã qualified, adapters đúng dimension/provenance; SQLite persistence/cache
    hoạt động; không synthetic executor trong đường chạy chứng nhận.
  status: pending
  note: ''
- id: I02
  requirement: REQ-INTEGRATION
  stage: integration
  owner: agent
  operation: implementation
  title: Hoàn thiện orchestration và quản lý tài nguyên thật
  depends_on:
  - I01
  deliverables:
  - tests/integration/test_real_specialist_execution.py
  acceptance: DAG có budget/cycle/cancellation/failure propagation; model loader/offload thật và telemetry
    thực; simulation phải được gắn nhãn.
  status: pending
  note: ''
- id: I03
  requirement: REQ-INTEGRATION
  stage: integration
  owner: agent
  operation: implementation
  title: Tích hợp report và kiểm chứng evidence
  depends_on:
  - I02
  deliverables:
  - tests/integration/test_supported_research_report.py
  acceptance: Mỗi assertion có nguồn và phạm vi hỗ trợ; kiểm hash/span, mức hỗ trợ và abstention; trích
    đúng nguồn không tự đồng nghĩa kết luận đúng.
  status: pending
  note: ''
- id: I04
  requirement: REQ-INTEGRATION
  stage: integration
  owner: joint
  operation: qualification
  title: Nghiệm thu hệ thống tích hợp local
  depends_on:
  - I03
  deliverables:
  - reports/integration/qualification.json
  acceptance: Chạy end-to-end trên bộ bài báo thật sau các stage trước; VRAM full-load <= 15.0 GB; có
    audit chất lượng/latency/lỗi, không lấy synthetic benchmark làm chứng nhận.
  status: pending
  note: ''
- id: R01
  requirement: REQ-SPECIALISTS
  stage: specialists
  owner: agent
  operation: implementation
  title: Hoàn thiện so sánh nghiên cứu và counter-evidence
  depends_on:
  - I04
  deliverables:
  - tests/integration/test_cross_paper_counter_evidence.py
  acceptance: So sánh chỉ khi điều kiện/đơn vị/metric tương thích; tách mâu thuẫn thực với khác setup;
    truy xuất phản chứng và giới hạn phạm vi.
  status: pending
  note: ''
- id: R02
  requirement: REQ-SPECIALISTS
  stage: specialists
  owner: agent
  operation: implementation
  title: Chuẩn bị specialist reasoning/generation và gold
  depends_on:
  - R01
  deliverables:
  - docs/specifications/SPECIALIST_LEARNING_SPECIFICATION.md
  - docs/training/SPECIALIST_RUNBOOK.md
  acceptance: Chốt từng specialist, dữ liệu/gold, objective, protocol, gate và lệnh owner; nguồn synthetic
    phải tách benchmark độc lập; không mặc định benchmark score. Gold do người gán theo D05; nếu D05 vẫn
    bị bỏ qua, specialist cần gold ghi blocked, không dùng gold tự sinh.
  status: pending
  note: ''
- id: R03
  requirement: REQ-SPECIALISTS
  stage: specialists
  owner: owner
  operation: training
  title: Chủ dự án train specialist được duyệt
  depends_on:
  - R02
  deliverables:
  - reports/specialists/owner-runs.json
  acceptance: Chạy smoke ngắn và trả kết quả trước khi chạy dài; chủ dự án thực thi từng run được duyệt
    và trả artifacts/validation; không train tự phát hoặc cập nhật online khi chạy nghiên cứu.
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
- id: R04
  requirement: REQ-SPECIALISTS
  stage: specialists
  owner: joint
  operation: qualification
  title: Nghiệm thu research gap và generation có kiểm chứng
  depends_on:
  - R03
  deliverables:
  - reports/specialists/qualification.json
  acceptance: Đạt gate đã chốt ở R02; bác gap đã được giải/không đủ chứng cứ; tách author limitation,
    candidate và reviewed gap; manuscript chỉ tạo khi yêu cầu.
  status: pending
  note: ''
- id: P01
  requirement: REQ-PRODUCT
  stage: product
  owner: agent
  operation: implementation
  title: Hoàn thiện giao diện và workflow người dùng
  depends_on:
  - R04
  deliverables:
  - docs/development/USER_GUIDE.md
  acceptance: Tạo project, nhập corpus/query, xem nguồn/counter-evidence/caveat, xuất report, resume;
    UI không che uncertainty hoặc bịa tiến độ capability.
  status: pending
  note: ''
- id: P02
  requirement: REQ-PRODUCT
  stage: product
  owner: agent
  operation: implementation
  title: Thiết lập regression, feedback và vận hành
  depends_on:
  - P01
  deliverables:
  - docs/development/OPERATIONS.md
  acceptance: Corpus/checkpoint/report lineage, cache invalidation, recovery, regression và feedback có
    provenance; không đưa test vào training hoặc học online trái phép.
  status: pending
  note: ''
- id: P03
  requirement: REQ-RELEASE
  stage: product
  owner: joint
  operation: qualification
  title: Nghiệm thu và phát hành theo Git Flow
  depends_on:
  - P02
  deliverables:
  - reports/release/acceptance.json
  acceptance: Cài mới/smoke/E2E/quality/resource gates pass; tài liệu/user commands đủ; đóng issue/PR
    theo evidence; release/main chỉ khi chủ dự án phê duyệt.
  status: pending
  note: ''
---

# Kế hoạch tiếp tục dự án LARIS

## 1. Phạm vi và điểm xuất phát

Kế hoạch này dẫn từ baseline phần mềm hiện có đến hệ thống được nghiệm thu. Đây
không phải kế hoạch dọn thư mục đã kết thúc. G00–G03 và F01–F05 được đánh dấu done; các
bước model, evaluation và sản phẩm còn lại chưa được thực hiện theo kế hoạch này.
G00–G03 và F01–F05 đã hoàn thành. F04A đã chốt trong [FOUNDATION_BUDGET.md](../docs/training/FOUNDATION_BUDGET.md).

Đặc tả đích: [spec.md](spec.md). Sổ công việc chi tiết: [task.md](task.md).
Giai đoạn sau chỉ được thực thi khi qualification giai đoạn trước hoàn thành và
được owner duyệt. Hoạt động chuẩn bị không phải giấy phép bỏ qua gate.

## 2. Các phase và điều kiện chuyển

| Phase | Task | Kết quả phải có | Chặn việc gì nếu chưa xong |
| --- | --- | --- | --- |
| Quản trị | G00–G03 | Baseline đã merge và đối chiếu; ba file đối chứng được; chính sách gate, dữ liệu, gold và tiền điều kiện owner được chốt | Chưa bắt đầu F01 |
| Foundation | F01–F07 (gồm F04A) | Đủ phép đo, dữ liệu/curriculum, ngân sách do owner chốt, owner train, nghiệm thu model 01 | Không triển khai model 02 |
| Scientific language | S01–S05 | Corpus và model 02, scientific NLI/evidence, owner train, qualification | Không nhảy sang OCR/PDF research workflow |
| OCR | O01–O04 | Document schema, reading order/layout/OCR và audit tọa độ | Không tuyên bố manuscript learning đã có đầu vào tin cậy |
| Manuscript learning | M01–M03 | Discourse learning trên đầu ra OCR, đủ gold và gate | Không certify tích hợp đầy đủ |
| Integration | I01–I04 | Model thật, retrieval/graph/orchestration/resource/report E2E | Không gọi simulation là specialist runtime đã đạt |
| Specialists | R01–R04 | So sánh, phản chứng, học specialist và research-gap verification | Không certify generation/gap chỉ bằng heuristic |
| Product/release | P01–P03 | Workflow/UI, vận hành/regression và acceptance release | Không tự phát hành main/release |

## 3. Ưu tiên tiếp theo

**Task kế tiếp là F06-R1.** F06 đã hoàn tất và F07 ghi nhận hai gate fertility fail. F05-R1 đã chuẩn bị corpus train và mẫu validation cố định cho nhánh tokenizer. Owner chốt quyền fit và ngân sách riêng cho vòng mới.
[Báo cáo F07](../reports/language_encoder/foundation-qualification.json) · [Hướng dẫn F06-R1](../docs/training/FOUNDATION_TOKENIZER_REMEDIATION.md)

## 4. Chu kỳ làm việc cho mỗi task

1. Đọc requirement trong spec, acceptance và predecessor trong plan.
2. Chỉ bắt đầu khi dependency đã done và stage trước đã qualified nếu có.
3. Agent làm code/config/data tooling và lệnh; owner làm mọi fitting/training/
   backward/optimizer profiling. Không chạy full suite có optimizer dưới quyền agent.
4. Chạy phép kiểm phù hợp; lưu bằng chứng có thể tái lập, lỗi chưa xử lý phải ghi rõ.
5. Đối chiếu ba file. Status, title, requirement, note và task coverage phải thống nhất;
   task done cần deliverable/evidence thực tồn tại, checkbox có gạch và note.
6. Chạy validator đến PASS trước task kế. Cập nhật qualification/model state chỉ
   sau đúng task nghiệm thu và owner review, không theo số task đã gạch.

## 5. Handoff và điểm dừng bắt buộc

G03 đã đóng: owner bỏ qua dataset thiếu và D05 (human gold), agent đã chọn OCR/dependency và cài đặt. Không xem việc bỏ dataset hoặc D05 là miễn gate hay cho phép tự sinh gold. F04A là điểm dừng bắt buộc; S01A, O01A, M01A đang blocked chờ annotator.

F06, S04, O03, M02, R03 là task training của **owner**, ban đầu được ghi blocked.
Khi đến đó agent dừng ở code/config/lệnh và chờ artifacts/measurements từ owner;
việc có một task training trong kế hoạch không cho phép agent chạy nó.
Các task qualification là joint: agent đối chiếu bằng chứng, owner duyệt kết luận.
Nếu gate chưa đạt, mở task sửa lỗi/ablation có phạm vi và cập nhật cả ba file;
không gạch task qualification, không giảm ngưỡng, không chuyển phase.

## 6. Thực thi, Git và kiểm tra

Một implementation issue/PR tập trung đi từ feature branch vào develop theo Git
Flow; main/release cần owner authorization riêng. Không trộn weights vào commit.
Giữ source theo domain/function; experiments và measurements ở khu vực riêng.
Các draft PR cũ phải được review/đối chiếu trạng thái trước khi nhận là baseline.

Lệnh kiểm tra của agent:

```bash
.venv/bin/python scripts/validate_work_plan.py
make PY=.venv/bin/python check-no-training
```

Đây là kiểm tra engineering, không phải nghiệm thu học máy. Khi thay component,
chọn thêm test không optimization tương ứng; full training tests thuộc owner.
Không ấn định thời gian/GPU giờ khi chưa có profiling và dữ liệu; cập nhật estimate
sau phép đo và giữ quyết định ngân sách cho owner.

## 7. Chính sách gate, ngân sách và vòng sửa

**Chính sách gate mặc định.** Giữ nguyên 12 gate foundation và ADR-002; agent không nới gate.
Cả ba file ghi rõ rủi ro: model 01 là encoder khoảng 110M huấn luyện từ đầu trên một GPU
16 GB, trong khi ANLI macro F1 hiện 0,40 so với 0,85, SQuAD, PAWS và ViNLI cũng còn cách
xa. F04A đánh giá khả thi bằng số đã đo. Nếu ngân sách hết mà gate chưa đạt, chỉ owner
được chọn: tiếp tục với ngân sách mới, dừng, hoặc mở sửa gate/ADR có lý do và bằng chứng.
Không khôi phục đường dùng pretrained ngoài nếu chưa có thay đổi ADR-002 được duyệt.

**Vòng sửa khi qualification fail.** Chèn cặp task agent (chuẩn bị) và owner (train) với
hậu tố `-R1`, `-R2`... đặt trước task qualification, thêm chúng vào `depends_on` của task
qualification và `task_ids` của requirement, rồi chạy validator. Số vòng tối đa theo
F04A (foundation) hoặc theo quyết định owner tương ứng. Không gạch task qualification.

**Smoke run.** Agent không chạy được backward nên code huấn luyện chỉ kiểm được bằng
test forward và fixture. Mọi task train của owner bắt đầu bằng một smoke run ngắn, báo
kết quả rồi mới chạy dài, để lỗi lộ sớm.

**Gold.** Nhãn gold cần người gán (G03 chốt người và ngưỡng đồng thuận; S01A, O01A, M01A
thực hiện). Agent chỉ viết guideline, công cụ và kiểm tra, không sinh gold.

**Chưa áp dụng.** Chạy song song các việc chuẩn bị ở stage sau khi model trước chưa
qualified bị cấm bởi validator và AGENTS.md. Nếu owner muốn, cần đổi cả hai.

**Hệ quả của việc bỏ qua D05.** Không có annotator thì không có gold do người gán. Hệ quả
đã biết: (1) F03 chỉ dùng relevance người gán đã có sẵn từ nguồn công khai đã xác minh quyền;
nếu không có, G12 giữ MISSING và F07 không thể qualify; (2) S01A, O01A, M01A blocked nên S05
(evidence precision/recall), O04 (CER, layout IoU), M03 (discourse F1) và R04 không thể có
đo lường hợp lệ cho đến khi owner chỉ định người gán; (3) F01, F02, F04, F04A, F05 và các
task code không cần gold vẫn tiến hành được. Bỏ qua D05 là hoãn quyết định, không phải
miễn gate: muốn mở lại chỉ cần owner chỉ định người gán và protocol (xem mục 5 của
PROJECT_PREREQUISITES.md), rồi chuyển các task blocked về pending.
