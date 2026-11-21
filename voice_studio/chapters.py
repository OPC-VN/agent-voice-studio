"""Đọc manifest truyện và xuất mốc chương."""
import argparse
import json
import math
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import BinaryIO, Sequence

from . import _env, contract
from ._m4b import add_chapter_lead_in
from .contract import ContractError, EngineError

_FFMETADATA_ESCAPES = str.maketrans({char: "\\" + char for char in "=;#\\\n"})
_AUDIO_FORMATS = {
    ".aac": "aac", ".flac": "flac", ".m4a": "mov", ".m4b": "mov",
    ".mp3": "mp3", ".ogg": "ogg", ".opus": "ogg", ".wav": "wav",
}
_PCM_RATE = 48000
_PCM_CHANNELS = 2
_PCM_FRAME_BYTES = _PCM_CHANNELS * 2  # Signed 16-bit PCM.


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


def _utf8_field(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ContractError(f"{field} phải là chuỗi không rỗng.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractError(f"{field} không biểu diễn được bằng UTF-8.") from exc
    return value


def parse_manifest(source: str) -> tuple[str, list[Chapter]]:
    """Đọc JSON của pipeline truyện. Mốc tính bằng giây từ đầu audio."""
    try:
        data = json.loads(source)
    except (ValueError, RecursionError) as exc:
        raise ContractError(f"Manifest JSON không hợp lệ: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError("Manifest phải là một đối tượng JSON.")
    audio = _utf8_field(data.get("audio"), "Đường dẫn audio")
    rows = data.get("chapters")
    if not isinstance(rows, list) or not rows:
        raise ContractError("Manifest cần danh sách chapters có ít nhất một chương.")

    chapters: list[Chapter] = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ContractError(f"Chương {i} phải là một đối tượng JSON.")
        title = _utf8_field(row.get("title"), f"Chương {i}: title")
        start = _seconds(row.get("start"), f"Chương {i}: start")
        dur = _seconds(row.get("dur"), f"Chương {i}: dur")
        if dur <= 0:
            raise ContractError(f"Chương {i}: dur phải lớn hơn 0.")
        if chapters:
            previous = chapters[-1]
            if start <= previous.start:
                raise ContractError(f"Chương {i} phải bắt đầu sau mốc bắt đầu của chương {i - 1}.")
            previous_end = previous.start + previous.dur
            # Chấp nhận sai số cộng số thực ở các mốc liền nhau, ví dụ 0.1 + 0.2.
            if start < previous_end and not math.isclose(start, previous_end, abs_tol=1e-9, rel_tol=0):
                raise ContractError(f"Chương {i} chồng lấn với chương {i - 1}.")
        title = title.replace("\r\n", "\n").replace("\r", "\n")
        chapters.append(Chapter(title, start, dur))
    return audio, chapters


def _one_line(title: str) -> str:
    return " ".join(title.splitlines())


def render_text(chapters: Sequence[Chapter]) -> str:
    """Mốc HH:MM:SS cho mô tả YouTube."""
    lines = []
    for index, chapter in enumerate(chapters):
        # YouTube cần mốc 0. Đoạn dẫn nhập thuộc mục đầu tiên trong bản text.
        hours, rest = divmod(int(chapter.start) if index else 0, 3600)
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
        # Khi chia số mẫu rồi nhân 75, một mốc đúng frame có thể thấp hơn một ULP.
        seconds, frames = divmod(int(math.nextafter(chapter.start * 75, math.inf)), 75)
        minutes, seconds = divmod(seconds, 60)
        lines.extend((f"  TRACK {number:02} AUDIO", f'    TITLE "{_cue_label(chapter.title)}"',
                      f"    INDEX 01 {minutes:02}:{seconds:02}:{frames:02}"))
    return "\n".join(lines) + "\n"


def _read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"Không đọc được tệp UTF-8 {path}: {exc}") from exc


def _audio_input(path: Path) -> list[str]:
    audio_format = _AUDIO_FORMATS.get(path.suffix.lower())
    if not audio_format or not path.is_file():
        raise ContractError(f"Cần file audio cục bộ có định dạng hỗ trợ: {path}")
    # Chỉ mở audio cục bộ. Không dò playlist hoặc định dạng tham chiếu nguồn khác.
    return ["-protocol_whitelist", "file", "-f", audio_format, "-i", str(path)]


def _directory_sources(audio_dir: Path, labels_file: Path) -> list[tuple[Path, str]]:
    if not audio_dir.is_dir():
        raise ContractError(f"Không có thư mục audio: {audio_dir}")
    paths = sorted(
        (path for path in audio_dir.iterdir()
         if path.suffix.lower() in _AUDIO_FORMATS and path.is_file()),
        key=lambda path: (path.name.casefold(), path.name),
    )
    labels = []
    for line in _read_utf8(labels_file).splitlines():
        if not line.strip():
            continue
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2 or not re.fullmatch(r"[0-9]{2,}:[0-5][0-9]:[0-5][0-9]", fields[0]):
            raise ContractError("Mỗi dòng trong chapters.txt cần có HH:MM:SS và tên chương.")
        labels.append(fields[1])
    if not paths or len(paths) != len(labels):
        raise ContractError(
            f"Cần một tên chương cho mỗi file audio, có {len(labels)} tên và {len(paths)} file."
        )
    return list(zip(paths, labels))


def _run_ffmpeg(exe: str, args: list[str], *, stdout: BinaryIO | None = None) -> None:
    result = subprocess.run(
        [exe, "-nostdin", "-v", "error", "-xerror", *args],
        stdout=subprocess.DEVNULL if stdout is None else stdout, stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise EngineError(f"FFmpeg lỗi (mã {result.returncode}): {detail}")


def _warn_past_audio_end(ffmpeg: str, input_args: list[str], chapters: Sequence[Chapter]) -> None:
    """Thử lấy thời lượng từ đầu vào mà không giải mã toàn bộ audio."""
    try:
        result = subprocess.run(
            [ffmpeg or _env.ffmpeg_exe(), "-nostdin", "-hide_banner", "-v", "info",
             *input_args, "-map", "0:a:0", "-t", "0", "-c:a", "copy", "-f", "null", "-"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15,
        )
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return  # Xuất TXT/JSON vẫn dùng được khi không đo được audio.
    if result.returncode:
        return
    match = re.search(rb"(?m)^  Duration: (\d+):(\d\d):(\d\d\.\d+),", result.stderr)
    if not match:
        return
    hours, minutes, seconds = map(float, match.groups())
    duration = hours * 3600 + minutes * 60 + seconds
    for i, chapter in enumerate(chapters, 1):
        end = chapter.start + chapter.dur
        # Dòng Duration của FFmpeg chỉ có độ phân giải 0.01 giây.
        if end > duration + 0.005:
            contract.log(f"Cảnh báo: chương {i} kết thúc ở {end:.3f} s, "
                         f"vượt độ dài audio {duration:.3f} s.")


def _join_pcm(
    ffmpeg: str, sources: Sequence[tuple[Path, str]], pcm_path: Path, *, keep_pcm: bool,
) -> list[Chapter]:
    """Chép từng stream PCM liền nhau và tính mốc từ số frame đã giải mã."""
    chapters = []
    total_frames = 0
    with pcm_path.open("wb", buffering=0) as pcm:
        for path, title in sources:
            start_byte = pcm.tell()
            _run_ffmpeg(ffmpeg, [
                *_audio_input(path), "-map", "0:a:0", "-ac", str(_PCM_CHANNELS),
                "-ar", str(_PCM_RATE), "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
            ], stdout=pcm)
            frames, remainder = divmod(pcm.tell() - start_byte, _PCM_FRAME_BYTES)
            if not frames or remainder:
                raise EngineError(f"FFmpeg không trả về PCM đầy đủ cho {path}.")
            chapters.append(Chapter(title, total_frames / _PCM_RATE, frames / _PCM_RATE))
            total_frames += frames
            if not keep_pcm:
                pcm.seek(0)
                pcm.truncate()
    return chapters


def _ffmpeg_version(ffmpeg: str) -> str:
    try:
        output = subprocess.check_output([ffmpeg, "-version"], stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return "FFmpeg chưa đọc được phiên bản"
    lines = output.decode("utf-8", errors="replace").splitlines()
    return lines[0] if lines else "FFmpeg chưa đọc được phiên bản"


def _verify_m4b_timing(ffmpeg: str, target: Path, chapters: Sequence[Chapter]) -> None:
    try:
        result = subprocess.run(
            [ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-f", "mov",
             "-i", str(target), "-map_metadata", "-1", "-map_metadata:c", "-1",
             "-f", "ffmetadata", "-"],
            capture_output=True, timeout=30,
        )
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()[-500:]
            raise ValueError(f"Đọc mốc chương thất bại (mã {result.returncode}): {detail}")
        # Bỏ tag để tiêu đề có nhiều dòng không bị nhầm với khối [CHAPTER].
        metadata = result.stdout.decode("utf-8").replace("\r\n", "\n")
        header, *blocks = metadata.split("\n[CHAPTER]\n")
        if not header.startswith(";FFMETADATA1"):
            raise ValueError("Đầu ra đọc lại thiếu đầu mục FFMETADATA1.")
        if len(blocks) != len(chapters):
            raise ValueError(f"Mong đợi {len(chapters)} chương, đọc được {len(blocks)} chương.")

        checks = []
        for index, (chapter, block) in enumerate(zip(chapters, blocks, strict=True), 1):
            match = re.fullmatch(
                r"TIMEBASE=([1-9][0-9]*)/([1-9][0-9]*)\nSTART=(-?[0-9]+)\nEND=(-?[0-9]+)",
                block.strip(),
            )
            if not match:
                raise ValueError(f"Không đọc được TIMEBASE/START/END của chương {index}.")
            num, den, start, end = map(int, match.groups())
            unit = Fraction(num, den)
            checks.append((index, "START", Fraction(str(chapter.start)), unit * start))
        last = chapters[-1]
        checks.append((len(chapters), "END", Fraction(str(last.start)) + Fraction(str(last.dur)), unit * end))
        for index, field, expected, actual in checks:
            if abs(expected - actual) > Fraction(1, 1000):
                raise ValueError(
                    f"Mốc {field} chương {index}: mong đợi {float(expected):.6f} s, "
                    f"đọc được {float(actual):.6f} s."
                )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise EngineError(f"Tự kiểm mốc M4B thất bại ({_ffmpeg_version(ffmpeg)}): {exc}") from exc


def _write_m4b(
    ffmpeg: str, input_args: list[str], chapters: Sequence[Chapter], target: Path,
) -> None:
    metadata = target.with_suffix(".ffmetadata")
    safe_chapters = []
    overrides = []
    for i, chapter in enumerate(chapters):
        if chapter.title.endswith("\\"):
            # FFmpeg có thể đọc tiếp sang khối sau dù backslash cuối dòng đã escape.
            safe_chapters.append(Chapter(" ", chapter.start, chapter.dur))
            overrides.extend((f"-metadata:c:{i}", f"title={chapter.title}"))
        else:
            safe_chapters.append(chapter)
    metadata.write_text(render_ffmetadata(safe_chapters), encoding="utf-8", newline="\n")
    lead_in_ms = round(chapters[0].start * 1000)
    timing_options = ["-movie_timescale", "1000", "-use_editlist", "1"] if lead_in_ms else []
    _run_ffmpeg(ffmpeg, [
        *input_args, "-protocol_whitelist", "file", "-f", "ffmetadata", "-i", str(metadata),
        "-map", "0:a:0", "-map_metadata", "1", "-map_chapters", "1",
        *overrides, *timing_options, "-c:a", "aac", str(target),
    ])
    if lead_in_ms:
        add_chapter_lead_in(target, lead_in_ms)
        _verify_m4b_timing(ffmpeg, target, chapters)


def _publish(stage: Path, paths: Sequence[Path]) -> None:
    previous = stage / "previous"
    previous.mkdir()
    touched = []
    try:
        for path in paths:
            touched.append(path)
            if path.exists():
                path.replace(previous / path.name)
            (stage / path.name).replace(path)
    except (OSError, KeyboardInterrupt):
        for path in reversed(touched):
            saved = previous / path.name
            if saved.exists():
                saved.replace(path)
            elif not (stage / path.name).exists():
                path.unlink(missing_ok=True)
        raise


def export_chapters(args: argparse.Namespace) -> dict[str, object]:
    """Xuất sidecar và tuỳ chọn bọc AAC có chương."""
    out_dir = args.out_dir.resolve()
    audio = None
    sources: list[tuple[Path, str]] = []
    if args.manifest is not None:
        if args.chapters_file is not None:
            raise ContractError("--chapters-file chỉ dùng với --audio-dir.")
        source = args.manifest.resolve()
        audio_ref, chapters = parse_manifest(_read_utf8(source))
        audio = (source.parent / audio_ref).resolve()
        input_args = _audio_input(audio) if args.m4b else []
        protected = {source, audio}
    else:
        audio_dir = args.audio_dir.resolve()
        if out_dir == audio_dir:
            raise ContractError("--out-dir phải khác --audio-dir.")
        labels_file = (args.chapters_file or audio_dir / "chapters.txt").resolve()
        sources = _directory_sources(audio_dir, labels_file)
        protected = {labels_file, *(path.resolve() for path, _ in sources)}

    names = {"text": "chapters.txt", "json": "chapters.json"}
    if args.m4b:
        names.update(m4b="chapters.m4b", cue="chapters.cue")
    outputs = {key: out_dir / name for key, name in names.items()}
    if any(path.resolve() in protected for path in outputs.values()):
        raise ContractError("Đầu ra trùng với tệp đầu vào. Hãy chọn --out-dir khác.")
    if any(path.is_symlink() or (path.exists() and not path.is_file())
           for path in outputs.values()):
        raise ContractError("Đường dẫn đầu ra đã bị chiếm bởi thư mục hoặc liên kết.")

    ffmpeg = _env.ffmpeg_exe() if sources or args.m4b else ""
    if audio is not None and (input_args or (audio.suffix.lower() in _AUDIO_FORMATS and audio.is_file())):
        _warn_past_audio_end(ffmpeg, input_args or _audio_input(audio), chapters)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".chapters-", dir=out_dir) as scratch:
        stage = Path(scratch)
        if sources:
            pcm = stage / "chapters.pcm"
            chapters = _join_pcm(ffmpeg, sources, pcm, keep_pcm=args.m4b)
            input_args = ["-protocol_whitelist", "file", "-f", "s16le",
                          "-ar", str(_PCM_RATE), "-ac", str(_PCM_CHANNELS), "-i", str(pcm)]
        (stage / names["text"]).write_text(render_text(chapters), encoding="utf-8", newline="\n")
        (stage / names["json"]).write_text(render_json(chapters), encoding="utf-8", newline="\n")
        if args.m4b:
            _write_m4b(ffmpeg, input_args, chapters, stage / names["m4b"])
            (stage / names["cue"]).write_text(
                render_cue(names["m4b"], chapters), encoding="utf-8", newline="\n",
            )
        _publish(stage, list(outputs.values()))
    contract.log(f"[chapters] {len(chapters)} chương → {out_dir}")
    return {"chapter_count": len(chapters),
            "outputs": {key: str(path) for key, path in outputs.items()}}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="voice-studio chapters", description="Xuất mốc truyện, tuỳ chọn thêm sách nói AAC.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path, help="JSON của pipeline truyện.")
    source.add_argument("--audio-dir", type=Path, help="Thư mục có một file audio cho mỗi chương.")
    parser.add_argument("--chapters-file", type=Path, help="Mặc định: <audio-dir>/chapters.txt.")
    parser.add_argument("--out-dir", type=Path, required=True, help="Thư mục ghi kết quả.")
    parser.add_argument("--m4b", action="store_true", help="Thêm chapters.m4b (AAC) và chapters.cue.")
    parser.add_argument("--json", action="store_true", help="In một dòng JSON kết quả.")
    args, code = contract.parse(parser, argv)
    if code is not None:
        return code
    return contract.run(export_chapters, args, args.json)
