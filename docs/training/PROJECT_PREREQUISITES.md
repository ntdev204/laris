---
document_id: "DOC-RUNBOOK-PREREQ-001"
title: "Project Prerequisites and Owner Decisions"
document_type: "plan"
status: "DRAFT"
version: "0.2.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Project Owner"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/training/OWNER_RUNBOOK.md"
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
  - "docs/specifications/DATASET_SPECIFICATION.md"
  - "docs/specifications/LARIS_GOLD_SPECIFICATION.md"
decision_references:
  - "ADR-002"
  - "ADR-008"
  - "ADR-013"
change_summary: "G03 agent draft: preserves existing approvals and records missing source, human-gold and dependency decisions for owner handoff."
---

# Tiền điều kiện dự án và quyết định của owner

G03 là task **joint**. Owner đã quyết định bỏ qua dataset thiếu, tìm/tải STEM-VI
nếu có và giao agent chọn nguồn OCR, cài dependency. Quyết định mới và kết quả
thực hiện ở **mục 8** thay thế các mục PENDING_OWNER về nguồn/toolchain trong
bản draft ban đầu bên dưới. D05 (người gán nhãn/agreement) ban đầu được owner bỏ qua rồi mở lại ngày 2026-11-11;
G03 đã đóng, D05 hiện ghi REOPENED_D05A (xem mục 7). Không training, không thay gate.

Các mục 2–7 giữ bối cảnh khảo sát trước cài đặt; mục 8 là trạng thái mới nhất.

## 1. Chính sách đã có hiệu lực

- Giữ nguyên đủ 12 gate tại [`foundation.yaml`](../../configs/evaluation/foundation.yaml)
  và [đặc tả training](../specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md).
  Không đổi gate hoặc protocol để làm checkpoint pass. Mọi qualification cần
  held-out evidence đúng identity và owner review.
- Giữ ADR-002: không dùng foundation pretrained bên ngoài. Muốn thay đổi phải có
  ADR được duyệt; cài một thư viện không đồng nghĩa được dùng weights của nó.
- Agent không fit tokenizer, train, backward/optimizer, optimizer profiling hoặc
  chạy test có optimization. Owner thực hiện các run đã chuẩn bị và trả evidence.
- Foundation → scientific language → OCR → manuscript learning → integration →
  specialists. Chuẩn bị G03 không thực thi stage sau.
- Không chế dữ liệu/nhãn/gold, không dùng output model/OCR làm gold. Không tune
  bằng test. Weights/datasets và thông tin xác thực không đưa vào Git.
- Ngân sách compute, điều kiện dừng và quyết định tokenizer thuộc F04A sau F04;
  chưa cần owner chạy training/profiling ở G03. Runbook hiện tại là mẫu baseline,
  không phải lệnh candidate mới đã được duyệt.

## 2. Evidence và phạm vi kiểm tra

Nguồn local: [`acquisition_manifest.json`](../../data/acquisition_manifest.json),
[đặc tả dataset](../specifications/DATASET_SPECIFICATION.md) và
[báo cáo G02](../../reports/verification/baseline-reconciliation.json), kiểm tra
2026-11-11. Các số bên dưới là số **manifest ghi nhận**, chưa phải kiểm tra lại
checksum toàn bộ dữ liệu trong phiên này. Không truy cập secret/API key, không
thử tải nguồn, không xác nhận lại license upstream qua mạng. Lỗi 401 S2ORC là
ghi nhận lịch sử trong manifest, không phải kết quả request mới.

## 3. Quyền sử dụng đã ghi nhận và phần còn thiếu

| Dataset | Manifest hiện tại | Quyết định được bảo toàn | Chưa được chứng minh/cho phép |
| --- | --- | --- | --- |
| VINLI | VERIFIED; 30.376 cặp; APPROVED_BY_OWNER | Owner đã cho dùng ngày 2026-10-29 | Uploader không khai license; review trước redistribution vẫn thiếu |
| UIT-VIQUAD-V2 | VERIFIED; 39.569 mẫu; APPROVED_BY_OWNER | Owner đã cho dùng ngày 2026-10-29 | Mirror không khai SPDX; không suy rộng sang redistribution/commercial use |
| CC100-VI-CLEAN | VERIFIED; 2.700.000 bản ghi; APPROVED_BY_OWNER | Owner đã cho dùng ngày 2026-10-29 | Không có dataset license riêng; review redistribution; bounded prefix có thể lệch chủ đề |

Acceptance cũ của G03 gọi chung ba nguồn này là `NEEDS_LICENSE_REVIEW`.
Trạng thái có cấu trúc thực tế là `APPROVED_BY_OWNER`, còn notes giữ cảnh báo
review. Không hủy hay yêu cầu owner phê duyệt lại cùng phạm vi đã cho phép.
Các use approval trên là quyết định dự án được manifest ghi nhận, không tự chứng
minh quyền của upstream hoặc cho phép phân phối dữ liệu. Phân phối nằm ngoài
phạm vi đã được chứng minh và vẫn bị chặn đến khi có căn cứ/quyết định riêng.

## 4. Nguồn theo stage

Bảng tình trạng D01–D06 ban đầu đã được thay bằng sổ quyết định ở mục 7 và kết quả thực hiện ở mục 8.
Nguồn thay thế không tự được chấp nhận. S2ORC phải tuân thủ hard cap của đặc tả (dưới 20 GB và dưới 20
triệu records, không tải full dump). Một mục được owner ghi blocked chỉ ghi nhận tình trạng, không biến
dữ liệu thiếu thành sẵn có; task tiêu thụ tương ứng phải dừng khi tới dependency đó.

## 5. Human gold và đồng thuận

[Đặc tả LARIS-GOLD](../specifications/LARIS_GOLD_SPECIFICATION.md) đã yêu cầu hai
domain expert gán nhãn độc lập và người thứ ba phân xử khi Cohen's κ < 0,85.
Giữ nguyên quy tắc này; agent không tự đặt lại ngưỡng hoặc giả định đã có annotator.
Gold reasoning giữ split theo topic/paper cluster và test seal theo đặc tả.

D05 cần owner chỉ định tên/vai trò (có thể dùng định danh nội bộ) của hai người gán
và người phân xử, phạm vi chuyên môn/ngôn ngữ, cùng khả năng thực hiện. Với gold
retrieval relevance, scientific NLI/evidence/discourse, OCR text/layout và discourse
trên OCR: cần chốt guideline, đơn vị annotation, metric đồng thuận, ngưỡng chấp nhận,
cách phân xử và split/freeze **trước khi gán và trước khi xem kết quả model**.
Không tự áp Cohen's κ cho text/layout liên tục nếu protocol không phù hợp.
D05 được owner mở lại ngày 2026-11-11 (D05-a); chưa có annotator nên chưa có nhãn nào được tạo.

## 6. Toolchain

Danh sách candidate ban đầu đã được thay bằng kết quả cài đặt D06 ở mục 7 và 8 và
`reports/verification/prerequisite-setup.json`. Phê duyệt cài dependency không cho phép tải model
pretrained ngoài ADR-002 hoặc bỏ qua thứ tự stage.

## 7. Sổ quyết định

| Mục | Trạng thái | Evidence quyết định owner |
| --- | --- | --- |
| Giữ 12 gate và ADR-002 | EFFECTIVE_EXISTING_POLICY | canonical config, ADR-002 |
| Use approval VINLI/ViQuAD/CC100 | RECORDED_EXISTING_APPROVAL | Notes manifest: 2026-10-29; không mở rộng phạm vi |
| Redistribution ba nguồn trên | BLOCKED_UNVERIFIED | Không có căn cứ phê duyệt mới |
| D01 SciFact | DOWNLOADED_NEEDS_LICENSE_REVIEW | Ban đầu owner bỏ qua; sau đó agent tải bản BEIR làm nguồn G12 EN (`acquire_scifact`, `data/raw/scifact`); license mâu thuẫn, áp điều kiện phi thương mại, chờ owner ghi nhận |
| D02 S2ORC | SKIPPED_MISSING_ACCESS | Owner 2026-11-11; không dùng khóa API |
| D03 STEM-VI | APPROVED_BY_OWNER (2026-11-11) | Owner cho dùng bất chấp license chưa rõ (quyết định dự án, không phải xác nhận pháp lý; không phân phối lại). Dùng cho chẩn đoán cross-lingual và corpus khoa học sau này; vẫn là dịch máy, không bao giờ là human gold; chưa có quyền training |
| D04 OCR | SOURCE_SELECTED | Agent chọn DocLayNet (CDLA-Permissive-1.0); bounded subset ở O01A |
| D05 Human gold | REOPENED_D05A | Owner mở lại 2026-11-11, bắt đầu D05-a; chưa chỉ định A1/A2/adjudicator nên chưa có nhãn; S01A/O01A/M01A vẫn blocked; xem D05_HUMAN_GOLD_PROTOCOL.md |
| D06 Dependency | INSTALLED | Pillow, pytesseract, pypdf, Tesseract eng/vie/osd; xem prerequisite-setup.json |
| Training | NOT_EXECUTED | Không training; cài dependency đã thực hiện theo D06 |

## 8. Quyết định mới của owner và thực hiện (2026-11-11)

Owner chỉ dẫn: dataset còn thiếu thì bỏ qua; STEM-VI có thì tải, không có thì
bỏ qua; agent tự chọn nguồn OCR và tải/cài dependency. Owner sau đó cung cấp
quyền sudo; thông tin xác thực không lưu vào repository.

| Mục | Quyết định/kết quả hiện tại |
| --- | --- |
| D01 SciFact | Đã tải (BEIR, 5.183 abstract, 300 query test có qrels chuyên gia), digest đóng băng trong `foundation_retrieval.yaml`; chờ owner ghi nhận license phi thương mại |
| D02 S2ORC | SKIPPED_MISSING_ACCESS; không yêu cầu API key, không tải full dump |
| D03 STEM-VI | Tìm được VietAI/vi_pubmed; tải đúng một shard (~254 MB); owner cho dùng bất chấp license (2026-11-11); là dịch máy, không phải gold, chưa có quyền training |
| D04 OCR | Agent chọn DocLayNet từ DS4SD; chỉ chuẩn bị nguồn ở G03, chưa chạy stage OCR; acquisition bounded ở O01A sau các qualification |
| D05 Human gold | REOPENED_D05A (owner mở lại 2026-11-11): chưa chỉ định annotator/adjudicator và protocol theo loại; S01A/O01A/M01A blocked; không coi việc bỏ qua dataset là phê duyệt tự sinh gold |
| D06 Dependency | Owner cho agent tự chọn/cài; chọn Pillow 12.3.0, pytesseract 0.3.13, pypdf 7.0.1 trong `.venv`, Tesseract 5.3.4 cùng eng/vie/osd trên hệ thống |

### STEM-VI đã tải

Nguồn tác giả: [ViPubmed](https://github.com/vietai/ViPubmed), liên kết tới
[VietAI/vi_pubmed](https://huggingface.co/datasets/VietAI/vi_pubmed).
Revision `decfdcc57efa83466449ccaa658ad431a8a416d4`;
file `data/pubmed22-00000-of-00089-5cd8ea7c3541d46a.parquet`.
Đã đọc metadata Parquet: 225.697 rows, hai cột `en`/`vi`, 254.227.532 bytes.
SHA-256 `54e411a885c4a349b4bdf154c5482d131fd7acbd21edbacac6b69feb12837231`.
Local: `data/raw/vi_pubmed_candidate/`, manifest cùng thư mục; dữ liệu bị Git ignore.

Đây là abstracts y sinh dịch máy do upstream phát hành, không phải corpus STEM
bao phủ mọi ngành hoặc human gold. Thẻ HF ghi `license: cc` nhưng thiếu subtype;
MIT của repository code không tự áp cho corpus. Trạng thái
`DOWNLOADED_QUARANTINED` khi tải; owner đã cho phép dùng ngày 2026-11-11 (xem bảng quyết định). Trước đó: chưa duyệt training, chưa đưa vào registry đang train,
chưa split; lấy shard đầu, không phải random sample. Không tải toàn bộ 23 GB.

### Nguồn OCR đã chọn

[DS4SD DocLayNet](https://github.com/DS4SD/DocLayNet) cung cấp human layout
annotations; [LICENSE upstream](https://github.com/DS4SD/DocLayNet/blob/main/LICENSE)
là CDLA-Permissive-1.0. Core archive 28 GiB vượt budget 20 GB nên **không tải full**.
O01A cần subset bounded có annotations và source identity; dữ liệu cuộc thi không
mặc định được coi là tập train. Layout boxes/digital text không tự chứng nhận
OCR gold tiếng Việt, degraded pages hoặc CER. Phần thiếu theo owner được ghi skip;
qualification liên quan vẫn chưa thể pass nếu thiếu phép đo bắt buộc.

### Dependency và lệnh tái lập

Python optional extra `ocr` được ghi trong `pyproject.toml` để tái lập:

```bash
uv pip install --python .venv/bin/python -e '.[ocr]'
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-vie
/usr/bin/tesseract --version
/usr/bin/tesseract --list-langs
```

Agent đã chạy install Python và apt; chỉ probe version/language inventory, chưa
chạy model/OCR trên tài liệu, chưa training hay tạo gold. Bản fallback cục bộ
được chuẩn bị trước khi có sudo nằm trong `artifacts/tools/ocr/` (Git ignored).
Sau cài hệ thống, `.venv/bin/tesseract` trỏ tới binary hệ thống. Evidence setup:
[prerequisite-setup.json](../../reports/verification/prerequisite-setup.json).

Owner đã mở lại **D05** từ D05-a (người gán nhãn và protocol/agreement); S01A, O01A, M01A, R02 vẫn
blocked tới khi có annotator và protocol của từng loại. Bỏ qua dataset không
có nghĩa bỏ gate, tự promote model hoặc tự tạo người/nhãn gold.
