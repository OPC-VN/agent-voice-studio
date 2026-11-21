"""Giữ mốc dẫn nhập của track chương QuickTime trong M4B do FFmpeg xuất."""

import struct
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Iterator, NamedTuple

from .contract import EngineError


class _Box(NamedTuple):
    kind: bytes
    start: int
    payload: int
    end: int


def _boxes(stream: BinaryIO, end: int) -> Iterator[_Box]:
    while (start := stream.tell()) < end:
        size, kind = struct.unpack(">I4s", stream.read(8))
        if size == 1:
            size, = struct.unpack(">Q", stream.read(8))
        elif size == 0:
            size = end - start
        payload = stream.tell()
        if not payload <= start + size <= end:
            raise ValueError("Kích thước box M4B không hợp lệ.")
        yield _Box(kind, start, payload, start + size)
        stream.seek(start + size)


def _children(stream: BinaryIO, parent: _Box) -> list[_Box]:
    stream.seek(parent.payload)
    return list(_boxes(stream, parent.end))


def _child(stream: BinaryIO, parent: _Box, kind: bytes) -> _Box:
    return next(box for box in _children(stream, parent) if box.kind == kind)


def _extend_duration(data: bytearray, box: _Box, duration: int) -> None:
    version = data[box.payload]
    if version not in (0, 1):
        raise ValueError("Phiên bản header M4B chưa được hỗ trợ.")
    # tkhd có thêm track ID và một trường dành riêng trước thời lượng.
    offset = box.payload + (24 if version else 16) + (4 if box.kind == b"tkhd" else 0)
    format_code = ">Q" if version else ">I"
    current, = struct.unpack_from(format_code, data, offset)
    struct.pack_into(format_code, data, offset, max(current, duration))


def add_chapter_lead_in(target: Path, lead_ms: int) -> None:
    """Sửa bảng thời gian của track chương. Track audio và bảng Nero giữ nguyên."""
    try:
        with target.open("r+b") as file:
            file_end = file.seek(0, 2)
            file.seek(0)
            movie = next(box for box in _boxes(file, file_end) if box.kind == b"moov")
            if movie.end != file_end:
                raise ValueError("Cần moov ở cuối tệp M4B.")
            file.seek(movie.start)
            data = bytearray(file.read(movie.end - movie.start))
            _apply_lead_in(data, lead_ms)
            file.seek(movie.start)
            file.write(data)
    except (OSError, StopIteration, IndexError, ValueError, struct.error) as exc:
        raise EngineError("Không thể giữ mốc dẫn nhập trong track chương M4B.") from exc


def _apply_lead_in(data: bytearray, lead_ms: int) -> None:
    stream = BytesIO(data)
    movie = next(_boxes(stream, len(data)))
    # Lệnh xuất chỉ map một track audio. FFmpeg thêm track chương ở vị trí thứ hai.
    _, track = [box for box in _children(stream, movie) if box.kind == b"trak"]
    edits = _child(stream, track, b"edts")
    edit_list = _child(stream, edits, b"elst")
    media = _child(stream, track, b"mdia")
    header = _child(stream, media, b"mdhd")
    media_info = _child(stream, media, b"minf")
    sample_table = _child(stream, media_info, b"stbl")
    sample_times = _child(stream, sample_table, b"stts")
    entry_offset = sample_times.payload + 4
    run_count, first_count, first_delta = struct.unpack_from(">III", data, entry_offset)
    if not run_count or not first_count:
        raise ValueError("Bảng thời gian mẫu chương không hợp lệ.")

    # Thang thời gian ở cả movie và track chương là 1000 đơn vị/giây.
    edit_version, = struct.unpack_from(">B", data, edit_list.payload)
    edit_format = {0: ">IiI", 1: ">QqI"}.get(edit_version)
    if edit_format is None:
        raise ValueError("Phiên bản edit list chưa được hỗ trợ.")
    edit_count, = struct.unpack_from(">I", data, edit_list.payload + 4)
    edit_start = edit_list.payload + 8
    duration, media_start, rate = struct.unpack_from(edit_format, data, edit_start)
    if edit_count == 2 and duration == lead_ms and media_start == -1:
        return  # Phiên bản FFmpeg đã ghi edit dẫn nhập đúng.
    if edit_count != 1 or media_start != 0 or rate != 0x10000:
        raise ValueError("Edit list của track chương không đúng cấu trúc dự kiến.")

    # Với một chương, FFmpeg dùng thời lượng mẫu trực tiếp. Với nhiều chương,
    # FFmpeg gộp đoạn dẫn vào mẫu đầu khi tính chênh lệch đến mốc kế tiếp.
    single_chapter = run_count == first_count == 1
    merged_lead = 0 if single_chapter else lead_ms
    if duration <= merged_lead or first_delta <= merged_lead:
        raise ValueError("Độ dài mẫu đầu không khớp với đoạn dẫn.")
    empty_edit = struct.pack(edit_format, lead_ms, -1, rate)
    struct.pack_into(">I", data, edit_list.payload + 4, 2)
    struct.pack_into(edit_format, data, edit_start, duration - merged_lead, 0, rate)
    if single_chapter:
        _extend_duration(data, _child(stream, track, b"tkhd"), duration + lead_ms)
        _extend_duration(data, _child(stream, movie, b"mvhd"), duration + lead_ms)

    media_version, = struct.unpack_from(">B", data, header.payload)
    media_timing = {0: (12, ">II"), 1: (20, ">IQ")}.get(media_version)
    if media_timing is None:
        raise ValueError("Phiên bản media header chưa được hỗ trợ.")
    offset, media_format = media_timing
    time_scale, media_duration = struct.unpack_from(media_format, data, header.payload + offset)
    if time_scale != 1000 or media_duration <= merged_lead:
        raise ValueError("Thang hoặc độ dài track chương không hợp lệ.")
    struct.pack_into(
        media_format, data, header.payload + offset, time_scale, media_duration - merged_lead,
    )

    struct.pack_into(">II", data, entry_offset + 4, 1, first_delta - merged_lead)
    insertions = [(edit_start, empty_edit)]
    growth = {box: len(empty_edit) for box in (movie, track, edits, edit_list)}
    if first_count > 1:
        remainder = struct.pack(">II", first_count - 1, first_delta)
        struct.pack_into(">I", data, entry_offset, run_count + 1)
        insertions.append((entry_offset + 12, remainder))
        for box in (movie, track, media, media_info, sample_table, sample_times):
            growth[box] = growth.get(box, 0) + len(remainder)
    for box, extra in growth.items():
        if box.payload - box.start == 16:
            struct.pack_into(">Q", data, box.start + 8, box.end - box.start + extra)
        else:
            struct.pack_into(">I", data, box.start, box.end - box.start + extra)
    for offset, entry in sorted(insertions, reverse=True):
        data[offset:offset] = entry
