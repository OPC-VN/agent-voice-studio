"""Đọc manifest truyện và xuất mốc chương."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from .contract import ContractError

_FFMETADATA_ESCAPES = str.maketrans({char: "\\" + char for char in "=;#\\\n"})


@dataclass(frozen=True)
class Chapter:
    title: str
    start: float
    dur: float


def _seconds(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ContractError(f"{field} phải là số giây.")
    if not 0 <= value < 2**52 / 1000:
        raise ContractError(f"{field} phải là số giây hữu hạn, không âm và trong phạm vi mốc chương.")
    return float(value)


def parse_manifest(source: str) -> tuple[str, list[Chapter]]:
    """Đọc JSON của pipeline truyện. Mốc tính bằng giây, bắt đầu từ 0."""
    try:
        data = json.loads(source)
    except (ValueError, RecursionError) as exc:
        raise ContractError(f"Manifest JSON không hợp lệ: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError("Manifest phải là một đối tượng JSON.")
    audio = data.get("audio")
    rows = data.get("chapters")
    if not isinstance(audio, str) or not audio.strip() or "\0" in audio:
        raise ContractError("Manifest cần trường audio là đường dẫn.")
    if not isinstance(rows, list) or not rows:
        raise ContractError("Manifest cần danh sách chapters có ít nhất một chương.")

    chapters: list[Chapter] = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ContractError(f"Chương {i} phải là một đối tượng JSON.")
        title = row.get("title")
        if not isinstance(title, str) or not title.strip() or "\0" in title:
            raise ContractError(f"Chương {i} thiếu tiêu đề hợp lệ.")
        start = _seconds(row.get("start"), f"Chương {i}: start")
        dur = _seconds(row.get("dur"), f"Chương {i}: dur")
        if dur <= 0:
            raise ContractError(f"Chương {i}: dur phải lớn hơn 0.")
        if (chapters and start <= chapters[-1].start) or (not chapters and start != 0):
            raise ContractError("Mốc chương phải bắt đầu từ 0 và tăng dần.")
        title = title.replace("\r\n", "\n").replace("\r", "\n")
        chapters.append(Chapter(title, start, dur))
    return audio, chapters


def _one_line(title: str) -> str:
    return " ".join(title.splitlines())


def render_text(chapters: Sequence[Chapter]) -> str:
    """Mốc HH:MM:SS cho mô tả YouTube."""
    lines = []
    for chapter in chapters:
        hours, rest = divmod(int(chapter.start), 3600)
        minutes, seconds = divmod(rest, 60)
        lines.append(f"{hours:02}:{minutes:02}:{seconds:02} {_one_line(chapter.title)}\n")
    return "".join(lines)


def render_json(chapters: Sequence[Chapter]) -> str:
    return json.dumps([asdict(chapter) for chapter in chapters], ensure_ascii=False, indent=2) + "\n"


def render_ffmetadata(chapters: Sequence[Chapter]) -> str:
    """Mốc theo đơn vị mili giây và tiêu đề escape theo định dạng FFmpeg."""
    lines = [";FFMETADATA1"]
    previous_start = -1
    for chapter in chapters:
        start = round(chapter.start * 1000)
        end = round((chapter.start + chapter.dur) * 1000)
        if start <= previous_start or end <= start:
            raise ContractError("Mốc chương phải phân biệt được đến mili giây.")
        lines.extend(("[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}",
                      f"title={chapter.title.translate(_FFMETADATA_ESCAPES)}"))
        previous_start = start
    return "\n".join(lines) + "\n"


def _cue_label(value: str) -> str:
    # CUE dùng dấu ngoặc kép để phân định nội dung.
    return _one_line(value).replace('"', "”")


def render_cue(audio: str, chapters: Sequence[Chapter]) -> str:
    """CUE dùng 75 frame mỗi giây."""
    file_type = "MP3" if Path(audio).suffix.lower() == ".mp3" else "WAVE"
    lines = [f'FILE "{_cue_label(audio)}" {file_type}']
    for number, chapter in enumerate(chapters, 1):
        seconds, frames = divmod(int(chapter.start * 75), 75)
        minutes, seconds = divmod(seconds, 60)
        lines.extend((f"  TRACK {number:02} AUDIO", f'    TITLE "{_cue_label(chapter.title)}"',
                      f"    INDEX 01 {minutes:02}:{seconds:02}:{frames:02}"))
    return "\n".join(lines) + "\n"
