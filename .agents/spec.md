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
document: spec
scope: Đặc tả toàn hệ thống LARIS; không phải biên bản một đợt dọn repo.
requirements:
- id: REQ-GOV
  title: Quản trị và khả năng đối chứng
  acceptance: Mọi thay đổi có truy vết; spec/plan/task thống nhất; task done có gạch, note và bằng chứng.
    Gate không bị nới; chính sách dữ liệu, gold và tiền điều kiện owner được ghi trước khi triển khai.
  task_ids:
  - G00
  - G01
  - G02
  - G03
- id: REQ-FND-EVAL
  title: Phép đo foundation đúng protocol
  acceptance: Đủ QA answer-text, PAWS macro F1, fertility và retrieval held-out, tách EN/VI; không thay
    bằng metric gần giống.
  task_ids:
  - F01
  - F02
  - F03
- id: REQ-FND-DATA
  title: Dữ liệu foundation sạch và có chẩn đoán
  acceptance: Dataset/label/split/sampling có manifest và error analysis; dữ liệu dùng cho training không
    nhiễm evaluation.
  task_ids:
  - F04
- id: REQ-FND-TRAIN
  title: Chuẩn bị và chạy foundation theo quyền chủ dự án
  acceptance: Agent chỉ làm code/config/lệnh; ngân sách compute, điều kiện dừng và nhánh tokenizer do
    owner chốt trước run; owner tự train/profile và trả provenance; không khẳng định lặp baseline sẽ tự
    đạt chất lượng.
  task_ids:
  - F04A
  - F05
  - F06
  - F05-R1
  - F06-R1
- id: REQ-FND-QUAL
  title: Model 01 qualified trước model 02
  acceptance: Tất cả gate của cấu hình foundation và protocol/identity/test evidence được kiểm tra, có
    owner review.
  task_ids:
  - F07
- id: REQ-SCI
  title: Ngôn ngữ khoa học model 02
  acceptance: Học STEM sau foundation qualified; bảo toàn semantic quantities; scientific NLI/evidence
    đạt gate và không làm hỏng foundation. Gold do người gán, có đồng thuận và audit; agent không tự sinh
    gold.
  task_ids:
  - S01
  - S01A
  - S02
  - S03
  - S04
  - S05
- id: REQ-OCR
  title: Document intelligence và scientific OCR
  acceptance: Đọc đúng thứ tự, giữ tọa độ và gold layout/text; pass CER/IoU và audit nguồn vật lý. Gold
    do người gán, có đồng thuận và audit; agent không tự sinh gold.
  task_ids:
  - O01
  - O01A
  - O02
  - O03
  - O04
- id: REQ-MANUSCRIPT
  title: Học discourse gắn OCR
  acceptance: Phân loại vai trò khoa học bằng nội dung, có gold và provenance; đạt gate discourse trên
    văn bản OCR. Gold do người gán, có đồng thuận và audit; agent không tự sinh gold.
  task_ids:
  - M01A
  - M01
  - M02
  - M03
- id: REQ-INTEGRATION
  title: Hệ thống local có model thật
  acceptance: Các đường chạy chứng nhận dùng model/telemetry/adapters thật, có failure handling và budget;
    evidence/report được audit.
  task_ids:
  - I01
  - I02
  - I03
  - I04
- id: REQ-SPECIALISTS
  title: Reasoning, gap và generation kiểm chứng được
  acceptance: So sánh hợp lệ, tìm phản chứng, abstain khi thiếu evidence; specialist có gold/gate riêng
    và được nghiệm thu.
  task_ids:
  - R01
  - R02
  - R03
  - R04
- id: REQ-PRODUCT
  title: Sản phẩm sử dụng và vận hành được
  acceptance: Workflow từ corpus đến report có citation inspection, lineage, recovery và regression; không
    che giới hạn năng lực.
  task_ids:
  - P01
  - P02
- id: REQ-RELEASE
  title: Phát hành có bằng chứng
  acceptance: Quality/capability/resource gates và clean install pass; chủ dự án duyệt release, không
    tự đưa lên main.
  task_ids:
  - P03
task_progress:
- id: G00
  status: done
  note: 'Đã commit và merge PR #314 vào develop tại 873dd91; 41 test không training và bằng chứng chuẩn
    bị đã lưu.'
- id: G01
  status: done
  note: Đã viết ba file Markdown đúng phạm vi hệ thống/dự án; cập nhật validator và tham chiếu; chưa thực
    hiện các task triển khai tiếp theo.
- id: G02
  status: done
  note: Đã đối chiếu GitHub, 22 module và môi trường; sửa mô tả fertility/stage theo nguồn chuẩn; check-no-training
    PASS (49 test); không training, cài dependency hay đổi gate.
- id: G03
  status: done
  note: 'D01–D04, D06 đã xử lý: ViPubmed (STEM-VI) được owner cho dùng 2026-11-11 bất chấp license chưa rõ (dịch máy, không phải gold, chưa có quyền training), SciFact tải làm nguồn G12 EN (chờ owner ghi nhận license), DocLayNet chọn nguồn, OCR EN/VI đã cài. Owner mở lại
    D05 (2026-11-11) bắt đầu từ D05-a retrieval relevance; chưa có annotator được chỉ định nên chưa có
    nhãn, S01A/O01A/M01A vẫn blocked, F03 chỉ dùng relevance có sẵn; không training hay đổi gate.'
- id: F01
  status: done
  note: Đã thêm EM/F1 answer-text chuẩn hóa (đa đáp án, no-answer, truncation giữ và đếm), tách khỏi token-span;
    15 test mới, check-no-training PASS; chạy inference trên val mẫu, chưa phải bằng chứng qualification;
    không training.
- id: F02
  status: done
  note: 'Đã đo fertility EN/VI trên 4 nguồn test unseen (seed 42, kiểm trùng corpus fit, bootstrap CI):
    EN 1,420 và VI 1,363 đều FAIL G10/G11 (≤1,35); báo cáo hợp lệ cho readiness; 10 test mới, check-no-training
    PASS; không fit tokenizer hay training.'
- id: F03
  status: done
  note: 'Đã đóng băng benchmark (SQuAD EN 7284 query/1338 đoạn; ViQuAD VI 1429/288, tách theo bài viết)
    và đo BM25/dense/hybrid: dense MRR 0,034 EN và 0,116 VI so với BM25 0,783 và 0,813; nguồn general-domain
    nên G12 vẫn MISSING; 16 test mới, check-no-training PASS; không training.'
- id: F04
  status: done
  note: Đã đo lỗi validation trên 6 dataset và đối chiếu 18 shard với manifest. Phát hiện 5 cặp STS-B
    trùng train/test và 9 dòng ViQuAD có offset lệch. Đã ghi đối chiếu 12 gate và phương án sampling có
    SHA-256. 49 test không training và 42 test metric/retrieval PASS.
- id: F04A
  status: done
  note: Owner chốt tối đa 2 giờ GPU, 2 vòng × 2.000 bước, validation mỗi 500 bước, patience 3 theo loss
    validation trung bình và giữ tokenizer hiện tại cho chẩn đoán. Profiling đạt peak 3,64 GiB.
- id: F05
  status: done
  note: Đã nối sampler train và loss contrastive QA tùy chọn, kiểm khởi tạo từ checkpoint theo SHA-256
    và bàn giao hai vòng đối chứng sampling theo F04A. 49 test không training và 47 test tập trung PASS.
- id: F06
  status: done
  note: Owner ủy quyền trực tiếp chạy F06. Hai smoke 10 bước và hai vòng chính 1.990 bước đã hoàn tất,
    peak log 3,9 GiB và tổng 37 phút 26 giây gồm validation. Checkpoint và validation đã đối chiếu SHA-256.
    Sampling có loss validation tốt nhất 0,221779 tại bước 1.500, baseline 0,222040 tại bước 1.990.
- id: F05-R1
  status: done
  note: 'Đã chuẩn bị 3.999.993 mục train từ bốn nguồn có SHA-256 và khóa 9.748 văn bản validation dùng
    chung. Fertility development của tokenizer cũ: EN 1,4417, VI 1,3442. Đã kiểm parser lệnh owner, 49
    test không training và 47 test tập trung PASS.'
- id: F06-R1
  status: blocked
  note: Chờ owner duyệt fit nhánh BPE 32k và ngân sách CPU. Sau so sánh validation, cần chốt tokenizer
    và ngân sách GPU mới trước khi huấn luyện encoder. Đo inference 2026-11-11, dense MRR 0,012 so với BM25 0,636 trên SciFact train; embedding CLS chưa học retrieval (trọng số 0), nên ngân sách GPU phải có giai đoạn contrastive (retrieval-loss-weight > 0) để G12 khả thi. Tokenizer 48k không tách chữ số đã fit và qua gate trên mẫu development (EN 1,300, VI 1,185); còn lại đổi vocab encoder lên 48000, đo lại profiling và chốt ngân sách GPU có giai đoạn contrastive.
- id: F07
  status: blocked
  note: Chưa qualified. G10 EN 1,420 và G11 VI 1,363 vượt 1,35. G12 có nguồn SciFact (relevance chuyên gia, 300 query) đã đóng băng digest nhưng chưa chấm; chưa có nguồn VI người gán. F06
    cung cấp validation cho G01–G09. Mở F05-R1 và F06-R1 trước khi nghiệm thu lại.
- id: S01
  status: pending
  note: ''
- id: S01A
  status: blocked
  note: 'D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định
    người gán và protocol rồi mới mở task.'
- id: S02
  status: pending
  note: ''
- id: S03
  status: pending
  note: ''
- id: S04
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
- id: S05
  status: pending
  note: ''
- id: O01
  status: pending
  note: ''
- id: O01A
  status: blocked
  note: 'D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định
    người gán và protocol rồi mới mở task.'
- id: O02
  status: pending
  note: ''
- id: O03
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
- id: O04
  status: pending
  note: ''
- id: M01A
  status: blocked
  note: 'D05 bị owner bỏ qua: chưa có annotator/adjudicator; agent không tự sinh gold. Chờ owner chỉ định
    người gán và protocol rồi mới mở task.'
- id: M01
  status: pending
  note: ''
- id: M02
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
- id: M03
  status: pending
  note: ''
- id: I01
  status: pending
  note: ''
- id: I02
  status: pending
  note: ''
- id: I03
  status: pending
  note: ''
- id: I04
  status: pending
  note: ''
- id: R01
  status: pending
  note: ''
- id: R02
  status: pending
  note: ''
- id: R03
  status: blocked
  note: Chỉ chủ dự án thực thi sau khi các phụ thuộc hoàn thành; agent không training.
- id: R04
  status: pending
  note: ''
- id: P01
  status: pending
  note: ''
- id: P02
  status: pending
  note: ''
- id: P03
  status: pending
  note: ''
---

# Đặc tả hệ thống LARIS

## 1. Mục tiêu và phạm vi

LARIS là hệ thống nghiên cứu khoa học local-first: xây năng lực ngôn ngữ từ nền
ngôn ngữ tự nhiên EN/VI, chuyên biệt hóa ngôn ngữ khoa học, đọc tài liệu, tổ chức
bằng chứng và hỗ trợ so sánh nghiên cứu, nhận diện gap ứng viên, đề xuất kiểm chứng.
Đầu ra mặc định là report có nguồn và giới hạn kết luận; manuscript chỉ tạo khi
người dùng yêu cầu. Đây là đặc tả đích, không phải khẳng định mọi năng lực đã có.

Người dùng chính là chủ dự án/nhà nghiên cứu làm việc trên workstation cục bộ.
Đầu vào gồm text/dataset được phép sử dụng, tài liệu khoa học, câu hỏi và artifacts
model đã được nghiệm thu. Đầu ra gồm corpus có lineage, prediction/representation,
evidence graph, report, audit và artifacts được version hóa.

## 2. Ràng buộc bất biến

- Không phụ thuộc bắt buộc vào cloud inference hoặc foundation pretrained bên ngoài.
- Agent không neural training, tokenizer fitting, backward/optimizer step, authorized
  profiling hoặc test có optimization. Agent viết code/config/lệnh; chủ dự án tự chạy.
- Không suy ra capability từ việc có code, nhiều test pass, loss giảm hoặc metric mặc định.
- Foundation qualified → scientific language → OCR → manuscript learning → integration
  → specialist learning/verification. Không đưa pilot tập bài báo lên trước model 02.
- Mỗi assertion có nguồn, định danh revision/hash và span; citation hợp lệ chưa chứng
  minh nội dung hỗ trợ kết luận. Kết luận thiếu hỗ trợ phải hạ mức tin cậy hoặc abstain.
- Tách dữ liệu development/validation/test; không điều chỉnh model/ngưỡng bằng test.
- Giữ weights/checkpoints/dataset lớn ngoài Git; source/config đặt tên theo chức năng
  theo ADR-013, không theo số model hoặc số layer.
- Không phát hành/merge/main ngoài phạm vi được chủ dự án cho phép.

## 3. Kiến trúc chức năng

| Miền | Trách nhiệm đích | Hợp đồng chính |
| --- | --- | --- |
| corpus | Acquisition, quyền sử dụng, chuẩn hóa, dedup, split | Manifest, schema, SHA-256, thống kê task/language, cách ly evaluation |
| language | Tokenizer và model 01 | Vocabulary/artifact identity, NLI/paraphrase/similarity/QA/embedding đúng protocol |
| scientific | Model 02 và scientific NLP | NLI khoa học, evidence/discourse, phủ định, điều kiện, đại lượng và đơn vị |
| document intelligence | OCR/layout/canonical document | Reading order và liên kết PDF/page/block/sentence/span; phần chưa có phải ghi rõ |
| graph/retrieval | Lưu và truy xuất bằng chứng | SQLite, lexical/dense/graph, rank fusion, provenance fail-closed |
| reasoning | So sánh nghiên cứu và gap | Kiểm comparability, mâu thuẫn, taxonomy, phản chứng, mức bất định |
| orchestration/execution | Điều phối và tài nguyên | DAG, budget, cycle/failure/cancel, model loading thật, telemetry thật |
| evaluation/reporting | Đo chất lượng, audit và sản phẩm | Benchmark độc lập, citation/support review, report lineage, UI kiểm tra nguồn |

12 layer là kiến trúc khái niệm; không tạo lại cây `layers/layerX_*`. Miền document
intelligence chưa có parser/OCR production hoàn chỉnh; vị trí package và hợp đồng
mới được chốt trong task O01 trước khi triển khai. Các subsystem còn heuristic/mock
phải được ghi nhãn, không dùng làm đường chứng nhận model thật.

## 4. Thứ tự model và gate

| Giai đoạn | Năng lực | Điều kiện nghiệm thu | Trạng thái hiện tại |
| --- | --- | --- | --- |
| Model 01 | Ngôn ngữ tự nhiên EN/VI | Đủ 12 gate foundation, đúng protocol/identity/held-out, owner review | Có checkpoint; chưa qualified |
| Model 02 | Ngôn ngữ khoa học STEM | SciFact macro F1 ≥ 0,82; evidence precision/recall ≥ 0,80; regression foundation | Chưa triển khai |
| OCR | Scientific OCR/layout | CER ≤ 1,5% clean / 3% degraded; layout IoU ≥ 0,88; audit reading order/coordinates | Chưa triển khai learning pipeline |
| Manuscript learning | Discourse gắn OCR | Discourse-role macro F1 ≥ 0,82; heading-independent, giữ semantic quantities | Chưa triển khai learning pipeline |
| Integration | Kết nối các model đã qualified | E2E thật, audit, failure handling, VRAM full-load ≤ 15 GB | Có nhiều component; chưa qualified |
| Specialists | Reasoning/verification/generation | Gate từng specialist được chốt trước training, human review và phản chứng | Có baseline; chưa qualified |

Rủi ro đã ghi nhận: một số gate foundation (ANLI, SQuAD, PAWS, ViNLI) cách xa kết quả hiện tại và
chưa có ngân sách compute; chính sách xử lý nằm ở mục 7 của plan. Gate chi tiết model 01 có một nguồn chuẩn tại
[`foundation.yaml`](../configs/evaluation/foundation.yaml) và
[đặc tả training](../docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md).
Không thay gate này bằng baseline-relative floors trong `language_encoder.yaml`.
Model 02 nhận năng lực foundation đã qualified; lựa chọn adaptation/objective/data
cụ thể phải được chốt trước training, không tự coi shared encoder hiện tại là model 02.
Scientific language có thể học từ corpus text sạch; chưa cần OCR để chuẩn bị text
khoa học. OCR là stage sau, không phải lý do nhảy từ model 01 sang workflow PDF.

## 5. Dữ liệu, artifacts và evidence

Mỗi corpus phải khai báo nguồn, phiên bản, quyền sử dụng, schema, đơn vị đếm,
ngôn ngữ, task, hash và cách split/dedup. Không lấp thiếu nhãn hoặc thiếu dữ liệu
bằng giá trị mặc định/synthetic rồi gọi đó là dữ liệu thật. Dữ liệu synthetic nếu
có phải được tách và gắn nhãn; không thay thế benchmark độc lập.

Artifact phải nối được checkpoint → config/git/seed → tokenizer → dataset manifests
→ measurement reports. Resume không được tuyên bố khôi phục chính xác data stream
nếu loader chưa lưu vị trí stream. Các report phải ghi metric protocol, sample count,
source split, identity và baseline; thiếu trường quan trọng thì chưa đủ nghiệm thu.

Nhãn gold (NLI/evidence/discourse khoa học, OCR/layout, discourse trên OCR) phải do người gán, có
đồng thuận và audit; agent không tự sinh gold rồi dùng làm benchmark.

Evidence cần phân biệt: excerpt đúng nguồn, claim được hỗ trợ, synthesis nhiều nguồn,
hypothesis và gap ứng viên. Research gap không được kết luận chỉ từ việc search
không tìm thấy tài liệu. Human review và phạm vi corpus là một phần của kết luận.

## 6. Hành vi sản phẩm đích

1. Nhận câu hỏi/corpus, xác định phạm vi và kiểm quyền sử dụng/identity.
2. Chuẩn hóa, phân tích ngôn ngữ khoa học, OCR/layout khi cần; tạo evidence graph.
3. Truy xuất lexical/dense/graph, kiểm điều kiện so sánh, tìm phản chứng.
4. Trình bày report với citation inspection, bằng chứng trái chiều, uncertainty và
   phần chưa kiểm chứng; không tự tạo manuscript hay chạy thí nghiệm.
5. Ghi lineage và feedback; không online training hoặc tự đưa evaluation vào training.

## 7. Tài nguyên và vận hành

Target là workstation RTX 5070 Ti 16 GB / RAM khoảng 32 GB. Giới hạn chuẩn bị đo
training allocations là 14,5 GB; full-load integration là 15 GB theo gate tương ứng.
Inference peak không chứng nhận training memory. Owner tự thực hiện phép đo có
backward/optimizer; agent chỉ chuẩn bị lệnh. Loading/offloading/cache phải dùng
telemetry và chuyển tensor thật trước khi được gọi là đã nghiệm thu tài nguyên.

## 8. Bằng chứng hiện có và giới hạn

PR #314 đã merge vào develop ở `873dd91`; repo có readiness offline, owner runbook
và report hiện có. [Readiness model 01](../reports/language_encoder/foundation-readiness.json)
vẫn NOT QUALIFIED: score còn thấp, thiếu metric/protocol và held-out evidence.
[Pilot 20 bài](../reports/scientific_nlp/pilot.json) là chẩn đoán lịch sử: dense yếu
trong bộ query nhỏ và nhiều excerpt không hữu ích dù khớp nguồn. Nó không hoàn
thành model 02 hoặc research-gap engine.

Các PR #310 (benchmark) và #312 (source evidence) là thay đổi riêng chưa được merge
trong mốc baseline #314. G02 kiểm tra lại ngày 2026-11-11: cả hai vẫn là draft; PR #317 đã merge tại `5954f53`.
[Đối chiếu baseline](../reports/verification/baseline-reconciliation.json) ghi module trùng chức năng, môi trường và nguồn chuẩn; không coi draft PR là code đã có trên develop.

## 9. Truy vết yêu cầu và quy tắc thay đổi

Mỗi requirement trong YAML front matter là yêu cầu hệ thống; `task_ids` nối tới các
bước trong [plan.md](plan.md) và checklist trong [task.md](task.md). `task_progress`
chỉ là chỉ mục đối chứng, không thay nội dung đặc tả. Một yêu cầu có thể cần nhiều
task; task engineering done không tự đổi trạng thái model thành qualified.

G02 đã hoàn tất đối chiếu local; G03 đã đóng với D05 human gold bị owner bỏ qua; nguồn/dependency đã xử lý tại
[tiền điều kiện dự án](../docs/training/PROJECT_PREREQUISITES.md). Giữ approval
dùng dữ liệu đã ghi nhận; không tự mở rộng sang redistribution hoặc giả định đã
có người gán gold. Thiếu gold người gán thì các gate cần gold (evidence, OCR/layout, discourse)
không thể được đo hợp lệ.

Sau từng task: đối chiếu requirement/acceptance → plan/dependency/deliverable → task/
evidence; sửa mọi lệch, cập nhật status/note ở cả ba file, gạch task done, rồi chạy
`python scripts/validate_work_plan.py` thành công. Qualification còn cần report và
owner review; không hard-code tất cả stage mãi chưa qualified, cũng không tự promote.
Các ADR và specification chuẩn vẫn là nguồn hợp đồng chi tiết; sửa gate cần nêu lý do
và cập nhật config/spec/tests cùng nhau. Không giảm gate để che kết quả chưa đạt.
