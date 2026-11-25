---
title: PLAN — macmini-media-sync (voice side — voice station on the Mac mini)
date: 2026-11-25
revision: 3
status: draft_waiting_owner_decisions
master: agent-marketing-team/docs/plans/macmini-media-sync/PLAN.md
executor: Codex on the Mac mini
evaluator: Claude
---

# PLAN — macmini-media-sync · phần voice: trạm giọng trên Mac mini

> Kế hoạch chủ: `agent-marketing-team/docs/plans/macmini-media-sync/PLAN.md`. File này nói cách đưa voice 0.7.0 (API 1.2.0) xuống Mac mini, dựng trạm giọng mới từ **bản chép** dữ liệu giọng của Mac, và những gì repo voice cần bổ sung cho macOS.
> Tên giọng thật, bảng đổi tên giọng giữa hai máy là dữ liệu riêng: nằm ở hồ sơ riêng của chủ máy và trong trạm, **không** ghi vào repo.

## 0. Mục tiêu

1. Cài voice `main` (0.7.0) song song ở `~/Studio-next/agent-voice-studio`, chung venv `~/Studio-next/.venv` với repo video.
2. Trạm giọng mới `~/Studio-next/workspaces/voice` theo cây mới (`profiles/<tên>/{voice,raw,lab,report,products}`, `music/{library,channels,generated}`, `station.json` contract 1.2), dựng từ: (a) gói export từ Windows nếu chủ máy chuyển sang, (b) **bản chép** trạm giọng cũ của Mac. Trạm cũ không bị chạm.
3. Xác nhận TTS chạy được trên MPS (bản 0.7.0 trên Mac **chưa kiểm**) và đo tốc độ.

## 1. Hiện trạng repo (đã đọc)

- Lệnh: `voice-studio profiles list [--json]`, `voice-studio station migrate-layout` (mặc định `--dry-run`; `--apply`, `--undo`, `--map`; chỉ dời, sổ sha256 ở `.layout-ledger/`, rào `.gitignore`, idempotent, chuẩn hoá NFC cho tên NFD của macOS), `export --personal [--with-music-channels]`, `import` (không ghi đè trừ `--force`), `backup --out`, `doctor` (`docs/WORKSPACE.md`, `voice_studio/layout.py`).
- Loader đọc cây mới trước, lùi về kho phẳng cũ (`voice_studio/profiles.py`). Biến cũ `OMNIVOICE_DIR`, `VOICE_STUDIO_WORK`, `VOICE_BGM_DIR`, `VOICES_DIR` còn đọc nhưng doctor cảnh báo khi lệch cây mới.
- macOS: `brew install git python@3.12 ffmpeg-full`; torch cài riêng; MPS fp16 mặc định, `OMNIVOICE_DTYPE=float32` để đổi; engine tự đặt `PYTORCH_ENABLE_MPS_FALLBACK=1`, `HF_DEACTIVATE_ASYNC_LOAD=1`; launchd không đọc shell profile nên env phải nằm trong plist (`docs/INSTALL.md`, `skills/voice-routing/references/install-omnivoice.md`, `docs/troubleshooting.md`).
- Lock chỉ có bản Windows; `opcos-runtime.json` chưa có khoá `darwin`.

## 2. Dựng trạm giọng mới trên Mac (Codex, pha P2)

1. `voice-studio init --mode separate` trỏ vào `~/Studio-next/workspaces/voice` (thư mục mới, rỗng; cách chỉ đường theo `docs/WORKSPACE.md`). Init in bảng chọn chế độ thì trình chủ máy, không tự chọn (AGENTS.md §1). Tải torch/weights (~3,3 GB, giấy phép CC-BY-NC) chỉ khi chủ máy đồng ý; nếu máy cũ đã có weights trong cache Hugging Face thì dùng lại.
2. Nếu có gói Windows (chủ máy chuyển qua ổ ngoài/scp, kèm sha256): kiểm băm → `voice-studio import <gói> --station ~/Studio-next/workspaces/voice` (không `--force`).
3. Chép trạm giọng cũ của Mac sang `~/Studio-next/_staging/voice-old-copy/` bằng `rsync -a` (không `--delete`). **Chỉ trên bản chép:** `voice-studio station migrate-layout --station <bản chép> --dry-run` → đọc bảng → `--apply`.
4. Gộp giọng từ bản chép vào trạm mới:
   - So `sha256` của `.wav` từng tên với trạm mới.
   - Tên chỉ có ở Mac → chép `profiles/<tên>/` sang trạm mới.
   - Trùng tên, cùng băm → bỏ qua.
   - Trùng tên, **khác băm** → chép bản Mac thành `profiles/<tên>-mac/`, ghi vào bảng xung đột trong bằng chứng; không ghi đè, không `--force`.
   - `raw/` chỉ chép khi chủ máy cho (nặng, nhạy cảm).
   - Mục migrate-layout liệt kê "cần dời tay" → ghi báo cáo, không tự dời.
5. Nhạc: `music/library` và `music/channels` từ gói hoặc bản chép (mp3 không đi qua git).
6. `station.json`: `venv` trỏ `~/Studio-next/.venv`; `default_profile` theo quyết định chủ máy ở Cổng A.
7. Kiểm (dưới `env -i`, không có biến cũ): `voice-studio doctor` exit 0; `voice-studio profiles list --json` khớp **danh sách tên kỳ vọng** chủ máy chốt ở Cổng A; mỗi giọng đang dùng trong `campaign.md`/`channel.yml` đọc thử một câu (`voice-studio speak --file <câu mẫu> --profile <tên> --json`), ghi thời gian và RTF.

## 3. Việc trong repo voice

Repo voice có 4 **việc** (TK) trong kế hoạch này:

| Mã | Việc | Kiểm |
|---|---|---|
| TK-W1 — Khoá `darwin` cho runtime | thêm mục macOS arm64 vào `opcos-runtime.json` (venv, ràng buộc torch MPS) | test đọc runtime 2 OS |
| TK-W2 — Ghi chú macOS đã đo | cập nhật `docs/troubleshooting.md`/`docs/INSTALL.md` với số đo thật MPS (RTF, thời gian một đoạn) sau pha P2; bỏ dòng "chưa kiểm" khi đã đo | cổng chống rò `tests/test_no_identity_leak.py` xanh |
| TK-W3 — Lệnh so giọng hai trạm (tuỳ chọn) | `voice-studio profiles diff --a <trạm> --b <trạm> --json`: tên, băm `.wav`, số marker — thay cho so tay ở bước 2.4. Lệnh mới → sửa README, README.vi, `docs/index.html` | test với hai trạm giả; `tests/test_docs_drift.py` |
| TK-W4 — CHANGELOG | ghi mục cho các thay đổi trên | `tests/test_version_sync.py` nếu đổi phiên bản |

TK-W3 là "nên có": nếu Cổng B thấy không cần thì bỏ, so tay bằng `shasum`.

## 4. Gọi giọng từ hai repo kia (không đổi hợp đồng)

- Marketing chọn giọng theo thứ tự `-Profile` → `campaign.md: runtime.voice_profile` → `channel.yml: voice_profile` → mặc định trạm; liệt kê giọng bằng `voice-studio profiles list --json`.
- Video gọi `voice-studio speak … --json` và đọc marker sắc thái qua `voice_studio.lab.vlab`.
- Plist launchd của cây mới chỉ mang `OMNIVOICE_DTYPE` (tin: `float32`, truyện: `float16`) và với truyện thêm `HF_DEACTIVATE_ASYNC_LOAD=1`; **không** còn `OMNIVOICE_DIR`, `VOICE_STUDIO_WORK`, `VOICE_BGM_DIR` (bảng biến: `agent-marketing-team/docs/RUNBOOK-DOI-MAY.md`).
