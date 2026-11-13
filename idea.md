# Ý tưởng: LARIS thế hệ 2 bằng Rust (ghi chép thảo luận 2026-11-13)

Tài liệu bàn giao cho phiên mới. Ghi lại những gì chủ dự án đã quyết, những gì là khuyến nghị
của Claude, những gì còn mở, các số liệu đã đo được, và trạng thái phát hành đang làm dở.
Đây **chưa phải** đặc tả: chưa có ADR, chưa có task trong `.claude/spec/`, chưa có dòng Rust nào.

## 1. Chủ dự án đã quyết

- **Bỏ Ink và Node.** Giao diện viết lại thành TUI bằng Rust, trải nghiệm giống Claude Code.
- **Viết lại lõi LARIS bằng Rust.** Không còn Python ở bất cứ đâu, trừ **bên mô hình (AI)**, phần này giữ nguyên.
- **Đi theo hướng codex và Claude Code:** CLI chạy harness ngay trên máy người dùng (vòng agent, công cụ,
  sandbox), chỉ gọi mô hình ra xa. Không đưa vòng agent lên server.
- **Làm chủ công nghệ ở "cấp 1":** tự viết toàn bộ logic (vòng agent, chính sách, bằng chứng, brain, giao thức, TUI)
  và dùng thư viện nền đã kiểm chứng (tokio, rustls, crossterm/ratatui, serde...), gom vào repo bằng `cargo vendor`
  và kiểm bằng `cargo-deny`.
- **Sandbox không tự viết mà fork từ codex** (Apache-2.0).
- **Không làm thư mục `/rust`.** Xây trực tiếp trên một nhánh mới, `Cargo.toml` nằm ở gốc.
- **Cài nhanh gọn như claude-code / codex-cli.**
- **Không trùng lặp:** mỗi yêu cầu chỉ có một bản cài đặt, và các yêu cầu phải được tách rõ theo chủ sở hữu.
- **Đóng băng thế hệ hiện tại:** gộp các nhánh đang có, phát hành, tag, và khoá thành nhánh `laris-v1`
  (đang làm dở, xem mục 7).

## 2. Kiến trúc đang hướng tới (khuyến nghị, chủ dự án chưa duyệt hết)

```
Cargo.toml (workspace ở gốc)
crates/
  laris-protocol      giao thức giữa UI và lõi, sinh từ một schema duy nhất
  laris-core          vòng agent nhiều lượt: kế hoạch, tự kiểm tra, nén ngữ cảnh, chạy công cụ   [thư viện]
  laris-model-client  gọi server qua P1 (/chat/completions + SSE)
  laris-tools         đọc, ghi, sửa, shell, tìm kiếm, nạp tài liệu
  laris-policy        quyền, hook, luật cục bộ
  laris-evidence      cổng dẫn nguồn (ADR-004)
  laris-brain         định dạng vault, chỉ mục, BM25
  laris-sandbox       fork từ codex
  laris-tui           chỉ là UI, gọi laris-core qua laris-protocol
  laris-cli           binary `laris`
server/               Python cho tới khi client Rust xong (xem mục 4)
model/                Python: phục vụ mô hình, research, huấn luyện — giữ nguyên
.laris/  docs/  scripts/
```

- **Mặc định:** UI và lõi chạy chung một tiến trình (nhanh nhất). Vì có giao thức tách sẵn nên sau này có thể
  chạy lõi thành daemon (`laris daemon`) để IDE hay UI khác nối vào. Codex làm đúng như vậy với `app-server`.
- **E1 biến mất:** E1 là giao thức giữa Ink và engine Python. Khi TUI và lõi cùng một binary thì không cần nó nữa.
- **`shared/` của Python biến mất.** Trong một workspace Rust, crate dùng chung (giao thức, định dạng vault, BM25)
  là *một* bản cài đặt dùng ở hai nơi. Điều đó hợp lệ. Trùng lặp chỉ xảy ra khi cùng một yêu cầu được cài
  ở hai ngôn ngữ.
- **Giao thức P1/P2 và `/chat/completions` giữ nguyên,** để khối mô hình không phải sửa và client Rust chạy được
  với server Python hiện tại.

## 3. Một chủ cho mỗi yêu cầu (khuyến nghị)

| Chủ | Mã yêu cầu hiện có | Trách nhiệm |
|---|---|---|
| Client (Rust) | SR-C1–C10, SR-V1–V6, phần client của SR-H3/H4 | TUI, lệnh, quyền, hook, sandbox, vòng agent, vault dự án, SQLite, che bí mật của người dùng, đăng nhập |
| Server | SR-S4–S7, SR-H7, SR-H9, SR-B1–B6 | khoá và hạn mức, system prompt/luật/workflow (chỉ ở đây), brain của hệ thống, chặn lộ chính sách, trace, gọi mô hình |
| Mô hình (Python) | SR-S3, SR-H6, SR-A1–A6 | phục vụ mô hình, NLP khoa học, huấn luyện |
| Giao thức | SR-S2 | P1 (client–server), P2 (server–mô hình), một schema |

Nguồn trùng hiện nay (đã kiểm trong mã):
- Có **hai vòng lặp**: `client/agent/loop.py` (`AgentSession`, 646 dòng) và
  `server/gateway/service.py` (`PolicyGateway._stream`, 488 dòng).
- `shared/harness/guard.py` phục vụ **hai mục đích khác nhau**: che bí mật của người dùng (client) và chặn lộ
  chính sách hệ thống (server). Phải tách thành hai yêu cầu, mỗi yêu cầu một chủ.
- Server import từ `shared/` các mô-đun `harness.guard`, `harness.trust`, `harness.runtime`, `policy.workflows`,
  `plan`, `brain`, `backend`, `config.runtime_schemas`.

## 4. Server

- LARIS cần server vì các yêu cầu buộc phải có một bên đáng tin: brain và system prompt bí mật (SR-B3),
  khoá và hạn mức (SR-H9), GPU dùng chung (SR-S3), trace để kiểm toán. Codex và Claude Code không có server riêng
  vì máy chủ của hãng mô hình đóng vai đó.
- Server là **cổng đứng trước mô hình**, không chạy vòng agent.
- **Khuyến nghị:** giữ Python cho tới khi client Rust xong, sau đó viết lại server bằng Rust thành một chương trình
  riêng. Cái được là bộ nhớ thấp, ảnh Docker nhỏ, cùng crate giao thức; **không phải tốc độ**, vì nút thắt là GPU.
  Cần thêm thư viện (axum, sqlx, rustls), phải được chủ dự án duyệt.
- **Chế độ trực tiếp** (client gọi thẳng nhà cung cấp mô hình, bỏ qua server): khuyến nghị **không làm** ở bản đầu,
  vì nó bỏ qua SR-B3 và SR-H9, và D16 đã chủ ý không có chế độ offline.

## 5. Research (khuyến nghị)

- `research/` (khoảng 20k dòng) cùng `shared/language`, `scientific`, `scholarly`, `graph` (khoảng 9,8k dòng)
  thuộc **bên mô hình**: ở lại Python, gom vào `model/`.
- Client hiện dùng một ít trong đó (`scientific.extractor` 3 chỗ, `scholarly` 3 chỗ): biến chúng thành
  **công cụ phía server**, để client Rust không có NLP nào. Cần kiểm hết các chỗ gọi trước khi chốt.
- `vault` (2k dòng), `retrieval`/BM25 (2,5k), `brain` là harness: port sang Rust (`laris-brain`).

## 6. Số liệu đã đo

**Codex** (`github.com/openai/codex`, commit `aa5f492`, 2026-11-13, Apache-2.0):
- Rust, 135 crate, khoảng 2,35 triệu dòng (`core` 525k, `tui` 514k, `app-server` 218k).
- `tui` **không import `codex_core`**. Nó đi qua `app-server-client`, và crate này nhúng `codex-app-server` cùng
  `codex-core` ngay trong tiến trình.
- Giao thức app-server có khoảng 187 yêu cầu và 96 thông báo, nhiều phần gắn với OpenAI. E1 của LARIS có khoảng 48.
- Chỉ hỗ trợ Responses API: `wire_api = "chat"` "is no longer supported".
- Sandbox, số dòng mã riêng: `windows-sandbox-rs` 25.268, `shell-command` 8.149, `linux-sandbox` 4.994,
  `sandboxing` 4.894, `apply-patch` 4.500, `execpolicy` 2.160, `process-hardening` + `bwrap` 344.
- Nhưng sandbox **dính chặt** vào phần còn lại: `linux-sandbox` kéo theo 17 crate (khoảng 125k dòng) qua
  `codex-protocol`, `network-proxy`, `uds`, `otel`, `config`, `api`. Fork nghĩa là cắt lấy cơ chế hệ điều hành
  (Landlock/seccomp/bwrap, Seatbelt, token hạn chế/ACL/job object trên Windows) và thay kiểu của `codex-protocol`.
  Phải giữ `LICENSE`, `NOTICE`, đánh dấu file đã sửa, và ghi commit gốc vào một file `THIRD_PARTY`.

**LARIS** (Python):
- Số dòng: `client` 7,8k, `shared` 19k, `server` 2,7k, `model` 2,3k, `protocol` 0,75k, `research` 20k, Ink 1,7k.
- Cài chậm vì: gói npm 105–112 MB (PyInstaller), registry npm trễ tới 27 phút, sandbox còn tạo venv.

## 7. Phân phối mục tiêu

- Một binary tĩnh cho mỗi nền tảng (Linux musl, macOS, Windows MSVC), bật LTO và strip; đo kích thước ở cột mốc đầu.
- Cài bằng một dòng: `curl -fsSL …/install.sh | sh` và `irm …/install.ps1 | iex`, tải từ GitHub Releases,
  kiểm checksum và chữ ký.
- npm chỉ còn là vỏ mỏng chọn binary theo nền tảng (như `codex-cli/bin/codex.js`). Sau đó tính Homebrew, winget, scoop.
- Người dùng vẫn chạy `python` của họ trong shell và sandbox của agent, vì đó là mã nghiên cứu của họ.

## 8. Chuyển đổi an toàn

- Không xoá gì của thế hệ Python cho tới khi bản Rust đạt ngang. Xoá chỉ khi chủ dự án cho phép bằng lời.
- **Chín kịch bản ghi sẵn của Ink acceptance cùng bộ acceptance của engine là đặc tả hành vi:** dùng làm test vàng
  cho lõi Rust.
- Dữ liệu cũ phải đọc được: vault Markdown, SQLite, `settings.json`, `integrity.lock`, JSONL.
- Khi bản Rust qua đủ kịch bản vàng, nhánh mới gộp vào `main` và phát hành 3.0.

## 9. Còn mở, cần chủ dự án quyết

1. Tên nhánh tích hợp mới (đề xuất `next`, cắt từ `main` tại điểm khoá `laris-v1`).
2. Thời điểm viết lại server bằng Rust: sau client (khuyến nghị) hay sớm hơn.
3. Chế độ trực tiếp: không làm ở bản đầu?
4. Cổng dẫn nguồn ở **một** nơi: đề xuất server trả danh sách bằng chứng của brain (id và đoạn) trong `LarisMeta`
   của P1, và client kiểm một lần trước khi hiển thị. Việc này thêm một trường vào P1.
5. Thu dữ liệu học (`client/learning`): đề xuất ở client (SR-B5), cần đọc mã trước khi chốt.
6. Duyệt phụ thuộc mới: Rust toolchain và các crate (máy hiện tại chưa có `cargo`).
7. Ưu tiên sau task tài liệu: đo đạc sandbox (Windows trước) hay TUI trước.

## 10. Đề xuất thứ tự công việc

1. **Task tài liệu (chưa có mã):** tách `spec.md` thành `spec/client.md`, `server.md`, `model.md`, `protocol.md`
   theo bảng một chủ, phân lại nhóm SR-H, viết ADR mới (D27 trở đi) thay quyết định "không đổi kiến trúc" ngày 13/11,
   và thêm kiểm tra vào `validate_spec.py`: mỗi yêu cầu thuộc đúng một file.
2. Đo đạc sandbox: cắt crate của codex xem còn bao nhiêu dòng, Windows trước.
3. Workspace Rust với TUI chạy trên lõi giả.
4. Lõi vòng agent chạy được chín kịch bản vàng.
5. Công cụ, chính sách, bằng chứng, brain, từng bước.
6. Phân phối: binary, script cài, vỏ npm.
7. Server bằng Rust (chương trình riêng).

Quy tắc giữ nguyên: một task, một nhánh, một phiên; cập nhật cả ba file sổ cái và chạy
`python scripts/validate_spec.py`; không huấn luyện; mô hình nền NOT QUALIFIED; không cài phụ thuộc khi chưa được duyệt.

## 11. Trạng thái lúc kết thúc phiên (đang làm dở)

Phát hành 2.2.0 đã được chủ dự án cho phép trong chat ("commit, push, merge toàn bộ nhánh hiện tại,
publish tag và release luôn và khóa thành branch laris-v1").

**Đã xong:**
- PR #372 (copy sạch, `/copy`), #373 (kho trống là lỗi vĩnh viễn), #374 (client bỏ qua `configs/default.yaml`
  của dự án), #375 (T89: lời chào không gọi tìm kiếm) đã gộp vào `develop`, CI xanh.
- PR #376 (`develop` vào `main`) đã gộp, CI xanh.

**Đang dở trên nhánh cục bộ `release/2.2.0`** (cắt từ `main` tại `625ab84`, **chưa commit, chưa đẩy**):
- Nâng phiên bản lên 2.2.0 ở `pyproject.toml`, `src/laris/shared/core/__init__.py`, `packaging/npm/package.json`,
  `packaging/npm/package-lock.json` (chỉ dòng 3 và 9; các dòng `mimic-fn` không đụng), `tests/unit/test_env_smoke.py`.
- CHANGELOG: đã gom mục `[Unreleased]` thành `[2.2.0] - 2026-11-13`, một mục Added, một mục Fixed.
- **Chưa làm:** thêm task T90 (phát hành 2.2.0 và khoá `laris-v1`) vào sổ cái, chạy `validate_spec.py`.

**Còn lại:**
1. Commit, đẩy `release/2.2.0`, mở PR vào `main`, chờ CI, gộp.
2. Tag `v2.2.0` trên commit gộp; CI publish sáu gói npm; tạo GitHub Release từ changelog bằng tay
   (workflow không tự tạo).
3. Gộp ngược `main` vào `develop`, xoá nhánh release.
4. Tạo nhánh `laris-v1` từ commit của tag và khoá nó: cấm xoá, cấm force-push, bắt buộc PR.
5. Đóng T90 trong sổ cái.

**Cần biết thêm:**
- Bốn file corpus của chủ dự án (`data/acquisition_manifest.json`,
  `src/laris/research/corpus/acquisition/sources/s2orc.py`, `tests/unit/corpus/test_dataset_acquisition.py`,
  `tests/unit/corpus/test_task_splits.py`) đã bị một commit cũ cuốn nhầm vào nhánh copy. Chúng đã được gỡ khỏi
  bản phát hành và giữ ở nhánh cục bộ **`wip/corpus-acquisition-changes`** (`b9a629f`, chưa đẩy).
- Test `tests/unit/corpus/test_task_splits.py::test_audit_dataset_inventory_from_manifest` lỗi trên `develop`
  cả khi không có thay đổi nào của phiên này.
- Nhánh `feature/fix-saved-server-address` (worktree `/home/vth/ws/laris-fix`) không có commit nào ngoài `develop`.
- Bản sao codex của phiên này nằm trong thư mục tạm của phiên và có thể mất: clone lại `openai/codex` tại `aa5f492`.
- Việc làm giao diện Ink toàn màn hình (cuộn, chọn chuột, tự copy) **bị bỏ**, thay bằng TUI Rust.
