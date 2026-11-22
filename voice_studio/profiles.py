"""profiles.py — kho "profile giọng" để cả một video/chương dùng MỘT giọng nhất quán.

Nguyên nhân gốc của lỗi "mỗi câu một giọng": chế độ thiết kế giọng (`instruct=...`) lấy mẫu
một người nói MỚI ở mỗi lần gọi `generate()`. Cách chữa là dựng MỘT `voice_clone_prompt`
từ một clip tham chiếu cố định rồi dùng lại cho mọi câu.

## Hai kiểu bố cục trên đĩa

    KIỂU MỚI   <trạm>/profiles/<tên>/voice/<tên>.wav · .txt · .prompt.pt · .profile.json · <tên>.variants/
               (cạnh đó: raw/ lab/ report/ products/ README.md của cùng giọng)
    KIỂU CŨ    <kho phẳng>/<tên>.wav · .txt · …   với kho phẳng = VOICES_DIR hoặc <engine>/voices

Đọc: kiểu MỚI trước, lùi về kiểu cũ — trạm chưa dời (vd máy Mac) vẫn chạy. Liệt kê = HỢP hai nguồn, bỏ trùng
(kiểu mới thắng); bỏ thư mục bắt đầu bằng `_` hoặc `.` và thư mục `archive`. Ghi (profile MỚI tạo): vào kiểu
mới khi trạm đã có `profiles/` và kho phẳng không bị ghim (`set_voices_dir` / biến VOICES_DIR), ngược lại kiểu
cũ. Profile đã có thì ghi tiếp đúng chỗ nó đang nằm. Tên file bên trong KHÔNG đổi giữa hai kiểu.

Một profile = clip tham chiếu `<tên>.wav` + lời của clip `<tên>.txt`. Tên bắt đầu bằng `_` là file/thư mục
quản lý (vd `_default.txt`), không phải profile.

Profile MẶC ĐỊNH — theo thứ tự, không có tên nào viết cứng trong mã:
    1. (trạm kiểu mới) `station.json: default_profile`, rồi `profiles/_default.txt`
    2. `<kho phẳng>/_default.txt`
    3. biến môi trường `VOICE_DEFAULT_PROFILE`
    4. (trạm kiểu cũ) `station.json: default_profile`
    5. profile DUY NHẤT trong kho (chỉ khi kho có đúng một profile)
Mỗi nhánh chỉ nhận khi profile đó tồn tại. Không nhánh nào khớp ⇒ không có mặc định; `ensure_default()` báo
lỗi thay vì lùi về một giọng tổng hợp ngẫu nhiên — giọng ngẫu nhiên chính là bệnh "lung tung" cần tránh.

Clone prompt có ba tầng cache, nhanh trước: RAM trong tiến trình → `<tên>.prompt.pt` cạnh
profile trên đĩa → dựng lại từ clip. Tầng đĩa làm lần gọi ĐẦU của một tiến trình mới rẻ hơn
khoảng 50 lần; nó chỉ là cache, hỏng thì im lặng dựng lại và ghi đè.

Kho phẳng lấy từ `voice_studio._env.voices_dir()` (VOICES_DIR → trạm giọng), đọc lại mỗi
lần gọi; `set_voices_dir()` ghim cứng một thư mục cho cả tiến trình nếu cần.

Tên profile so theo Unicode **NFC**. Tên file/thư mục tiếng Việt có dấu có thể nằm trên đĩa ở dạng NFD
(chép từ máy khác, giải nén trên macOS) trong khi cấu hình và lời gọi viết NFC: nhìn giống hệt
nhau nhưng `==` ra sai. Vì thế `list_profiles()` và `get_default()` trả tên NFC, và mọi chỗ mở
file/thư mục tìm tên thật trên đĩa theo NFC — **không bao giờ đổi tên file của người dùng**.
"""
import json
import os
import unicodedata

from . import _env
from ._torchguard import no_grad_guard
from .contract import StationMissing

FROZEN_SAMPLE_TEXT = (
    "Đây là giọng đọc mẫu, được dùng làm giọng mặc định nhất quán cho toàn bộ video thuyết minh.")

DEFAULT_ENV = "VOICE_DEFAULT_PROFILE"
_DEFAULT_FILE = "_default.txt"

_override_dir = None
_prompt_cache = {}          # (thư mục chứa clip, tên NFC) -> prompt

__all__ = [
    "VOICES_DIR", "FROZEN_SAMPLE_TEXT", "ProfileError",
    "voices_dir", "set_voices_dir", "profiles_dir", "voice_dir", "layout", "list_profiles", "profile_records",
    "get_default", "set_default", "ensure_default", "get_clone_prompt", "save_profile_from_wav",
    "save_profile_from_instruct", "clear_cache", "nfc", "store_exists",
]


class ProfileError(FileNotFoundError):
    """Không xác định được profile giọng để dùng. Là FileNotFoundError để code cũ bắt được."""


def voices_dir():
    """Kho PHẲNG kiểu cũ (VOICES_DIR hoặc <engine>/voices). Có thể không tồn tại trên trạm kiểu mới."""
    return _override_dir or _env.voices_dir()


def set_voices_dir(path):
    """Ghim kho phẳng cho cả tiến trình (None = quay lại đọc biến môi trường)."""
    global _override_dir
    _override_dir = os.path.abspath(os.path.expanduser(path)) if path else None


def __getattr__(name):
    # `VOICES_DIR` là thuộc tính "sống": code cũ đọc `profiles.VOICES_DIR` luôn thấy cấu hình hiện hành.
    if name == "VOICES_DIR":
        return voices_dir()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def clear_cache():
    _prompt_cache.clear()


def nfc(name):
    """Tên ở dạng Unicode NFC — dạng dùng để SO tên profile (xem docstring module)."""
    return unicodedata.normalize("NFC", name) if name else name


# ── bố cục: tìm clip của một profile ở kiểu mới hay kiểu cũ ───────────────────────────────

def profiles_dir():
    """Gốc `profiles/` của trạm (đường, có thể chưa tồn tại); chưa xác định được trạm ⇒ None."""
    try:
        return _env.profiles_dir()
    except StationMissing:
        return None


def _new_root():
    """Gốc `profiles/` nếu trạm đã dùng kiểu mới (thư mục có thật), không thì None."""
    p = profiles_dir()
    return p if p and os.path.isdir(p) else None


def _legacy_dir():
    """Kho phẳng kiểu cũ, hoặc None nếu chưa xác định được (không trạm, không VOICES_DIR)."""
    try:
        return voices_dir()
    except StationMissing:
        return None


def _pinned():
    """Kho phẳng bị ghim tường minh (`set_voices_dir` hoặc VOICES_DIR) ⇒ profile mới ghi vào đó."""
    return bool(_override_dir or _env.env("VOICES_DIR"))


def layout():
    """`new` nếu trạm đã có `profiles/`, `legacy` nếu không."""
    return "new" if _new_root() else "legacy"


def store_exists():
    """Có chỗ nào chứa profile (kiểu mới hoặc kho phẳng) tồn tại không?"""
    ld = _legacy_dir()
    return bool(_new_root() or (ld and os.path.isdir(ld)))


def _stem_in(d, name):
    """Tên thật (stem) của profile `name` trong thư mục `d`: chính `name` nếu `<name>.wav` mở được, không thì
    file `.wav` có tên trùng `name` theo NFC. Không thấy ⇒ None."""
    if not d or not name:
        return None
    if os.path.isfile(os.path.join(d, name + ".wav")):
        return name
    key = nfc(name)
    try:
        entries = sorted(os.listdir(d))
    except OSError:
        return None
    for n in entries:
        if n.endswith(".wav") and nfc(n[:-4]) == key:
            return n[:-4]
    return None


def _locate(name):
    """-> (kiểu, thư mục chứa clip, stem) của profile ĐÃ CÓ, hoặc None. Kiểu mới thắng kiểu cũ."""
    if not name:
        return None
    root = _new_root()
    if root:
        folder = _env.profile_folder(name, root)
        if folder:
            vd = os.path.join(root, folder, "voice")
            stem = _stem_in(vd, name)
            if stem is not None:
                return "new", vd, stem
    d = _legacy_dir()
    stem = _stem_in(d, name)
    if stem is not None:
        return "legacy", d, stem
    return None


def voice_dir(name):
    """Thư mục chứa clip/manifest của profile `name`: chỗ nó đang nằm, hoặc (profile CHƯA có) chỗ nó sẽ được ghi."""
    loc = _locate(name)
    if loc:
        return loc[1]
    if _new_root() and not _pinned():
        return os.path.join(_env.profile_root(name), "voice")
    return voices_dir()


def _disk_name(name):
    """Tên thật trên đĩa của profile `name` (so theo NFC); chưa có ⇒ trả nguyên `name` (profile mới)."""
    loc = _locate(name)
    return loc[2] if loc else name


def _paths(name):
    loc = _locate(name)
    if loc:
        return os.path.join(loc[1], loc[2] + ".wav"), os.path.join(loc[1], loc[2] + ".txt")
    d = voice_dir(name)
    return os.path.join(d, name + ".wav"), os.path.join(d, name + ".txt")


def _prompt_path(name):
    """Cache đĩa của clip prompt đã token hoá (omnivoice >= 0.2.0), nằm cạnh profile."""
    return _paths(name)[0][:-4] + ".prompt.pt"


def _exists(name):
    return bool(name) and _locate(name) is not None


def _drop_prompt_cache(name):
    """Quên prompt của profile ở RAM *và* trên đĩa (gọi mỗi khi wav/txt của nó đổi)."""
    _prompt_cache.pop((voice_dir(name), nfc(name)), None)
    try:
        os.remove(_prompt_path(name))
    except OSError:
        pass


def _new_names(root):
    out = {}
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return out
    for n in entries:
        if not _env.is_profile_folder(n) or not os.path.isdir(os.path.join(root, n)):
            continue
        stem = _stem_in(os.path.join(root, n, "voice"), n)
        if stem is not None:
            out[nfc(n)] = (n, os.path.join(root, n, "voice"), stem)
    return out


def _legacy_names(d):
    out = {}
    if not d or not os.path.isdir(d):
        return out
    for n in sorted(os.listdir(d)):
        if n.endswith(".wav") and not n.startswith("_"):
            out[nfc(n[:-4])] = (n[:-4], d, n[:-4])
    return out


def _marker_count(vd, stem):
    p = os.path.join(vd, stem + ".profile.json")
    if not os.path.isfile(p):
        return 0
    try:
        with open(p, "r", encoding="utf-8") as f:
            return len((json.load(f) or {}).get("variants") or {})
    except (OSError, ValueError, AttributeError):
        return 0


def profile_records():
    """Mọi profile dùng được (hợp hai kiểu, kiểu mới thắng), sắp theo tên NFC: dict
    `{name, kind: new|legacy, markers, voice_dir}`. `markers` = số marker trong `.profile.json` (0 = một giọng)."""
    recs = {}
    for kind, names in (("legacy", _legacy_names(_legacy_dir())),
                        ("new", _new_names(_new_root()) if _new_root() else {})):
        for key, (_disk, vd, stem) in names.items():
            recs[key] = {"name": key, "kind": kind, "markers": _marker_count(vd, stem), "voice_dir": vd}
    return [recs[k] for k in sorted(recs)]


def list_profiles():
    """Tên các profile trong trạm (kiểu mới ∪ kiểu cũ), dạng NFC, đã sắp xếp, không trùng."""
    return [r["name"] for r in profile_records()]


# ── mặc định ──────────────────────────────────────────────────────────────────────────

def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _station_default():
    try:
        return str(_env.station_info().get("default_profile") or "").strip()
    except StationMissing:
        return ""


def _default_file():
    """Nơi `set_default` ghi khi KHÔNG dùng station.json: `profiles/_default.txt` (trạm mới) hoặc `_default.txt` của kho phẳng."""
    root = _new_root()
    if root and not _pinned():
        return os.path.join(root, _DEFAULT_FILE)
    return os.path.join(voices_dir(), _DEFAULT_FILE)


def get_default():
    """Tên profile mặc định theo thứ tự ở docstring module, hoặc None."""
    root = _new_root()
    tried = []
    if root:
        tried += [_station_default(), _read_text(os.path.join(root, _DEFAULT_FILE))]
    d = _legacy_dir()
    if d:
        tried.append(_read_text(os.path.join(d, _DEFAULT_FILE)))
    tried.append((os.environ.get(DEFAULT_ENV) or "").strip())
    if not root:
        tried.append(_station_default())
    for n in tried:
        if n and _exists(n):
            return nfc(n)
    names = list_profiles()
    if len(names) == 1:
        return names[0]
    return None


def set_default(name):
    if not _exists(name):
        raise FileNotFoundError(f"không có profile giọng '{name}' (thiếu {name}.wav)")
    name = nfc(name)
    root = _new_root()
    if root and not _pinned():
        # Chỗ nào đang THẮNG thì cập nhật chỗ đó: station.json có default_profile thì sửa nó, không thì profiles/_default.txt.
        sj = os.path.join(_env.station_dir(), _env.STATION_FILE)
        info, err = _env.read_json(sj)
        if not err and str(info.get("default_profile") or "").strip():
            info["default_profile"] = name
            with open(sj, "w", encoding="utf-8", newline="\n") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
                f.write("\n")
            return name
    path = _default_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(name)
    return name


def ensure_default(model=None, instruct=None, name=None):
    """Trả một profile dùng được, KHÔNG BAO GIỜ lùi về giọng tổng hợp ngẫu nhiên.

    `name` (nếu đưa và tồn tại) thắng; sau đó là profile mặc định. `model`/`instruct` giữ
    trong chữ ký để tương thích với code cũ, không dùng.
    """
    if name:
        if _exists(name):
            return nfc(name)
        raise ProfileError(f"không có profile giọng '{name}' trong {_where()}")
    d = get_default()
    if d:
        return d
    names = list_profiles()
    if names:
        hint = (f"Kho có {len(names)} profile ({', '.join(names)}) nhưng chưa chọn mặc định: "
                f"ghi tên vào {_default_file()} (hoặc station.json: default_profile), "
                f"hoặc đặt biến {DEFAULT_ENV}, hoặc truyền tên profile khi gọi.")
    else:
        hint = (f"Kho giọng {_where()} chưa có profile nào. Tạo một profile trước "
                f"(clone từ bản ghi có sự đồng ý, hoặc đóng băng một giọng từ `instruct`), "
                f"rồi đặt {DEFAULT_ENV} nếu kho có nhiều profile.")
    raise ProfileError(hint + " Không render bằng giọng tổng hợp ngẫu nhiên.")


def _where():
    return _new_root() or _legacy_dir() or "(chưa xác định trạm)"


def save_profile_from_wav(src_wav, ref_text, name, set_as_default=True):
    """Tạo profile bằng cách clone một bản ghi thật (trộn về mono, giữ sample rate).

    Chỉ clone giọng của chính mình, hoặc người đã đồng ý.
    """
    import soundfile as sf
    if not os.path.isfile(src_wav):
        raise FileNotFoundError(src_wav)
    wav, txt = _paths(name)
    os.makedirs(os.path.dirname(wav), exist_ok=True)
    data, sr = sf.read(src_wav)
    if getattr(data, "ndim", 1) > 1:
        data = data.mean(axis=1)
    sf.write(wav, data, sr)
    with open(txt, "w", encoding="utf-8") as f:
        f.write((ref_text or "").strip())
    _drop_prompt_cache(name)
    if set_as_default:
        set_default(name)
    return name


def save_profile_from_instruct(model, instruct, name, sample_text=None, set_as_default=True,
                               language="Vietnamese"):
    """Đóng băng MỘT giọng tổng hợp nhất quán từ `instruct` (không cần bản ghi)."""
    import soundfile as sf
    sample_text = (sample_text or FROZEN_SAMPLE_TEXT).strip()
    wav, txt = _paths(name)
    os.makedirs(os.path.dirname(wav), exist_ok=True)
    with no_grad_guard():
        audio = model.generate(text=sample_text, language=language, instruct=instruct)[0]
    sf.write(wav, audio, model.sampling_rate)
    with open(txt, "w", encoding="utf-8") as f:
        f.write(sample_text)
    _drop_prompt_cache(name)
    if set_as_default:
        set_default(name)
    return name


def _load_cached_prompt(name, wav):
    """Prompt trên đĩa của `name`, hoặc None nếu thiếu/cũ/không đọc được.

    Cũ = clip tham chiếu (hoặc lời của nó) mới hơn cache — profile thu lại thì không bao giờ
    được phục vụ bằng prompt lỗi thời.
    """
    pt = _prompt_path(name)
    if not os.path.isfile(pt):
        return None
    try:
        cached_at = os.path.getmtime(pt)
        newest_src = os.path.getmtime(wav)
        txt = _paths(name)[1]
        if os.path.isfile(txt):
            newest_src = max(newest_src, os.path.getmtime(txt))
        if newest_src > cached_at:
            return None
        from omnivoice.models.omnivoice import VoiceClonePrompt
        return VoiceClonePrompt.load(pt)
    except Exception:
        # File hỏng, hoặc prompt ghi bởi bản omnivoice khác định dạng — dựng lại.
        return None


def get_clone_prompt(model, name=None):
    """Clone prompt dùng lại được cho profile `name` (hoặc mặc định). None nếu không có profile nào."""
    name = name or get_default()
    if not name:
        return None
    key = (voice_dir(name), nfc(name))
    if key in _prompt_cache:
        return _prompt_cache[key]
    wav, txt = _paths(name)
    if not os.path.isfile(wav):
        raise FileNotFoundError(f"profile giọng '{name}' thiếu {wav}")

    prompt = _load_cached_prompt(name, wav)
    if prompt is None:
        ref_text = None
        if os.path.isfile(txt):
            with open(txt, "r", encoding="utf-8") as f:
                ref_text = f.read().strip() or None
        with no_grad_guard():
            prompt = model.create_voice_clone_prompt(ref_audio=wav, ref_text=ref_text)
        try:    # cố gắng hết sức: kho giọng chỉ-đọc không được làm hỏng việc tổng hợp
            prompt.save(_prompt_path(name))
        except Exception:
            pass

    _prompt_cache[key] = prompt
    return prompt
