"""layout.py — dời trạm giọng KIỂU CŨ sang cây `profiles/` (`voice-studio station migrate-layout`).

Cây đích (station.json 1.2):

    <trạm>/profiles/<tên>/{voice,raw,lab,report,products}/ + README.md · profiles/_default.txt
           music/{library,channels,generated}/ · out/ (nháp) · archive/<ngày>-<slug>/ · station.json

Lệnh CHỈ DỜI, không xoá gì, và chỉ đụng thứ thuộc hợp đồng của plugin:

    kho giọng phẳng  <engine>/voices/<tên>.*            → profiles/<tên>/voice/
    sổ tay organize  <engine>/voices/<tên>/README.md    → profiles/<tên>/README.md  (phần còn lại → products/)
    mặc định         <engine>/voices/_default.txt       → profiles/_default.txt
    kho nghỉ hưu     <engine>/voices/_archive (+_layout.json) → archive/<ngày>-voices/
    nhạc nền         assets/bgm                         → music/library
    chỗ đào clip     <work>/lab/<tên>                   → profiles/<tên>/lab
    cấu hình         station.json lên 1.2 (profiles_dir, music_dir, bgm_dir=music/library)

Thứ NGOÀI hợp đồng (truyen-out, apps, raw/<người>, out/<profile>, musicgen…) KHÔNG tự dời: `--dry-run` liệt kê chúng
là "cần dời tay" kèm gợi ý đích; muốn dời thì đưa bảng `--map file.json` (`{"moves":[{"from","to"}], "rename":{"cũ":"mới"}}`,
đường tương đối theo trạm) — các bước đó cũng vào SỔ và cũng `--undo` được.

SỔ: `<trạm>/.layout-ledger/layout-<giờ>.json` ghi từng bước ĐÃ làm (đường tương đối, sha256 từng file); `--undo` đọc sổ
mới nhất còn hiệu lực và đảo ngược từng bước theo thứ tự ngược. Một bước hỏng giữa chừng ⇒ tự hoàn tác các bước đã làm.

Trạm là git ⇒ `.gitignore` PHẢI chặn raw/lab/products/music-generated/out/archive TRƯỚC khi dời (bản ghi thô nặng hàng GB);
lệnh tự thêm các dòng thiếu, kiểm lại bằng `git check-ignore`, không chặn được thì dừng trước khi dời byte nào.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import subprocess

from . import API_VERSION, __version__, _env, contract
from .contract import ContractError

LEDGER_DIR = ".layout-ledger"
GITIGNORE = ".gitignore"

GITIGNORE_HEADER = "# ── voice-studio: cây trạm profiles/ (thêm bởi `voice-studio station migrate-layout`)"
GITIGNORE_LINES = ("/profiles/*/raw/", "/profiles/*/lab/", "/profiles/*/products/",
                   "/music/generated/", "/out/", "/archive/")
GITIGNORE_KEEP_COMMENT = "# clip tham chiếu của giọng là tài sản chính — vào git"
GITIGNORE_KEEP = "!/profiles/*/voice/**/*.wav"
# đường mẫu để hỏi git "chỗ này bị bỏ qua chưa" (tên `_probe` không phải profile thật)
PROBES = {"profiles/*/raw/": "profiles/_probe/raw/x.wav", "profiles/*/lab/": "profiles/_probe/lab/x.wav",
          "profiles/*/products/": "profiles/_probe/products/x.wav", "music/generated/": "music/generated/x.wav",
          "out/": "out/x.wav", "archive/": "archive/x.wav"}

# thứ ở gốc trạm mà lệnh hiểu: không báo "cần dời tay"
KNOWN_TOP = {"profiles", "music", "out", "archive", "cache", "station.json", "README.md", "INDEX.md",
             "ARCHIVE-LOG.md", GITIGNORE, ".git", LEDGER_DIR}


def _now():
    return datetime.datetime.now()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _b64(data):
    return None if data is None else base64.b64encode(data).decode("ascii")


def _unb64(text):
    return None if text is None else base64.b64decode(text.encode("ascii"))


def _read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


# ── .gitignore ───────────────────────────────────────────────────────────────────────

def station_is_git(st):
    return os.path.exists(os.path.join(st, ".git"))


def _git_ignored(st, rel):
    """True/False theo `git check-ignore`; None nếu không hỏi được (không có git, lỗi)."""
    try:
        r = subprocess.run(["git", "-C", st, "check-ignore", "-q", "--no-index", "--", rel],
                           capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(r.returncode)


def gitignore_unprotected(st):
    """Danh sách thư mục dữ liệu nặng mà `.gitignore` của trạm CHƯA chặn (rỗng = ổn). None nếu trạm không phải
    git hoặc không có git để hỏi."""
    if not station_is_git(st):
        return None
    out = []
    for label, probe in PROBES.items():
        res = _git_ignored(st, probe)
        if res is None:
            return None
        if not res:
            out.append(label)
    return out


def _gitignore_edit(st):
    """-> (before bytes|None, after bytes, các dòng sẽ thêm). `after == before` khi không thiếu gì."""
    before = _read_bytes(os.path.join(st, GITIGNORE))
    text = before.decode("utf-8", errors="replace") if before is not None else ""
    have = {ln.strip() for ln in text.splitlines()}
    add = [ln for ln in GITIGNORE_LINES if ln not in have]
    if GITIGNORE_KEEP not in have:
        add.append(GITIGNORE_KEEP)
    if not add:
        return before, before, []
    nl = "\r\n" if "\r\n" in text else "\n"
    block = [GITIGNORE_HEADER] + [ln for ln in add if ln != GITIGNORE_KEEP]
    if GITIGNORE_KEEP in add:
        block += [GITIGNORE_KEEP_COMMENT, GITIGNORE_KEEP]
    prefix = "" if (not text or text.endswith(("\n", "\r"))) else nl
    gap = nl if text else ""
    after = text + prefix + gap + nl.join(block) + nl
    return before, after.encode("utf-8"), add


# ── kế hoạch ─────────────────────────────────────────────────────────────────────────

def _rel(st, path):
    return os.path.relpath(path, st).replace(os.sep, "/")


def _abs(st, rel):
    return os.path.join(st, *rel.split("/"))


def _check_rel(rel, what):
    parts = rel.replace("\\", "/").split("/")
    if (not rel or os.path.isabs(rel) or rel.startswith(("/", "\\")) or any(p in ("", "..") or ":" in p for p in parts)
            or parts[0] == ".git"):
        raise ContractError(f"{what}: đường không hợp lệ {rel!r} (phải tương đối theo trạm, không `..`, không `:`, "
                            "không vào .git)")
    return "/".join(parts)


def _load_map(path):
    if not path:
        return [], {}
    data, err = _env.read_json(path)
    if err or not data:
        raise ContractError(f"--map không đọc được hoặc rỗng: {err or path}")
    moves, rename = [], {}
    for m in data.get("moves") or []:
        if not isinstance(m, dict) or not m.get("from") or not m.get("to"):
            raise ContractError(f"--map: mỗi mục `moves` cần `from` và `to`: {m!r}")
        moves.append({"from": _check_rel(str(m["from"]), "--map from"), "to": _check_rel(str(m["to"]), "--map to"),
                      "note": str(m.get("note") or "")})
    for old, new in (data.get("rename") or {}).items():
        if not _env.is_profile_folder(str(new)) or any(c in str(new) for c in "/\\:"):
            raise ContractError(f"--map rename: tên mới không hợp lệ {new!r}")
        # NFC cả hai vế: trên macOS tên file hay ở dạng NFD, khoá NFC trong map sẽ không khớp nếu so thô.
        rename[_env.nfc(str(old))] = _env.nfc(str(new))
    return moves, rename


def _station_engine(st):
    info = _env.read_json(os.path.join(st, _env.STATION_FILE))[0]
    rel = str(info.get("engine_dir") or "omnivoice")
    return rel if os.path.isabs(rel) else os.path.join(st, *rel.replace("\\", "/").split("/"))


def _hint_omnivoice(name):
    n = name.lower()
    if n == "apps":
        return "archive/<ngày>-omnivoice-code/ (bộ dựng tin đã vào video_studio/templates/news)"
    if n in ("truyen-out", "news-out"):
        return "marketing/<kênh>/<chiến dịch>/out|work|logs/ (hoặc archive/<ngày>-<slug>/) — bạn chốt giữ hay xoá"
    if n == "assets":
        return ("nhạc kênh (*.mp3) → music/channels/<kênh>/; hình (nền, logo, hiệu ứng, ảnh thiết kế tin) → "
                "video/assets/channels/<kênh>/ hoặc assets/shared/")
    if n == "_vtitles":
        return "không dời — thư mục nháp của ffmpeg, mã dựng lại trong video/scratch/"
    return "archive/<ngày>-omnivoice-code/ (mã/công cụ của package cũ)"


def _manual_for_station(st, lab_bases, profile_names):
    """Thứ ngoài hợp đồng: [{path, hint}] — không bao giờ tự dời."""
    out = []
    eng = _station_engine(st)
    if os.path.isdir(eng):
        for n in sorted(os.listdir(eng)):
            if n in ("voices", ".venv", "__pycache__") or n.startswith(".venv"):
                continue
            out.append({"path": _rel(st, os.path.join(eng, n)), "hint": _hint_omnivoice(n)})
    for n in sorted(os.listdir(st)):
        if n in KNOWN_TOP or n == os.path.basename(eng) and os.path.dirname(eng) == st:
            continue
        p = os.path.join(st, n)
        if n == "assets":
            for a in sorted(os.listdir(p)):
                if a != "bgm":
                    out.append({"path": f"assets/{a}", "hint": "music/channels/<kênh>/ (nhạc) hoặc video/assets/ (hình)"})
        elif n == "raw" and os.path.isdir(p):
            for a in sorted(os.listdir(p)):
                hint = ("archive/<ngày>-raw-clean/ (dựng lại được từ bản ghi gốc)" if a == "_clean"
                        else f"profiles/<tên giọng gốc>/raw/{a} (bản ghi đặt ở profile gốc, profile khác chỉ trỏ)")
                out.append({"path": f"raw/{a}", "hint": hint})
        elif n == "musicgen":
            out.append({"path": "musicgen/out", "hint": "music/generated/ (bản thô MusicGen, CC-BY-NC)"})
            out.append({"path": "musicgen/*.py", "hint": "archive/<ngày>-<slug>/ (trùng extras/musicgen của repo)"})
        elif n == "voice-clean":
            out.append({"path": "voice-clean", "hint": "archive/<ngày>-omnivoice-code/"})
        elif n == "_archive":
            out.append({"path": "_archive", "hint": "archive/<ngày>-<slug>/"})
        elif n == "data":
            left = [d for d in sorted(os.listdir(p))]
            out.append({"path": "data", "hint": "sau khi dời lab/: phần còn lại ("
                        + ", ".join(left[:5]) + ") → archive/<ngày>-<slug>/ hoặc xoá tay"})
        elif n == _env.STATION_FILE + ".bak" or n.startswith("station.json.bak"):
            out.append({"path": n, "hint": "archive/<ngày>-<slug>/"})
        else:
            out.append({"path": n, "hint": "chưa có gợi ý — quyết định đích rồi đưa vào --map"})
    op = os.path.join(st, "out")
    if os.path.isdir(op):
        for a in sorted(os.listdir(op)):
            full = os.path.join(op, a)
            if not os.path.isdir(full) or a == "lab":
                continue
            if _env.nfc(a) in profile_names:
                out.append({"path": f"out/{a}", "hint": f"profiles/{a}/report/ (hồ sơ kiểm của giọng)"})
            elif "-archive" in a:
                out.append({"path": f"out/{a}", "hint": f"archive/profiles/{a}/ (giọng nghỉ hưu)"})
    return out


class Planner:
    """Gom các bước dời, kiểm xung đột TRƯỚC khi đụng byte nào."""

    def __init__(self, st):
        self.st = st
        self.steps = []              # mkdir | move
        self.conflicts = []
        self.notes = []
        self.manual = []
        self.will_exist = set()      # đường (rel) sẽ có sau các bước đã xếp
        self.will_leave = set()      # nguồn đã xếp dời
        self.dsts = set()

    def exists(self, rel):
        return rel in self.will_exist or os.path.lexists(_abs(self.st, rel))

    def mkdir(self, rel):
        if self.exists(rel) and (rel in self.will_exist or os.path.isdir(_abs(self.st, rel))):
            return
        parent = rel.rpartition("/")[0]
        if parent:
            self.mkdir(parent)
        self.steps.append({"op": "mkdir", "path": rel})
        self.will_exist.add(rel)

    def move(self, src, dst, why=""):
        s_abs = _abs(self.st, src)
        if not os.path.lexists(s_abs):
            self.conflicts.append(f"nguồn không còn: {src}")
            return False
        if src in self.will_leave:
            self.conflicts.append(f"nguồn bị dời hai lần: {src}")
            return False
        if any(src.startswith(x + "/") for x in self.will_leave):
            self.conflicts.append(f"nguồn nằm trong thư mục đã xếp dời: {src}")
            return False
        dst_abs = _abs(self.st, dst)
        replace_empty = False
        if dst in self.dsts or dst in self.will_exist:
            self.conflicts.append(f"đích đã có: {dst} (nguồn {src})")
            return False
        if os.path.lexists(dst_abs) and dst not in self.will_leave:
            if os.path.isdir(dst_abs) and not os.listdir(dst_abs) and os.path.isdir(s_abs):
                replace_empty = True
            else:
                self.conflicts.append(f"đích đã có: {dst} (nguồn {src})")
                return False
        if dst == src or dst.startswith(src + "/"):
            self.conflicts.append(f"đích nằm trong nguồn: {src} → {dst}")
            return False
        self.mkdir(dst.rpartition("/")[0]) if "/" in dst else None
        step = {"op": "move", "src": src, "dst": dst, "kind": "dir" if os.path.isdir(s_abs) else "file", "why": why}
        if replace_empty:
            step["replace_empty_dir"] = True
        self.steps.append(step)
        self.will_leave.add(src)
        self.will_exist.add(dst)
        self.dsts.add(dst)
        return True


def _archive_name(st, planner, today, slug):
    base = f"archive/{today}-{slug}"
    n, cand = 1, base
    while planner.exists(cand):
        n += 1
        cand = f"{base}-{n}"
    return cand


def build_plan(st, map_path=None, today=None):
    """Kế hoạch dời đầy đủ (chưa ghi gì). -> dict: steps, manual, conflicts, notes, gitignore, station_json, summary."""
    st = os.path.abspath(st)
    today = today or datetime.date.today().isoformat()
    map_moves, rename = _load_map(map_path)
    p = Planner(st)
    names = set()                                       # profile sẽ có trong profiles/

    def prof(name):
        return rename.get(_env.nfc(name), name)          # so tên theo NFC (macOS: NFD)

    # A. kho giọng phẳng
    lv = os.path.join(_station_engine(st), "voices")
    if os.path.isdir(lv):
        top = sorted(os.listdir(lv))
        handled = {"_default.txt", "_archive", "_layout.json"}
        stems = [n[:-4] for n in top if n.endswith(".wav") and not n.startswith("_")
                 and os.path.isfile(os.path.join(lv, n))]
        for stem in stems:
            new = prof(stem)
            if not _env.is_profile_folder(new):
                p.manual.append({"path": _rel(st, os.path.join(lv, stem + ".wav")),
                                 "hint": "tên không thành thư mục profile hợp lệ — đổi tên rồi dời tay"})
                continue
            if new != stem and (os.path.exists(os.path.join(lv, stem + ".profile.json"))
                                or os.path.isdir(os.path.join(lv, stem + ".variants"))):
                raise ContractError(f"rename '{stem}' → '{new}': profile có manifest/biến thể (đường trong "
                                    ".profile.json gắn tên cũ) — không đổi tên tự động, dời nguyên tên rồi sửa tay")
            names.add(new)
            handled.update({stem, stem + ".wav", stem + ".txt", stem + ".prompt.pt", stem + ".profile.json",
                            stem + ".variants"})
            base = f"profiles/{new}/voice"
            for ext in (".wav", ".txt", ".prompt.pt", ".profile.json"):
                f = os.path.join(lv, stem + ext)
                if os.path.isfile(f):
                    p.move(_rel(st, f), f"{base}/{new}{ext}", "kho giọng")
            vd = os.path.join(lv, stem + ".variants")
            if os.path.isdir(vd):
                p.move(_rel(st, vd), f"{base}/{new}.variants", "biến thể sắc thái")
            nd = os.path.join(lv, stem)
            if os.path.isdir(nd):                       # sổ tay + demo do `lab organize` kiểu cũ
                for child in sorted(os.listdir(nd)):
                    dst = (f"profiles/{new}/README.md" if child == "README.md"
                           else f"profiles/{new}/products/{child}")
                    p.move(_rel(st, os.path.join(nd, child)), dst, "sổ tay/demo của organize")
        d_file = os.path.join(lv, "_default.txt")
        if os.path.isfile(d_file):
            p.move(_rel(st, d_file), "profiles/_default.txt", "profile mặc định")
            cur = _read_bytes(d_file).decode("utf-8", errors="replace").strip()
            if _env.nfc(cur) in rename:
                p.notes.append(f"profile mặc định '{cur}' bị đổi tên thành '{rename[_env.nfc(cur)]}': sửa nội dung "
                               "profiles/_default.txt (hoặc station.json: default_profile) sau khi dời")
        arch = os.path.join(lv, "_archive")
        a_dst = _archive_name(st, p, today, "voices")
        if os.path.isdir(arch):
            p.move(_rel(st, arch), a_dst, "kho giọng nghỉ hưu")
        lay = os.path.join(lv, "_layout.json")
        if os.path.isfile(lay):
            p.move(_rel(st, lay), f"{a_dst}/_layout.json", "sổ bố cục cũ")
        for n in top:
            if n not in handled:
                p.manual.append({"path": _rel(st, os.path.join(lv, n)),
                                 "hint": "_example: bỏ (bản mẫu ở repo)" if n == "_example"
                                 else "ngoài hợp đồng kho giọng — quyết định đích rồi đưa vào --map"})

    # B. nhạc nền
    bgm = os.path.join(st, "assets", "bgm")
    moved_bgm = False
    if os.path.isdir(bgm):
        moved_bgm = p.move("assets/bgm", "music/library", "thư viện nhạc nền")
    for sub in ("music/channels", "music/generated"):
        if not p.exists(sub):
            p.mkdir(sub)

    # C. chỗ đào clip
    bases = []
    w = _env.env("VOICE_STUDIO_WORK")
    for cand in ([os.path.join(_env._expand(w), "lab")] if w else []) + [os.path.join(st, "out", "lab"),
                                                                       os.path.join(st, "data", "voicelab", "lab")]:
        if os.path.isdir(cand) and os.path.normcase(os.path.realpath(cand)) not in {
                os.path.normcase(os.path.realpath(b)) for b in bases}:
            bases.append(cand)
    for b in bases:
        for entry in sorted(os.listdir(b)):
            full = os.path.join(b, entry)
            new = prof(entry)
            if not os.path.isdir(full) or not _env.is_profile_folder(new):
                p.manual.append({"path": _rel(st, full) if _is_under(full, st) else full,
                                 "hint": "không phải thư mục lab của một profile — dời tay"})
                continue
            if _is_under(full, st):
                names.add(new)
                p.move(_rel(st, full), f"profiles/{new}/lab", "chỗ đào clip")
            else:
                p.manual.append({"path": full, "hint": f"nằm ngoài trạm (VOICE_STUDIO_WORK) — dời tay vào profiles/{new}/lab"})

    # D. bảng --map của người dùng
    for m in map_moves:
        p.move(m["from"], m["to"], m["note"] or "theo --map")

    # E. thư mục profile cần có (mkdir đã tự xếp theo đích); thêm profiles/ nếu chưa có
    if names and not p.exists("profiles"):
        p.mkdir("profiles")

    manual = p.manual + _manual_for_station(st, bases, {_env.nfc(n) for n in names})
    # bỏ khỏi "cần dời tay" thứ đã xếp dời
    manual = [m for m in manual if m["path"] not in p.will_leave and not any(
        m["path"].startswith(s + "/") for s in p.will_leave)]

    # F. station.json
    sj = os.path.join(st, _env.STATION_FILE)
    before = _read_bytes(sj)
    cur, err = _env.read_json(sj)
    if err:
        raise ContractError(f"station.json hỏng, sửa tay trước: {err}")
    new_info = dict(cur)
    new_info["contract"] = API_VERSION
    new_info["profiles_dir"] = "profiles"
    new_info["music_dir"] = "music"
    if moved_bgm or (os.path.isdir(os.path.join(st, "music", "library")) and not os.path.isdir(bgm)):
        new_info["bgm_dir"] = "music/library"
    # Ghi `engine_dir` mặc định CHỈ khi thư mục engine còn trên đĩa. Trạm đã dời xong (omnivoice/ đã giải thể)
    # chạy lại phải KHÔNG đổi gì: không ghi trỏ vào thư mục chết, không sinh sổ rỗng (review Opus 6).
    if "engine_dir" not in new_info and os.path.isdir(os.path.join(st, "omnivoice")):
        new_info["engine_dir"] = "omnivoice"
    if _env.nfc(str(cur.get("default_profile") or "")) in rename:
        new_info["default_profile"] = rename[_env.nfc(str(cur["default_profile"]))]
    new_info.setdefault("created_by", f"voice-studio {__version__}")
    after = (json.dumps(new_info, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    sj_changed = before is None or json.loads(before.decode("utf-8") or "{}") != new_info

    # G. .gitignore
    git = station_is_git(st)
    g_before, g_after, g_add = (_gitignore_edit(st) if git else (None, None, []))
    unprotected = gitignore_unprotected(st) if git else None

    return {"station": st, "steps": p.steps, "conflicts": p.conflicts, "notes": p.notes, "manual": manual,
            "station_json": {"changed": sj_changed, "before": before, "after": after},
            "gitignore": {"git": git, "add": g_add, "before": g_before, "after": g_after,
                          "unprotected": unprotected},
            "profiles": sorted(names), "renamed": rename, "today": today}


def _is_under(path, root):
    a, b = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


# ── thực thi + sổ ──────────────────────────────────────────────────────────────────────

def _ledger_path(st, stamp):
    return os.path.join(st, LEDGER_DIR, f"layout-{stamp}.json")


def _save_ledger(path, ledger):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _do_move(st, step):
    from .station import _move_file, _move_tree
    src, dst = _abs(st, step["src"]), _abs(st, step["dst"])
    if not os.path.lexists(src):
        raise ContractError(f"nguồn không còn: {step['src']}")
    if step.get("replace_empty_dir") and os.path.isdir(dst) and not os.listdir(dst):
        os.rmdir(dst)
    if os.path.lexists(dst):
        raise ContractError(f"đích đã có: {step['dst']}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src):
        step["kind"] = "dir"
        _move_tree(src, dst)
    else:
        step["kind"] = "file"
        step["sha256"] = _sha256(src)
        step["size"] = os.path.getsize(src)
        _move_file(src, dst)


def _undo_step(st, step, report):
    """Đảo MỘT bước. Trả về nếu đã đảo hoặc vốn chưa làm; ContractError nếu không đảo được an toàn."""
    from .station import _move_file, _move_tree
    op = step["op"]
    if op == "mkdir":
        d = _abs(st, step["path"])
        if step.get("created") and os.path.isdir(d):
            if os.listdir(d):
                report["kept_dirs"].append(step["path"])
            else:
                os.rmdir(d)
        return
    if op == "move":
        src, dst = _abs(st, step["src"]), _abs(st, step["dst"])
        if not os.path.lexists(dst):
            if os.path.lexists(src):
                return                                  # đã đảo từ trước
            raise ContractError(f"mất cả hai đầu: {step['src']} và {step['dst']}")
        if os.path.lexists(src):
            raise ContractError(f"nguồn cũ đã có lại: {step['src']} — không ghi đè")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        (_move_tree if os.path.isdir(dst) else _move_file)(dst, src)
        if step.get("replace_empty_dir"):
            os.makedirs(dst, exist_ok=True)
        if step.get("sha256") and os.path.isfile(src) and _sha256(src) != step["sha256"]:
            report["changed_since"].append(step["src"])
        return
    if op == "file_edit":
        path = _abs(st, step["path"])
        cur = _read_bytes(path)
        after, before = _unb64(step["after_b64"]), _unb64(step["before_b64"])
        if cur == after:
            if before is None:
                os.remove(path)
            else:
                _write_bytes(path, before)
            return
        if step["path"] == GITIGNORE and cur is not None and before is not None:
            added = after[len(before):] if after.startswith(before) else None
            if added and added in cur:
                _write_bytes(path, cur.replace(added, b"", 1))
                return
        report["skipped_files"].append(step["path"])
        return
    raise ContractError(f"bước lạ trong sổ: {op!r}")


def _undo_steps(st, steps, report):
    for step in reversed(steps):
        _undo_step(st, step, report)


def apply_plan(plan, ledger_stamp=None):
    st = plan["station"]
    if plan["conflicts"]:
        raise ContractError("không dời được, xung đột: " + "; ".join(plan["conflicts"]) + ". Chưa đụng gì.")
    g0 = plan["gitignore"]
    if not plan["steps"] and not plan["station_json"]["changed"] and not (g0["git"] and g0["add"]):
        return {"ledger": None, "steps": 0}         # đã dời xong từ trước: không làm gì, không đẻ sổ rỗng
    stamp = ledger_stamp or _now().strftime("%Y%m%d-%H%M%S")
    lp = _ledger_path(st, stamp)
    if os.path.exists(lp):
        raise ContractError(f"sổ {lp} đã có — chạy lại sau một giây")
    ledger = {"kind": "layout-migration", "version": 1, "created": _now().isoformat(timespec="seconds"),
              "voice_studio": __version__, "status": "applying", "steps": []}
    done = ledger["steps"]
    _save_ledger(lp, ledger)

    def record(step):
        done.append(step)
        _save_ledger(lp, ledger)

    try:
        g = plan["gitignore"]
        if g["git"] and g["add"]:
            _write_bytes(os.path.join(st, GITIGNORE), g["after"])
            record({"op": "file_edit", "path": GITIGNORE, "before_b64": _b64(g["before"]),
                    "after_b64": _b64(g["after"])})
        if g["git"]:
            left = gitignore_unprotected(st)
            if left:
                raise ContractError("`.gitignore` của trạm vẫn chưa chặn: " + ", ".join(left) +
                                    " (có luật `!` khác ghi đè?) — sửa tay rồi chạy lại. Chưa dời byte nào.")
        for step in plan["steps"]:
            s = dict(step)
            if s["op"] == "mkdir":
                d = _abs(st, s["path"])
                s["created"] = not os.path.isdir(d)
                if s["created"]:
                    os.makedirs(d)
            else:
                _do_move(st, s)
            record(s)
        sj = plan["station_json"]
        if sj["changed"]:
            path = os.path.join(st, _env.STATION_FILE)
            if _read_bytes(path) != sj["before"]:
                raise ContractError("station.json đã đổi trong lúc dời — không ghi đè")
            _write_bytes(path, sj["after"])
            record({"op": "file_edit", "path": _env.STATION_FILE, "before_b64": _b64(sj["before"]),
                    "after_b64": _b64(sj["after"])})
        ledger["status"] = "applied"
        ledger["finished"] = _now().isoformat(timespec="seconds")
        _save_ledger(lp, ledger)
    except BaseException as e:
        report = {"kept_dirs": [], "changed_since": [], "skipped_files": []}
        try:
            _undo_steps(st, done, report)
            ledger["status"] = "rolled-back"
            tail = "đã hoàn tác các bước đã làm, trạm như cũ."
        except BaseException as e2:     # noqa: BLE001
            ledger["status"] = "failed"
            tail = f"hoàn tác dở ({e2}); chạy `voice-studio station migrate-layout --undo` sau khi xem sổ {lp}."
        ledger["error"] = f"{type(e).__name__}: {e}"
        _save_ledger(lp, ledger)
        if isinstance(e, KeyboardInterrupt):
            raise
        raise ContractError(f"dời trạm thất bại: {e}; {tail}") from e
    return {"ledger": lp, "steps": len(done)}


def find_ledger(st):
    d = os.path.join(st, LEDGER_DIR)
    if not os.path.isdir(d):
        return None
    for name in sorted(os.listdir(d), reverse=True):
        if name.startswith("layout-") and name.endswith(".json"):
            data, err = _env.read_json(os.path.join(d, name))
            if not err and data.get("status") in ("applied", "failed", "applying", "undo-partial"):
                return os.path.join(d, name), data
    return None


def undo(st):
    found = find_ledger(st)
    if not found:
        raise ContractError(f"không có sổ nào còn hiệu lực trong {os.path.join(st, LEDGER_DIR)} — không có gì để hoàn tác")
    path, ledger = found
    report = {"kept_dirs": [], "changed_since": [], "skipped_files": []}
    try:
        _undo_steps(st, ledger["steps"], report)
    except ContractError as e:
        ledger["status"] = "undo-partial"
        ledger["error"] = str(e)
        _save_ledger(path, ledger)
        raise ContractError(f"hoàn tác dừng giữa chừng: {e}. Sổ {path} giữ nguyên, dữ liệu chưa mất.") from e
    ledger["status"] = "undone"
    ledger["undone"] = _now().isoformat(timespec="seconds")
    _save_ledger(path, ledger)
    return {"ledger": path, "steps": len(ledger["steps"]), **report}


# ── CLI ───────────────────────────────────────────────────────────────────────────────

def _plan_report(plan):
    moves = [s for s in plan["steps"] if s["op"] == "move"]
    return {"moves": [{"src": s["src"], "dst": s["dst"], "kind": s["kind"], "why": s["why"]} for s in moves],
            "mkdirs": [s["path"] for s in plan["steps"] if s["op"] == "mkdir"],
            "manual": plan["manual"], "conflicts": plan["conflicts"], "notes": plan["notes"],
            "profiles": plan["profiles"], "renamed": plan["renamed"],
            "station_json": {"changed": plan["station_json"]["changed"]},
            "gitignore": {"git": plan["gitignore"]["git"], "add": plan["gitignore"]["add"],
                          "unprotected_now": plan["gitignore"]["unprotected"]}}


def _print_plan(plan, dry):
    log = contract.log
    rep = _plan_report(plan)
    log(f"[migrate-layout] {'XEM TRƯỚC (chưa đụng gì)' if dry else 'sẽ thực thi'} · trạm: {plan['station']}")
    log(f"[migrate-layout] {len(rep['moves'])} bước dời, {len(rep['mkdirs'])} thư mục mới, "
        f"{len(plan['profiles'])} profile: {', '.join(plan['profiles']) or '(không)'}")
    for m in rep["moves"]:
        log(f"  dời  {m['src']}  →  {m['dst']}   [{m['kind']}; {m['why']}]")
    for d in rep["mkdirs"]:
        log(f"  tạo  {d}/")
    if rep["station_json"]["changed"]:
        log("  sửa  station.json → contract/profiles_dir/music_dir/bgm_dir (giữ nguyên mọi khoá khác)")
    g = rep["gitignore"]
    if g["git"]:
        un = g["unprotected_now"]
        log(f"  git  trạm là git; chưa chặn: {', '.join(un) if un else '(không có — hoặc không hỏi được git)'}")
        if g["add"]:
            log(f"  sửa  .gitignore: thêm {len(g['add'])} dòng ({', '.join(g['add'])}) TRƯỚC khi dời")
    for n in plan["notes"]:
        log(f"  ghi chú: {n}")
    if plan["conflicts"]:
        log("[migrate-layout] XUNG ĐỘT (phải xử lý trước khi --apply):")
        for c in plan["conflicts"]:
            log(f"  ! {c}")
    if plan["manual"]:
        log(f"[migrate-layout] {len(plan['manual'])} mục NGOÀI hợp đồng — cần dời tay (hoặc đưa vào --map):")
        for m in plan["manual"]:
            log(f"  tay  {m['path']}  →  {m['hint']}")
    if dry:
        log("[migrate-layout] chưa đụng gì. Chạy lại với --apply để dời; --undo để đảo theo sổ.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="voice-studio station migrate-layout",
        description="Dời trạm kiểu cũ (omnivoice/voices, assets/bgm, <work>/lab) sang cây profiles/ + music/. "
                    "Chỉ DỜI (không xoá), có sổ, --undo đảo chính xác. Mặc định (không cờ) = --dry-run.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="chỉ in kế hoạch (mặc định)")
    mode.add_argument("--apply", action="store_true", help="thực thi")
    mode.add_argument("--undo", action="store_true", help="đảo lần dời gần nhất theo sổ")
    ap.add_argument("--station", help="trạm cần dời (mặc định: trạm đang phân giải)")
    ap.add_argument("--map", dest="map_file", help="JSON {\"moves\":[{\"from\",\"to\"}],\"rename\":{\"cũ\":\"mới\"}}: "
                                                   "dời thêm mục ngoài hợp đồng (đường tương đối theo trạm)")
    ap.add_argument("--json", action="store_true")
    args, code = contract.parse(ap, argv)
    if args is None:
        return code

    def fn(a):
        st = os.path.abspath(os.path.expanduser(a.station)) if a.station else _env.station_dir()
        if not os.path.isdir(st):
            raise contract.StationMissing(f"không có trạm giọng: {st}")
        if a.undo:
            res = undo(st)
            contract.log(f"[migrate-layout] đã hoàn tác {res['steps']} bước theo {res['ledger']}")
            for k, label in (("kept_dirs", "thư mục còn file mới, giữ lại"),
                             ("changed_since", "file đã đổi nội dung sau khi dời"),
                             ("skipped_files", "file cấu hình đã đổi sau khi dời, không ghi đè")):
                for x in res[k]:
                    contract.log(f"  ! {label}: {x}")
            return {"action": "undo", **res}
        plan = build_plan(st, a.map_file)
        rep = _plan_report(plan)
        if not a.apply:
            _print_plan(plan, dry=True)
            return {"action": "dry-run", "station": st, **rep}
        _print_plan(plan, dry=False)
        res = apply_plan(plan)
        if res["ledger"] is None:
            contract.log("[migrate-layout] trạm đã ở cây mới — không có gì để dời, không ghi sổ.")
        else:
            contract.log(f"[migrate-layout] xong: {res['steps']} bước, sổ {res['ledger']}. Gỡ biến OMNIVOICE_DIR, "
                         "VOICE_STUDIO_WORK, VOICE_BGM_DIR nếu máy còn đặt; kiểm: voice-studio doctor.")
        return {"action": "apply", "station": st, **res, **rep}
    return contract.run(fn, args, args.json)
