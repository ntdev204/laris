# Implement Plan: tái cấu trúc, sửa lỗi, kiểm thử model, gọn docs, vệ sinh repo

> Trạng thái: **đang triển khai** (Phase 0: PR #252 chờ merge; Phase 1: đang làm). Ngày lập: 2026-10-29.
> Phạm vi: (1) tái cấu trúc thư mục, (2) sửa các lỗi đã phát hiện, (3) train xong model ngôn ngữ thì kiểm thử ngay bằng CLI, (4) gọn docs, (5) vệ sinh repo.

---

## 0. Nguyên tắc

1. **Đặt tên theo chức năng.** Không dùng tên theo phiên bản, giai đoạn hay kích thước (`stage1`, `model1`, `500m`, `v2`, `m2`, `layer0`...) cho file, module, class, config, CLI, nhánh hay thư mục artifact. Phiên bản, kích thước và giai đoạn là *giá trị cấu hình hoặc metadata*, không phải tên.
   - Ngoại lệ: tên chính thức của dataset bên ngoài (ví dụ `UIT-ViQuAD2.0`) giữ nguyên vì là định danh nguồn.
2. **Tuân thủ ADR-011/012**: tổ chức theo domain package, không quay lại cấu trúc `layerN`.
3. **Git Flow.** Mỗi phase là 1 issue (#244-#251), 1 nhánh `feature/<issue-id>-<mô-tả-chức-năng>` (GIT_FLOW chỉ định nghĩa `feature/`, `release/`, `hotfix/`) tách từ `develop`, 1 PR (squash). Merge xong thì xóa nhánh.
4. **Thứ tự: sửa lỗi → tái cấu trúc → tính năng → docs.** Sửa lỗi (đổi hành vi) trước, có test bảo vệ. Tái cấu trúc làm thuần túy bằng `git mv`, không đổi hành vi. Docs viết cuối cùng để khớp với cấu trúc đã chốt.
5. **Mọi PR phải qua đủ các cổng**: `pytest`, `ruff check .`, `mypy src`, `python3 scripts/validate_docs.py`.
6. **Đã giải quyết:** `gh` đã cài và đăng nhập; issue #244-#251 đã tạo. Ban đầu cần cài `gh` và đăng nhập (`sudo apt install gh && gh auth login`) để tạo issue và PR.

---

## 1. Bảng đổi tên theo chức năng

### Mã nguồn và script

| Hiện tại | Tên mới |
|---|---|
| `scripts/train_stage1.py` | lệnh `laris train language-encoder` (`src/laris/cli/commands/train.py`) |
| `Stage1LanguageTrainer` | `LanguageEncoderTrainer` |
| `Stage1LossCalculator` | `MultiTaskLossCalculator` |
| `TransformerEncoder500MConfig` / `TransformerEncoderConfig` | một class `LanguageEncoderConfig` + các preset kích thước trong YAML (`compact.yaml`, `large.yaml`); số tham số chỉ là giá trị cấu hình |
| `configs/model1_foundation.yaml` | `configs/model/language_encoder/compact.yaml`, `large.yaml` |
| `artifacts/checkpoints/stage1` | `artifacts/checkpoints/language_encoder/<run-id>/` |
| `--model-tier 500m` | `--model-config configs/model/language_encoder/large.yaml` |
| `scripts/acquire_datasets.py` | `laris data acquire` |
| `scripts/partition_datasets.py` | `laris data partition` |
| `scripts/train_tokenizer.py` | `laris train tokenizer` |

### Test

| Hiện tại | Tên mới |
|---|---|
| `tests/unit/test_500m_scaling_and_training.py` | `tests/unit/language/test_encoder_scaling_and_training.py` |
| `tests/integration/test_m2_reproducibility_exit_gate.py` | `tests/integration/test_language_artifact_reproducibility.py` |
| `tests/integration/test_layer0_pipeline.py` | `tests/integration/test_corpus_ingestion_pipeline.py` |
| `tests/unit/test_expansion_dataset_acquisition.py` | `tests/unit/corpus/test_bilingual_dataset_acquisition.py` |

### Docs và kế hoạch

| Hiện tại | Tên mới |
|---|---|
| Milestone `M0…M10` làm tiêu đề | Tiêu đề theo năng lực, ví dụ "Corpus ingestion", "Language encoder", "Hybrid retrieval". Mã M chỉ còn là metadata nếu cần tra cứu lịch sử |
| `STAGED_LEARNING_PIPELINE.md` | gộp vào `LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md` |

---

## 2. Phase 0: Hoàn tất bổ sung dataset song ngữ (nhánh hiện tại)

- **Nhánh:** `feature/244-bilingual-dataset-acquisition` (đổi tên từ `feature/tmp-expand-bilingual-datasets`).
- **Việc cần làm:**
  - [ ] Chờ CC-100 VI tải xong, kiểm tra marker `.complete` và manifest.
  - [ ] Sửa `test_training_readiness_contracts.py`: bỏ con số cứng `5106491`, thay bằng bất biến tổng = Σ các entry VERIFIED/DOWNLOADED.
  - [ ] Cập nhật số liệu thật trong `DATASET_SPECIFICATION.md`, CHANGELOG, BACKLOG, SESSION.
  - [ ] Chạy đủ các cổng, mở PR vào `develop`.

---

## 3. Phase 1: Vệ sinh repo

- **Nhánh:** `feature/245-repo-hygiene`.

| Việc | Chi tiết |
|---|---|
| Xóa rác cục bộ | `src/laris/layers/` (chỉ còn `__pycache__`, làm `test_no_numbered_layer_directories_exist` lỗi), mọi `__pycache__`, `.mypy_cache`, `.ruff_cache`, `src/laris.egg-info` cũ |
| `.gitignore` | Thêm `artifacts/checkpoints/`, `artifacts/evaluations/`, `artifacts/runs/`, `data/raw/**`, `data/processed/**` (giữ `.gitkeep`), `*.tmp`, `nohup.out` |
| Test độc lập | Test đang trỏ tới `data/raw/sample_paper.pdf`, `data/processed/train.jsonl`, `data/cache/tokens.bin` → chuyển sang `tmp_path` hoặc `tests/fixtures/` |
| Pytest markers | Khai báo `torch`, `gpu`, `network`, `slow` trong `pyproject.toml` |
| Pre-commit | Thêm `.pre-commit-config.yaml` chạy ruff, mypy, `validate_docs` |
| Lệnh chung | `Makefile`: `make check`, `make test`, `make lint` |
| Dependency | Thêm extra `[training]` = torch + sentencepiece + bitsandbytes (tùy chọn) |
| Nhánh | Xóa các nhánh local/remote đã merge |

- **Tiêu chí hoàn thành:** `git status` sạch sau `make check`, và toàn bộ test pass trên máy dev.

---

## 4. Phase 2: Sửa lỗi toàn vẹn dữ liệu và trainer

- **Nhánh:** `feature/246-training-data-integrity`.
- **Quy tắc:** mỗi lỗi có một test tái hiện, viết trước khi sửa.

| # | Lỗi (vị trí hiện tại) | Cách sửa | Test chấp nhận |
|---|---|---|---|
| 1 | Loader đọc lẫn `val`/`test.parquet` vào train (`language/dataloader.py:256`) | Thêm tham số `split="train"`, chỉ glob `{split}*.parquet` | Fixture có đủ 3 split; loader train không bao giờ trả bản ghi của val/test |
| 2 | Nhãn QA giả (`start = len(q)+2`, `end = start+4`) | Đổi offset ký tự của đáp án sang vị trí token (cần offset từ tokenizer); đáp án bị cắt thì trỏ về `[CLS]` | Span giải mã ra đúng chuỗi đáp án |
| 3 | Tokenizer dự phòng dùng `hash()`, kết quả đổi theo `PYTHONHASHSEED` | Lệnh train bắt buộc `--tokenizer-model`; bản dự phòng chỉ cho test, dùng `zlib.crc32` | 2 subprocess với seed khác nhau cho ra cùng ID |
| 4 | Không có dữ liệu thì tự dùng dữ liệu ngẫu nhiên (`fallback_to_synthetic=True`) | Mặc định `False`; in số shard của từng task | `data_dir` rỗng thì báo `FileNotFoundError` |
| 5 | Trainer không chuyển model sang device (3 test lỗi trên GPU) | Gọi `model.to(device)` trước khi tạo optimizer | Test trainer pass trên cả CPU và CUDA |
| 6 | Shard hỏng gây vòng lặp vô hạn (`except Exception: continue` trong `while True`) | Ghi log, loại shard hỏng; hết shard thì báo lỗi | Fixture shard hỏng không làm treo |
| 7 | 8-bit Adam tự chuyển về AdamW mà không báo | Cảnh báo rõ, và tính lại VRAM theo AdamW | Kiểm tra warning |

- **CI:** thêm job cài torch bản CPU để chạy các test có marker `torch`, vì hiện CI bỏ qua toàn bộ nhóm này.

---

## 5. Phase 3: Tái cấu trúc thư mục (không đổi hành vi)

- **Nhánh:** `feature/247-functional-package-layout`.
- **Tài liệu:** thêm **ADR-013 "Functional sub-package layout and CLI"** và một mục trong `DECISION_LOG.md`.

### 5.1 Cấu trúc đích

```
src/laris/
├── cli/                          # entrypoint `laris` qua [project.scripts]
│   ├── __main__.py
│   └── commands/
│       ├── data.py               #   laris data acquire | partition | status
│       ├── train.py              #   laris train tokenizer | language-encoder
│       ├── evaluate.py           #   laris evaluate language-encoder
│       ├── infer.py              #   laris infer fill-mask | nli | paraphrase | similarity | qa | embed
│       └── docs.py               #   laris docs validate
├── corpus/
│   ├── acquisition/              # logic chuyển ra từ scripts/acquire_datasets.py
│   │   ├── registry.py           #   DATASET_ID → acquirer (đọc configs/datasets/*.yaml)
│   │   ├── manifest.py           #   quy tắc trạng thái, tính tổng
│   │   └── sources/              #   huggingface.py, cc100.py, universal_dependencies.py, wikipedia.py
│   ├── splits/                   # tách task_splits.py (1.205 dòng)
│   │   ├── coverage.py
│   │   ├── manifest.py
│   │   └── partitioners/         #   mỗi dataset 1 file, đăng ký qua registry
│   └── dedup.py, normalizer.py, storage.py, pipeline.py, schemas.py
├── language/
│   ├── tokenization/             # tokenizer.py, tokenizer_trainer.py
│   ├── encoder/                  # neural.py → transformer.py, encoder.py, config.py, config_handoff.py
│   ├── training/                 # dataloader.py, trainer.py, losses.py, profiling.py, checkpoint.py, artifacts.py
│   ├── evaluation/               # MỚI: metrics.py, evaluator.py (xem Phase 4b)
│   ├── inference/                # MỚI: predictor.py, nạp checkpoint + tokenizer
│   └── benchmarks/               # stem_benchmark.py
├── retrieval/
│   ├── bm25.py                   # chuyển từ language/
│   └── benchmarks/               # retrieval_benchmark.py (chuyển từ language/), benchmark.py
└── core, config, scientific, graph, reasoning, orchestration, execution, evaluation, reporting  (giữ nguyên)

configs/
├── datasets/                     # mỗi dataset 1 YAML: nguồn, revision, license, min_rows, task
├── model/language_encoder/       # compact.yaml, large.yaml
├── training/language_encoder.yaml  # lr, warmup, batch, precision, accumulation
└── evaluation/language_encoder.yaml  # task, split, metric, ngưỡng chấp nhận

scripts/   # shim mỏng gọi laris.cli trong 1 release, sau đó xóa; giữ verify_target_server.sh
tests/
├── unit/<domain>/                # chia theo domain package
├── contract/  integration/  documentation/  cli/ (MỚI)
└── fixtures/                     # gồm checkpoint tí hon dùng cho test CLI
```

### 5.2 Cách làm

1. Dùng `git mv` để giữ lịch sử, rồi dùng script viết lại import. Không giữ shim import cũ vì đây là package nội bộ.
2. Đổi tên class và config theo bảng ở mục 1.
3. Cập nhật `__init__.py` re-export và `tests/contract/test_domain_packages.py`, thêm contract cho các sub-package mới.
4. Chia PR thành 3 commit: `corpus`, `language` + `retrieval`, `cli` + `scripts` + `configs`.

### 5.3 Tiêu chí hoàn thành

- Số test pass không đổi so với trước refactor.
- Grep không còn tên cũ: `stage1`, `Stage1`, `500M`, `model1`, `layer0`, `m2_`.

---

## 6. Phase 4: Train model ngôn ngữ, rồi kiểm thử ngay bằng CLI

### 6a. Vòng train đầy đủ

- **Nhánh:** `feature/248-language-encoder-training-loop`.
- **Việc cần làm:**
  - [ ] Checkpoint gồm model, optimizer, scheduler, RNG, step và manifest của lần chạy (config, hash dữ liệu, commit). Hỗ trợ `--resume`.
  - [ ] `torch.autocast` cho bf16/fp16 để `--precision` thật sự có tác dụng.
  - [ ] LR warmup và cosine scheduler.
  - [ ] Đếm step theo lần optimizer cập nhật.
  - [ ] Tích lũy gradient qua nhiều task khác nhau.
  - [ ] Đánh giá định kỳ trên **val** và early stopping. Tập **test không bao giờ được đọc khi train**.
  - [ ] Lệnh:
    ```
    laris train language-encoder \
      --model-config configs/model/language_encoder/large.yaml \
      --training-config configs/training/language_encoder.yaml \
      --tokenizer-model artifacts/tokenizer/<run-id>/tokenizer.model \
      --data-dir data/processed --output-dir artifacts/checkpoints/language_encoder
    ```
    Vẫn giữ rào cản `LARIS_TRAINING_AUTHORIZED=1` và `--profile-only`.

### 6b. Kiểm thử model sau khi train bằng CLI (bắt buộc)

- **Nhánh:** `feature/250-language-encoder-cli-evaluation`.
- **Yêu cầu:** train xong thì chạy kiểm thử ngay. Lệnh train có cờ `--evaluate-after` (mặc định bật) để tự gọi bước đánh giá trên checkpoint tốt nhất. Lệnh đánh giá cũng chạy được độc lập.

**Đánh giá định lượng trên tập test:**

```
laris evaluate language-encoder \
  --checkpoint artifacts/checkpoints/language_encoder/<run-id>/best \
  --split test \
  --config configs/evaluation/language_encoder.yaml \
  --output artifacts/evaluations/language_encoder/<run-id>.json
```

| Task | Tập test | Metric | So với baseline |
|---|---|---|---|
| Masked LM | Wikipedia VI/EN, CC-100 VI (phần test) | perplexity, độ chính xác top-1 | unigram |
| NLI | ViNLI, AllNLI/ANLI, FEVER (labelled_dev, chia theo claim) | accuracy, macro-F1 | dự đoán lớp đa số |
| Paraphrase | Quora, PAWS | F1, AUC | ngẫu nhiên |
| Similarity | STS-B, ViSTS | Pearson, Spearman | cosine BM25 |
| QA trích xuất | SQuAD, UIT-ViQuAD (dev, không dùng test riêng tư) | Exact Match, F1 | câu đầu ngữ cảnh |

- Kết quả được ghi ra JSON và một bảng in ra terminal: metric, baseline, chênh lệch, đạt hay không.
- Exit code ≠ 0 nếu một task dưới ngưỡng trong `configs/evaluation/language_encoder.yaml`. Theo ADR-008, chưa qua đánh giá thì không được tuyên bố năng lực.
- Báo cáo tách riêng theo ngôn ngữ (VI/EN).

**Kiểm thử thủ công và smoke test bằng lệnh suy luận:**

```
laris infer fill-mask   --checkpoint ... --text "Hà Nội là [MASK] của Việt Nam."
laris infer nli         --checkpoint ... --premise "..." --hypothesis "..."
laris infer paraphrase  --checkpoint ... --a "..." --b "..."
laris infer similarity  --checkpoint ... --a "..." --b "..."
laris infer qa          --checkpoint ... --context "..." --question "..."
laris infer embed       --checkpoint ... --input file.txt --output emb.npy
```

- Lệnh suy luận không cần cờ cho phép train.
- Lệnh từ chối checkpoint nếu manifest thiếu hoặc hash tokenizer không khớp.

**Test tự động cho CLI (`tests/cli/`):**

- [ ] Train một model tí hon trên fixture (2 step, CPU), rồi chạy `laris evaluate`, kiểm tra JSON đúng schema và exit code.
- [ ] Chạy từng lệnh `laris infer` trên checkpoint fixture: output đúng định dạng, kết quả xác định với seed cố định.
- [ ] Kiểm tra đánh giá từ chối `--split train`, và từ chối khi dữ liệu test trùng với train (kiểm tra dedup bằng digest).
- [ ] Đưa vào job CI torch bản CPU.

### 6c. Partition và tích hợp các dataset mới

- **Nhánh:** `feature/249-bilingual-dataset-partitioning`.
- **Việc cần làm:**
  - [ ] Viết partitioner cho ViNLI, ViSTS, UIT-ViQuAD2.0, FEVER, HotpotQA, CC-100 VI.
  - [ ] Chống trùng lặp giữa các tập: ViQuAD2 với ViQuAD 1.1, CC-100 với Wikipedia-VI.
  - [ ] Map dữ liệu vào đúng thư mục task của loader.
- **Phụ thuộc:** 6a cần 6c để có dữ liệu thật. 6b cần tập test do 6c tạo ra.

---

## 7. Phase 5: Gọn docs (72 → khoảng 40 file)

- **Nhánh:** `feature/251-documentation-consolidation`.
- Đọc kỹ từng cặp file trước khi gộp; bảng dưới là danh sách ứng viên.

| Hiện tại | Đề xuất |
|---|---|
| `adr/ADR_TEMPLATE.md` và `templates/ADR_TEMPLATE.md` (trùng, lệch nhau) | Giữ bản trong `templates/` |
| `DOCUMENTATION_STANDARD.md` + `DOCUMENT_LIFECYCLE.md` | Gộp thành `development/DOCUMENTATION.md` |
| `RELEASE_NOTES.md` + `CHANGELOG.md` | Giữ `CHANGELOG.md` ở gốc; sửa các test đang trỏ tới `RELEASE_NOTES` |
| `plans/BACKLOG.md` (911 dòng) | Chỉ giữ việc còn mở; phần đã xong chuyển sang `docs/archive/` |
| `IMPLEMENTATION_ROADMAP.md` + `MILESTONES.md` | Gộp thành `plans/ROADMAP.md`, tiêu đề theo năng lực |
| `STAGED_LEARNING_PIPELINE.md` + `NATURAL_LANGUAGE_TRAINING_SPECIFICATION.md` | Gộp thành `LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md`, kèm mục "Đánh giá bằng CLI" |
| `AGENT`/`SKILL`/`TOOL`/`WORKFLOW_SPECIFICATION.md` | Gộp thành `ORCHESTRATION_SPECIFICATION.md` |
| `research/` (8 file ngắn) | Gộp các file trùng chủ đề |
| `IDEA.md` (373 dòng) | Rút phần tầm nhìn vào `SYSTEM_OVERVIEW.md`, bản gốc chuyển vào `archive/` |
| `SESSION.md` (115 dòng) | Rút xuống khoảng 50 dòng: môi trường, lệnh CLI mới, trạng thái |
| `DATASET_SPECIFICATION.md` | Sửa số liệu dự kiến bị thổi phồng; đặt lại mục tiêu theo số thật |
| (mới) `docs/development/CLI.md` | Tham chiếu mọi lệnh `laris ...` |

- **Việc đi kèm:**
  - [x] Cập nhật `validate_docs.py` để bỏ qua `docs/archive/`.
  - [x] Kiểm tra `related_documents` không trỏ tới file đã bị gộp.
  - [x] Cập nhật `docs/README.md` làm mục lục duy nhất.
  - [x] Cập nhật `README.md` gốc theo lệnh CLI mới.

---

## 8. Thứ tự và phụ thuộc

```
Phase 0 → Phase 1 → Phase 2 → Phase 3 ─┬→ 6c dataset partitioning ─┐
                                       └→ 6a training loop ─────────┴→ 6b CLI evaluation → Phase 5 docs
```

| Phase | Nhánh | Phụ thuộc |
|---|---|---|
| 0 | `feature/244-bilingual-dataset-acquisition` | CC-100 tải xong |
| 1 | `feature/245-repo-hygiene` | 0 |
| 2 | `feature/246-training-data-integrity` | 1 |
| 3 | `feature/247-functional-package-layout` | 2 |
| 6a | `feature/248-language-encoder-training-loop` | 3 |
| 6c | `feature/249-bilingual-dataset-partitioning` | 3 |
| 6b | `feature/250-language-encoder-cli-evaluation` | 6a, 6c |
| 5 | `feature/251-documentation-consolidation` | 6b |

---

## 9. Rủi ro

| Rủi ro | Giảm thiểu |
|---|---|
| Refactor làm hỏng import ở nhiều test và docs | Đổi tên bằng script, grep tên cũ, giữ nguyên số test pass |
| Tập test bị lộ vào train | Sửa lỗi #1; kiểm tra dedup bằng digest trong `laris evaluate`; đánh giá từ chối `--split train` |
| Ước tính VRAM sai khi không có bitsandbytes | Sửa lỗi #7; chạy `--profile-only` thật trên GPU trước khi train |
| License chưa duyệt (ViNLI, UIT-ViQuAD2.0, CC-100) | Train mặc định loại các dataset `NEEDS_LICENSE_REVIEW`, chỉ đưa vào khi có cờ `--include-unreviewed-licenses` |
| Không đạt ngưỡng đánh giá | Ngưỡng ban đầu = baseline + biên nhỏ; cập nhật ngưỡng qua PR có số liệu |

---

## 10. Cần quyết định trước khi code

1. **Shim import cũ:** đề xuất **không giữ**.
2. **`scripts/`:** giữ shim gọi CLI trong 1 release rồi xóa? Đề xuất **có**.
3. **BACKLOG phần đã xong:** chuyển vào `docs/archive/` hay xóa hẳn? Đề xuất **archive**.
4. **Ngưỡng chấp nhận ban đầu** cho `laris evaluate`: dùng baseline + biên nhỏ, hay bạn có ngưỡng mục tiêu cụ thể?
5. **Cài `gh` và đăng nhập** để tạo issue cho từng phase.
