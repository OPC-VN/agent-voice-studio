# Trạm giọng — từng thư mục là gì

Repo `agent-voice-studio` chỉ chứa **mã**. Mọi thứ của riêng bạn — venv engine, giọng, nhạc nền,
output — nằm ở **trạm giọng**. Tài liệu này mô tả cây trạm, hai chế độ đặt trạm, và việc gì an
toàn với từng thư mục.

Repo này là một **năng lực thêm**, đứng một mình: cài khi bạn cần một giọng đọc. Quy trình sản
xuất nội dung nào gọi nó thì gọi qua hợp đồng mã thoát + dòng JSON cuối stdout, và chạy bình
thường khi máy chưa cài nó. Không có "bộ" nào phải cài đủ.

## Hai chế độ đặt trạm

| Chế độ | Trạm | Secret | Dành cho |
|---|---|---|---|
| **`embedded`** — gọn trong repo (**mặc định, khuyến nghị cho người mới**) | `<repo>/workspaces/` | `<repo>/.env` | một máy, "mở một folder là thấy hết" |
| **`separate`** — trạm ngoài repo | nơi bạn chỉ (`--station DIR`, hoặc trạm OpcOS) | kho secret riêng của máy (`~/.secret/…`) | nhiều máy, repo public của chính bạn, nhiều repo dùng chung trạm |

Tên thư mục thống nhất: gốc luôn là `workspaces`, trạm giọng khi cài cạnh OpcOS là thư mục con
`voice` của nó (`<OPCOS_WORKSPACES>/voice`). Cài riêng lẻ thì trạm là chính `<repo>/workspaces/` —
nằm trong repo nên không cần thêm `voice`. Tên số ít cũ `<repo>/workspace/` còn được **nhận** nếu nó
đã là một trạm mà `workspaces/` chưa có (kèm một dòng nhắc đổi tên); có cả hai thì `workspaces/` thắng
và có dòng nhắc. `init` mới không bao giờ tạo tên số ít, và không tự dời gì.

`voice-studio init` ghi lựa chọn vào `<repo>/studio.local.json`:

- Có `OPCOS_WORKSPACES` và có người trả lời: một câu xác nhận/đổi — Enter ra `<biến>/voice` (cả khi
  trạm đó đã có sẵn; gõ `1`/`2`/`embedded`/`separate` là mã 2, câu này nhận ĐƯỜNG; hết dữ liệu ở câu
  này — Windows `< NUL` — được coi là không có người).
  Ngoại lệ: trạm nhúng trong repo đã có dữ liệu mà chưa ghi lựa chọn thì hỏi một câu giữ/chuyển thay
  cho câu này (Enter = giữ, `chuyen` = dời vào `<biến>/voice`, vẫn hỏi y/N trước khi dời).
- Không có biến, có người trả lời: câu hỏi hai đường (Enter = `embedded`, `<repo>/workspaces/`);
  chọn `separate` thì hỏi tiếp đường dẫn — không có đường mặc định.
- `--yes` không bao giờ hỏi (có hay không có terminal). Máy có `OPCOS_WORKSPACES`: ra `<biến>/voice` (đã
  mang dấu thì dùng thẳng; chưa thì dựng ở đó và in một dòng nêu đường cùng cách đổi `--station`) —
  trừ khi `<repo>/workspaces/` (hay `workspace/` tên cũ) đã là một trạm có dữ liệu mà chưa ghi lựa chọn:
  khi đó **giữ trạm cũ** (ghi `embedded`, in cách dời sau bằng `migrate --to separate`), không dựng trạm
  rỗng cạnh dữ liệu. Máy không có biến: ra `<repo>/workspaces/`. Muốn trạm trong repo dù máy có biến:
  `--mode embedded --yes`.
- `--station DIR` — bạn chỉ thẳng trạm ⇒ `separate`.
- Máy **đã đặt trạm ngoài**: biến `VOICE_STATION` (hoặc tên cũ `OMNIVOICE_DIR`) ⇒ tự `separate`,
  **không bao giờ** tạo `workspaces/` (hai trạm cho một repo = hai nguồn sự thật).
- `--mode embedded` ⇒ trạm nhúng, không hỏi.
- `--mode separate` khi `OPCOS_WORKSPACES` đang đặt: đích là `<biến>/voice` (tuyệt đối, kể cả khi
  thư mục đó chưa là trạm). Đã mang dấu trạm thì dùng thẳng, không hỏi; chưa thì có người ngồi đó
  `init` hỏi xác nhận hoặc đổi; không có người thì dùng luôn và in một dòng nêu đường. Không đặt
  biến: có người thì hỏi đường, không thì dừng mã 2 (cần `--station DIR`).

Chạy không có người trả lời (`--non-interactive`, hoặc không có terminal) mà thiếu cả `--yes` lẫn
`--mode`: máy **không** đặt `OPCOS_WORKSPACES` ⇒ `init` in bảng lựa chọn rồi thoát mã 2 (không đoán
chế độ); máy **có** `OPCOS_WORKSPACES` ⇒ như `--yes` (trạm `<biến>/voice`, hoặc giữ trạm cũ có dữ
liệu). Hành vi theo từng cách gọi nằm trong bảng quyết định `tests/test_init_decision_table.py`.
**Agent cài phải trình bảng đó cho người dùng và chờ họ chọn** — không tự chọn im lặng. Tự
khai `--non-interactive` cũng vậy: nó nói "không có ai ngồi đây", KHÔNG nói "đoán hộ tôi", nên khi máy
chưa đặt `OPCOS_WORKSPACES`, thiếu `--yes`/`--mode`/`--station` thì vẫn là mã 2.

Agent cài nên **phân tích rồi khuyến nghị**, không hỏi trống: người không rành kỹ thuật, một
máy ⇒ `embedded`; người nhiều máy, rành hơn, hoặc repo này là bản public của chính họ ⇒
`separate`.

Xem trước, không ghi gì: `voice-studio init --dry-run`.

### Biến cấu hình ở chế độ `embedded` — `<repo>/.env`

`init` chép `.env.example` (khuôn tên biến, không có giá trị) thành `<repo>/.env` và khoá
quyền 600 trên POSIX. Chạy lại **không đè** file anh đã điền.

Thứ tự đọc một biến: **biến môi trường thật → `<repo>/.env` (chỉ khi `mode = embedded`) →
chưa đặt**. Biến thật luôn thắng file: máy đã đặt biến (máy chạy lịch) không được để một file
lạc vào repo cướp cấu hình. Chế độ `separate` **không bao giờ** nạp `.env` — ở đó repo có thể
là bản public của chính anh, và tự nạp một file nằm trong repo là mở cửa cho nó.

Một giới hạn phải biết: chỉ thứ đi qua `voice_studio._env.env()` mới đọc được từ `.env`. Biến
do **tiến trình khác** đọc — venv engine chạy riêng, thư viện Hugging Face đọc `HF_*` thẳng từ
môi trường — thì không; chúng được đánh dấu `[MÔI TRƯỜNG THẬT]` ngay trong `.env.example` và
phải đặt ở cấp user hoặc trong môi trường của scheduled task, kể cả khi đang `embedded`.

`.env` giữ **đường dẫn và cấu hình máy**, không bao giờ giữ token. Bí mật nằm trong file ngoài
git mà đường dẫn trong `.env` trỏ tới (ở `separate`: `~/.secret/voice-studio/`).

### Thứ tự tìm trạm (mọi lệnh dùng chung một hàm)

```
--station  →  VOICE_STATION  →  OMNIVOICE_DIR (tên cũ, trỏ thư mục engine)  →
<repo>/studio.local.json  →  <repo>/workspaces/ (có hay chưa; `init` tạo)  →  chưa xác định (mã 3)
```

**Không đặt gì thì trạm là thư mục trong repo** (`<repo>/workspaces/`, bị git bỏ qua) — không
bao giờ là một thư mục ẩn dưới thư mục cá nhân. Muốn dùng trạm ở nơi khác thì chỉ rõ: biến,
`--station`, hoặc câu trả lời khi `init` hỏi (ghi vào `studio.local.json`). Nếu máy có biến
`OPCOS_WORKSPACES`, `init` dùng `<biến>/voice` (`--yes` và chạy không người cũng đặt vào đó; Enter ở câu hỏi nhận đề xuất) và
`doctor` nhắc — resolver không đọc biến này.

`<repo>` là bản clone đã `pip install -e` (hoặc đặt `VOICE_STUDIO_REPO` — cách bản sao của máy
chạy lịch tìm về bản clone, xem [`INSTALL.md`](INSTALL.md) mục 3). Cài dạng wheel không đặt biến thì
không có repo — chỉ dùng được `separate`, và chưa đặt `VOICE_STATION` thì mọi lệnh cần trạm dừng
với mã 3 kèm cách đặt.

## Cây trạm

```
<trạm>/
├── station.json          QUẢN LÝ   cấu hình trạm (contract 1.2: profiles_dir, music_dir, bgm_dir, default_profile)
├── profiles/
│   ├── _default.txt      QUẢN LÝ   tên profile mặc định (station.json: default_profile thắng)
│   ├── _example/         MẪU       hướng dẫn tạo giọng ví dụ trung tính
│   └── <tên>/            MỖI GIỌNG MỘT THƯ MỤC
│       ├── voice/        CONTENT   clip tham chiếu — GIỮ NGUYÊN tên file:
│       │   ├── <tên>.wav · <tên>.txt          clip + lời của clip
│       │   ├── <tên>.profile.json · <tên>.variants/   profile đa sắc thái (nếu có)
│       │   └── <tên>.prompt.pt                QUẢN LÝ  cache clone prompt (dựng lại được)
│       ├── raw/          CONTENT   bản ghi gốc (nặng; profile gốc giữ, profile dẫn xuất chỉ trỏ trong README.md)
│       ├── lab/          NHÁP      chỗ làm việc của `voice-studio lab` (candidates.json, clips/)
│       ├── report/       CONTENT   hồ sơ kiểm của giọng
│       ├── products/     NHÁP      demo, bản đọc thử về giọng này (`lab organize`: ref.wav, demo/)
│       └── README.md     CONTENT   nguồn, mốc cắt, lịch sử
├── music/
│   ├── library/          CONTENT   thư viện nhạc nền: bgm-library.json + <style>.mp3   (= station.json: bgm_dir)
│   ├── channels/<kênh>/  CONTENT   nhạc nhận diện kênh: nền riêng, intro, outro (+ tracks.json: nguồn, giấy phép)
│   └── generated/        NHÁP      bản thô sinh bằng MusicGen
├── out/                  NHÁP      output tạm, xoá được
├── archive/<ngày>-<slug>/  CẤT     giọng nghỉ hưu, mã cũ — chỉ dời vào, không xoá thẳng
├── omnivoice/.venv/      QUẢN LÝ   venv engine — CHỈ khi máy không có OpcOS (trạm mới không dựng `omnivoice/` nữa)
└── cache/                NHÁP      cache công cụ
```

`archive/` nằm ở **gốc trạm**, không nằm trong `profiles/` (nếu không, loader sẽ coi `archive` là một giọng). Thư mục
dưới `profiles/` bắt đầu bằng `_` hoặc `.` cũng không phải giọng. Tên profile so theo Unicode NFC (macOS lưu tên
thư mục dạng NFD; tên có dấu nên đổi sang ASCII khi có thể).

**Trạm kiểu cũ** (kho phẳng `omnivoice/voices/<tên>.*`, `assets/bgm/`, `<work>/lab/<tên>/`) **vẫn chạy**: loader đọc
`profiles/<tên>/voice/` trước, lùi về kho phẳng; liệt kê giọng = hợp hai nơi, bỏ trùng (kiểu mới thắng). Profile mới
tạo (`make-profile`, `lab build`, `clone`) ghi vào kiểu mới khi trạm đã có `profiles/`, ngược lại vẫn kiểu cũ. Dời
trạm cũ sang cây mới bằng `voice-studio station migrate-layout` (mục *Vận hành*). Biến `VOICES_DIR` chỉ còn là
"kho phẳng kiểu cũ"; gỡ `OMNIVOICE_DIR`, `VOICE_STUDIO_WORK`, `VOICE_BGM_DIR` khi trạm đã sang cây mới (`doctor` nhắc).

Tuỳ chọn, bạn tự thêm khi cần: `voice-clean/` (công cụ làm sạch bản ghi + model, xem
`voice_studio/clean/README.md`). Không do `init` tạo; ngoài hợp đồng của plugin.

**Máy có OpcOS:** venv engine KHÔNG nằm trong trạm mà ở `$OPCOS_RUNTIME/venvs/agent-voice-studio/omnivoice`
(dọn giọng `…/sep`, `…/cv`; mô hình dọn giọng `$OPCOS_RUNTIME/engines/agent-voice-studio/clean`, gồm `models/` và
`checkpoints/`), tạo bằng `opcos-runtime ensure --repo-dir <repo>` theo `opcos-runtime.json`; `station.json: venv` của
trạm mới ghi đường tuyệt đối tới đó, trạm cũ giữ giá trị đang có. Đừng tạo venv trong `workspaces/` trên máy có
OpcOS — `opcos-runtime audit` sẽ báo đỏ. Máy không có OpcOS: venv trong trạm như bảng dưới.

## Từng thư mục

| Thư mục / file | Loại | Mục đích | Ai / cái gì ghi | `export --personal` | `backup` | Nhạy cảm | Xoá được? |
|---|---|---|---|---|---|---|---|
| `station.json` | quản lý | hợp đồng (`contract`), chế độ, `venv`, `engine_dir`, `profiles_dir`, `music_dir`, `bgm_dir`, `device`, `default_profile` | `init`, `migrate-layout`; bạn sửa tay được | có | có | không | xoá ⇒ `init --existing` dựng lại |
| `omnivoice/.venv/` (máy không có OpcOS) | quản lý | Python + torch + engine + package `voice_studio` | bạn, theo lệnh `init` in ra | **không** (cài lại ở máy mới) | **không** | không | được — tạo lại venv là xong |
| `profiles/<tên>/voice/*.wav, *.txt, *.profile.json, *.variants/` | **content** | giọng của bạn | `make-profile`, `clone`, `lab build`, `lab split` | có | có | **CÓ** — dữ liệu sinh trắc gần đúng | **không** — mất là phải dựng lại từ bản ghi |
| `profiles/_default.txt` | quản lý | profile mặc định | `make-profile --set-default`, bạn | có | có | không | được (mất mặc định: lệnh phải truyền `--profile`) |
| `profiles/<tên>/voice/*.prompt.pt` | quản lý | cache clone prompt, nhanh gấp ~50 lần lần gọi đầu | engine tự ghi | **không** | **không** | thấp | được — tự dựng lại |
| `profiles/<tên>/raw/` | **content** | bản ghi gốc dùng dựng giọng | bạn | **không** (nặng) | có | **CÓ** — giọng thật | **không** nên — dựng lại giọng cần nó |
| `profiles/<tên>/lab/` | nháp | `candidates.json` + `clips/` của `lab mine` (đường tương đối) | `lab mine`, `lab build` | chỉ khi `--with-lab` | có | **CÓ** | được, trừ khi đang giữa mẻ `lab mine → build` |
| `profiles/<tên>/report/`, `README.md` | content | hồ sơ kiểm, sổ tay của giọng | bạn, `lab organize` | không | có | thấp | không nên |
| `profiles/<tên>/products/` | nháp | demo, bản đọc thử về giọng đó | `lab organize`, bạn | không | có | **CÓ** | được |
| `profiles/_example/` | mẫu | hướng dẫn giọng ví dụ | `init` chép từ repo | không | có | không | được |
| `music/library/bgm-library.json` | content | style, style mặc định, âm lượng | `init` (khung), `gen_pack.py`, bạn | có | có | không | không nên |
| `music/library/<style>.mp3` | content | nhạc nền | bạn / MusicGen (`docs/bgm-generation.md`) | có | có | giấy phép nhạc | được nếu còn nguồn |
| `music/channels/<kênh>/` | content | nhạc riêng của kênh (nền, intro, outro) + `tracks.json` | bạn | chỉ khi thêm `--with-music-channels` (mặc định không: nặng, ~100 MB ở trạm thật) | có | giấy phép nhạc | không nên |
| `music/generated/` | nháp | bản thô MusicGen (CC-BY-NC: kênh kiếm tiền không dùng) | `extras/musicgen` | không | có | giấy phép | được — sinh lại được |
| `out/` (= `VOICE_STUDIO_WORK`) | nháp | output mặc định | mọi lệnh | **không** | **không** | **CÓ** — audio giọng thật | được |
| `archive/<ngày>-<slug>/` | cất | giọng nghỉ hưu, mã cũ, kho `_archive` cũ | `migrate-layout`, bạn | không | có | **CÓ** | **không** nên — chỉ dời vào |
| `cache/` | nháp | cache công cụ | công cụ | không | không | thấp | được |

Weights của engine (~3,3 GB) **không** nằm trong trạm mà trong cache Hugging Face (`HF_HOME`,
mặc định `~/.cache/huggingface`). Chuyển máy thì tải lại: lần tổng hợp đầu ở máy mới chạy với `OMNIVOICE_ONLINE=1` (doctor
không tải gì).

## Vận hành

| Việc | Lệnh | Ghi chú |
|---|---|---|
| Kiểm trạm | `voice-studio doctor` | ĐỎ khi vừa có `workspaces/` vừa có trạm ngoài; embedded: kiểm `workspaces/`, `.env` không bị git theo dõi, repo không nằm trong OneDrive/Drive/iCloud/Dropbox, `.env` quyền 600 |
| Cập nhật repo | `voice-studio update` | = `git pull --ff-only`. **Không bao giờ** xoá hay `git clean`. **Đừng xoá folder repo để cài lại** — ở chế độ embedded đó là xoá luôn giọng của bạn |
| Sao lưu | `voice-studio backup --out trạm.zip` | cả trạm (gồm `profiles/*/raw/`) trừ venv, `cache/`, `out/`, `*.prompt.pt`; `.env` chỉ kèm khi thêm `--with-env` |
| Chuyển máy | `voice-studio export --personal --out giong.zip` → máy mới: `voice-studio import giong.zip` | gói `profiles/*/voice/`, `profiles/_default.txt`, `music/library/`, `station.json` (trạm cũ: `omnivoice/voices/`, `assets/bgm/`); **không** gói `raw/`, `lab/`, `products/` — thêm `--with-lab` để kèm `lab/`, `--with-music-channels` để kèm `music/channels/` (nhạc nền + intro/outro kênh; không kèm thì chép tay sang máy mới); `station.json` trong gói **không mang `venv`** (đường tuyệt đối của máy nguồn): `import` để trống, hoặc giữ `venv` máy đích đã có — dựng venv bằng `opcos-runtime ensure`/`init` ở máy mới; từ chối file trông như secret (`*token*`, `*secret*`, `.env`…); `import` không đè file trùng trừ khi `--force` |
| Xem giọng của trạm | `voice-studio profiles list [--json]` | tên, kiểu (`new` = `profiles/<tên>/voice/`, `legacy` = kho phẳng cũ), số marker, mặc định, thư mục giọng. Pipeline khác (marketing, video) gọi lệnh này thay vì đọc thẳng thư mục kho |
| Dời trạm cũ sang cây mới | `voice-studio station migrate-layout [--dry-run\|--apply\|--undo] [--station P] [--map file.json]` | mặc định `--dry-run`. Chỉ **dời, không xoá**; có sổ `<trạm>/.layout-ledger/layout-<giờ>.json` (đường tương đối + sha256), `--undo` đảo lần dời gần nhất theo thứ tự ngược; bước hỏng giữa chừng tự hoàn tác. Dời: kho giọng → `profiles/<tên>/voice/`, sổ tay organize → `README.md` + `products/`, `_default.txt`, `_archive` → `archive/<ngày>-voices/`, `assets/bgm` → `music/library`, `<work>/lab/<tên>` → `profiles/<tên>/lab`, `station.json` lên 1.2. Trạm là git: tự thêm vào `.gitignore` các dòng chặn `/profiles/*/raw/`, `/profiles/*/lab/`, `/profiles/*/products/`, `/music/generated/`, `/out/`, `/archive/` (và `!/profiles/*/voice/**/*.wav` để clip tham chiếu vẫn vào git) TRƯỚC khi dời, kiểm bằng `git check-ignore`, không chặn được thì dừng. Thứ ngoài hợp đồng (raw/<nguồn>, out/<profile>, musicgen, truyện…) chỉ được liệt kê là "cần dời tay" kèm gợi ý đích; dời chúng bằng `--map` (`{"moves":[{"from","to"}],"rename":{"cũ":"mới"}}`, đường tương đối theo trạm; `rename` không áp cho profile có manifest) — cũng vào sổ, cũng `--undo` được |
| Tách trạm ra ngoài | `voice-studio migrate --to separate [--station DIR]` | dời `workspaces/` → DIR, `.env` → `~/.secret/voice-studio/.env`, ghi lại `studio.local.json`; đích phải rỗng. Thiếu `--station` thì HỎI nơi dời (gợi ý `<OPCOS_WORKSPACES>/voice` nếu có), hiện đường tuyệt đối + số file và dung lượng (KB/MB) và xin xác nhận y/N; từ chối đích nằm trong chính `workspaces/`; đường dán có ngoặc kép (Copy as path) được bóc; không có người trả lời thì dừng mã 2 (`--non-interactive` cũng vậy) — không có đích mặc định |

## Rào của chế độ embedded (init tự dựng)

- `.gitignore` của repo khoá `/workspaces/`, `.env`, `.env.*` (trừ `.env.example`), `studio.local.json`
  — test `tests/test_repo_gates.py` đỏ nếu ai xoá một dòng.
- `<repo>/.env` được dọn sẵn từ `.env.example`, quyền 600 trên POSIX. Cùng bộ test còn kiểm
  rằng **mọi biến mã đọc đều có trong khuôn** — thiếu một dòng là người dùng không biết mình
  phải điền gì, và chỉ phát hiện ra lúc lệnh nổ giữa chừng.
- Hook `pre-commit` (cài vào `.git/hooks/` nếu chưa có hook): chặn commit file dưới `workspaces/`,
  `.env`, `studio.local.json`, và dòng thêm mới trông giống token. Hook đã có sẵn thì giữ nguyên.
- `doctor` kiểm lại các rào trên mỗi lần chạy.
