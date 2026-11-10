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
next_task: F01
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
- id: F01
  requirement: REQ-FND-EVAL
  stage: foundation
  owner: agent
  operation: implementation
  title: Hoàn thiện metric QA và hợp đồng báo cáo
  depends_on:
  - G01
  deliverables:
  - src/laris/language/evaluation/evaluator.py
  - tests/unit/language/test_answer_metrics.py
  acceptance: EM/F1 theo answer-text chuẩn hóa; xử lý đa đáp án, no-answer, truncation; không nhầm token-span
    với answer-text; provenance/protocol được ghi.
  status: pending
  note: ''
- id: F02
  requirement: REQ-FND-EVAL
  stage: foundation
  owner: agent
  operation: implementation
  title: Đo tokenizer fertility EN/VI trên dữ liệu unseen
  depends_on:
  - F01
  deliverables:
  - src/laris/language/benchmarks/fertility.py
  - reports/tokenizer/fertility.json
  acceptance: Tách EN/VI; định nghĩa word/token rõ ràng; corpus unseen có manifest, chống leakage và report
    tương thích readiness.
  status: pending
  note: ''
- id: F03
  requirement: REQ-FND-EVAL
  stage: foundation
  owner: agent
  operation: implementation
  title: Xây benchmark retrieval nền tảng độc lập
  depends_on:
  - F02
  deliverables:
  - src/laris/language/benchmarks/retrieval.py
  - configs/evaluation/foundation_retrieval.yaml
  acceptance: Đóng băng query/relevance và split; đo MRR/nDCG, BM25/dense/hybrid, hard negatives; không
    dùng pilot sáu query để thay gate.
  status: pending
  note: ''
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
    thay đổi dữ liệu có checksum và lý do.
  status: pending
  note: ''
- id: F05
  requirement: REQ-FND-TRAIN
  stage: foundation
  owner: agent
  operation: implementation
  title: Chuẩn bị curriculum và lệnh train model 01
  depends_on:
  - F04
  deliverables:
  - configs/language_encoder/compact.yaml
  - docs/training/OWNER_RUNBOOK.md
  acceptance: Chốt objective/sampling/loss, ablation và ngân sách; cấu hình khớp parser/checkpoint; chỉ
    xuất lệnh, không fitting/backward/optimizer.
  status: pending
  note: ''
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
  acceptance: Chủ dự án tự profile/train; trả manifest, cấu hình, log, checkpoint digest và validation;
    không commit weights.
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
- id: F07
  requirement: REQ-FND-QUAL
  stage: foundation
  owner: joint
  operation: qualification
  title: Nghiệm thu model 01 trên held-out test
  depends_on:
  - F06
  deliverables:
  - reports/language_encoder/foundation-qualification.json
  acceptance: Đủ 12 gate, protocol đúng, cùng model/tokenizer, nguồn test độc lập và được chủ dự án duyệt;
    thiếu bất kỳ gate nào thì không promote.
  status: pending
  note: ''
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
    ghi thiếu dữ liệu VI thay vì giả định đủ.
  status: pending
  note: ''
- id: S02
  requirement: REQ-SCI
  stage: scientific_language
  owner: agent
  operation: implementation
  title: Triển khai adaptation và inference model 02
  depends_on:
  - S01
  deliverables:
  - src/laris/scientific/language/model.py
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
  - src/laris/scientific/training/runner.py
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
  acceptance: Chủ dự án tự train, trả artifacts/provenance và validation theo cấu hình đã chốt.
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
- id: O02
  requirement: REQ-OCR
  stage: ocr
  owner: agent
  operation: implementation
  title: Triển khai dữ liệu, parser và OCR pipeline
  depends_on:
  - O01
  deliverables:
  - src/laris/documents/parsing.py
  - src/laris/documents/ocr.py
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
  acceptance: Chủ dự án thực thi training đã duyệt; trả checkpoint/dataset lineage và measurements.
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
- id: M01
  requirement: REQ-MANUSCRIPT
  stage: manuscript
  owner: agent
  operation: implementation
  title: Triển khai học cấu trúc bản thảo gắn OCR
  depends_on:
  - O04
  deliverables:
  - src/laris/documents/discourse.py
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
  acceptance: Chủ dự án tự train theo lệnh, trả log, provenance và validation.
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
    phải tách benchmark độc lập; không mặc định benchmark score.
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
  acceptance: Chủ dự án thực thi từng run được duyệt và trả artifacts/validation; không train tự phát
    hoặc cập nhật online khi chạy nghiên cứu.
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
không phải kế hoạch dọn thư mục đã kết thúc. Chỉ G00/G01 được đánh dấu done; các
bước model, evaluation và sản phẩm còn lại chưa được thực hiện theo kế hoạch này.
Việc hiện tại chỉ viết/kiểm tra ba tài liệu; chưa bắt đầu F01 và không training.

Đặc tả đích: [spec.md](spec.md). Sổ công việc chi tiết: [task.md](task.md).
Giai đoạn sau chỉ được thực thi khi qualification giai đoạn trước hoàn thành và
được owner duyệt. Hoạt động chuẩn bị không phải giấy phép bỏ qua gate.

## 2. Các phase và điều kiện chuyển

| Phase | Task | Kết quả phải có | Chặn việc gì nếu chưa xong |
| --- | --- | --- | --- |
| Quản trị | G00–G01 | Baseline đã merge; ba file hệ thống/dự án đối chứng được | Chưa bắt đầu triển khai task mới |
| Foundation | F01–F07 | Đủ phép đo, dữ liệu/curriculum, owner train, nghiệm thu model 01 | Không triển khai model 02 |
| Scientific language | S01–S05 | Corpus và model 02, scientific NLI/evidence, owner train, qualification | Không nhảy sang OCR/PDF research workflow |
| OCR | O01–O04 | Document schema, reading order/layout/OCR và audit tọa độ | Không tuyên bố manuscript learning đã có đầu vào tin cậy |
| Manuscript learning | M01–M03 | Discourse learning trên đầu ra OCR, đủ gold và gate | Không certify tích hợp đầy đủ |
| Integration | I01–I04 | Model thật, retrieval/graph/orchestration/resource/report E2E | Không gọi simulation là specialist runtime đã đạt |
| Specialists | R01–R04 | So sánh, phản chứng, học specialist và research-gap verification | Không certify generation/gap chỉ bằng heuristic |
| Product/release | P01–P03 | Workflow/UI, vận hành/regression và acceptance release | Không tự phát hành main/release |

## 3. Ưu tiên ngay sau khi chủ dự án cho tiếp tục

**Task kế tiếp là F01**, không phải thu thập thêm một tập bài báo để làm research
workflow. Evaluator QA hiện dùng token-span; cần normalized answer-text EM/F1,
gold alternatives/no-answer/truncation đúng và report không nhầm protocol.
Sau đó bổ sung fertility và benchmark retrieval độc lập, rồi dùng error analysis
ANLI/ViNLI/PAWS/STS/QA để quyết định thay đổi dữ liệu/curriculum.

Chỉ sau F01–F05 mới bàn giao một cấu hình/lệnh candidate có mục đích rõ cho owner.
Không mặc định train lại baseline 100k bước sẽ cải thiện chất lượng. Runbook hiện
có là mẫu owner-executed, sẽ được cập nhật từ các kết quả F01–F05 trước run mới.

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
