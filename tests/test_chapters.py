"""Mốc chương thuần, không cần FFmpeg hay engine giọng."""
import importlib.util
import json

import pytest

from voice_studio.contract import ContractError


def _chapters_module():
    assert importlib.util.find_spec("voice_studio.chapters"), "chưa có bộ xuất mốc chương"
    from voice_studio import chapters

    return chapters


def test_manifest_and_text_formats_preserve_vietnamese():
    chapters = _chapters_module()
    source = json.dumps({
        "audio": "Tập một.mp3",
        "chapters": [
            {"title": "Mở đầu", "start": 0, "dur": 3702.5},
            {"title": "Chương 2 = chuyện; mới #1\\ tiếp\ndòng 2", "start": 3702.5, "dur": 5},
        ],
    }, ensure_ascii=False)
    audio, marks = chapters.parse_manifest(source)

    assert audio == "Tập một.mp3"
    assert chapters.render_text(marks) == (
        "00:00:00 Mở đầu\n01:01:42 Chương 2 = chuyện; mới #1\\ tiếp dòng 2\n"
    )
    assert json.loads(chapters.render_json(marks)) == json.loads(source)["chapters"]
    assert "Chương 2" in chapters.render_json(marks)
    assert chapters.render_ffmetadata(marks) == (
        ";FFMETADATA1\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=3702500\ntitle=Mở đầu\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=3702500\nEND=3707500\n"
        "title=Chương 2 \\= chuyện\\; mới \\#1\\\\ tiếp\\\ndòng 2\n"
    )
    assert chapters.render_cue(audio, marks) == (
        'FILE "Tập một.mp3" MP3\n'
        '  TRACK 01 AUDIO\n    TITLE "Mở đầu"\n    INDEX 01 00:00:00\n'
        '  TRACK 02 AUDIO\n    TITLE "Chương 2 = chuyện; mới #1\\ tiếp dòng 2"\n'
        '    INDEX 01 61:42:37\n'
    )


@pytest.mark.parametrize("payload", [
    None,
    {"audio": "a.wav", "chapters": []},
    {"audio": " ", "chapters": [{"title": "A", "start": 0, "dur": 1}]},
    {"audio": "a.wav", "chapters": [None]},
    {"audio": "a.wav", "chapters": [{"title": " ", "start": 0, "dur": 1}]},
    {"audio": "a.wav", "chapters": [{"title": "A", "start": True, "dur": 1}]},
    {"audio": "a.wav", "chapters": [{"title": "A", "start": -1, "dur": 1}]},
    {"audio": "a.wav", "chapters": [{"title": "A", "start": 1, "dur": 1}]},
    {"audio": "a.wav", "chapters": [{"title": "A", "start": 0, "dur": 0}]},
    {"audio": "a.wav", "chapters": [{"title": "A", "start": 0, "dur": float("inf")}]},
    {"audio": "a.wav", "chapters": [
        {"title": "A", "start": 0, "dur": 1},
        {"title": "B", "start": 0, "dur": 1},
    ]},
])
def test_manifest_rejects_invalid_shape_or_timing(payload):
    with pytest.raises(ContractError):
        _chapters_module().parse_manifest(json.dumps(payload))


def test_invalid_json_is_input_error():
    with pytest.raises(ContractError, match="JSON"):
        _chapters_module().parse_manifest("{")
