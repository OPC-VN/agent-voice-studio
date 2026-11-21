"""Mốc chương thuần, không cần FFmpeg hay engine giọng."""
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

from voice_studio import _env, cli
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
    {"audio": "\ud800.wav", "chapters": [{"title": "A", "start": 0, "dur": 1}]},
    {"audio": "a.wav", "chapters": [{"title": "\ud800", "start": 0, "dur": 1}]},
    {"audio": "a.wav", "chapters": [{"title": "A", "start": True, "dur": 1}]},
    {"audio": "a.wav", "chapters": [{"title": "A", "start": -1, "dur": 1}]},
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


def test_cue_preserves_exact_frame_boundary_after_resampling():
    chapters = _chapters_module()
    marks = [chapters.Chapter("Một", 0, 1), chapters.Chapter("Hai", 35200 / 48000, 1)]
    assert "INDEX 01 00:00:55" in chapters.render_cue("chapters.m4b", marks)


def _ffmpeg_or_skip():
    try:
        return _env.ffmpeg_exe()
    except RuntimeError:
        pytest.skip("Cần FFmpeg để mã hóa và đọc lại M4B thực.")


def _read_m4b(path, ffmpeg):
    result = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-i", str(path), "-f", "ffmetadata", "-"],
        capture_output=True, check=True, encoding="utf-8", timeout=30,
    )
    blocks = re.findall(r"\[CHAPTER\]\nTIMEBASE=(\d+)/(\d+)\nSTART=(\d+)\nEND=(-?\d+)\ntitle=([^\n]*)",
                        result.stdout)
    return [
        (int(start) * int(num) / int(den), int(end) * int(num) / int(den),
         re.sub(r"\\(.)", r"\1", title))
        for num, den, start, end, title in blocks
    ]


def _manifest(tmp_path, audio):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "audio": audio,
        "chapters": [
            {"title": "Mở đầu = chuyện #1; tiếng \\ Việt\\", "start": 0, "dur": 1.25},
            {"title": "Đoạn hai", "start": 1.25, "dur": 1.75},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    return manifest


def test_command_exports_text_json_and_roundtrips_m4b(tmp_path, capsys):
    from conftest import write_wav

    ffmpeg = _ffmpeg_or_skip()
    audio = tmp_path / "Tiếng Việt.wav"
    write_wav(audio, seconds=3)
    manifest = _manifest(tmp_path, audio.name)
    out = tmp_path / "out"
    assert cli.main(["chapters", "--manifest", str(manifest), "--out-dir", str(out),
                     "--m4b", "--json"]) == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1
    result = json.loads(captured.out)
    assert result["ok"] and result["chapter_count"] == 2
    assert (out / "chapters.txt").read_text(encoding="utf-8").splitlines() == [
        "00:00:00 Mở đầu = chuyện #1; tiếng \\ Việt\\", "00:00:01 Đoạn hai",
    ]
    rows = json.loads((out / "chapters.json").read_text(encoding="utf-8"))
    assert [row["start"] for row in rows] == [0, 1.25]
    assert "INDEX 01 00:01:18" in (out / "chapters.cue").read_text(encoding="utf-8")
    marks = _read_m4b(out / "chapters.m4b", ffmpeg)
    assert [title for _, _, title in marks] == [row["title"] for row in rows]
    assert [start for start, _, _ in marks] == pytest.approx([0, 1.25], abs=0.05)
    assert [end for _, end, _ in marks] == pytest.approx([1.25, 3], abs=0.05)


@pytest.mark.parametrize("third_start", [27.75, 34.5])
def test_manifest_lead_in_roundtrips_m4b_but_youtube_starts_at_zero(tmp_path, third_start):
    from conftest import write_wav

    ffmpeg = _ffmpeg_or_skip()
    audio = tmp_path / "Truyện.wav"
    write_wav(audio, seconds=60)
    rows = [
        {"title": "Chương đầu", "start": 7, "dur": 10.25},
        {"title": "Chương kế", "start": 17.25, "dur": third_start - 17.25},
        {"title": "Chương cuối", "start": third_start, "dur": 51.75 - third_start},
    ]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"audio": audio.name, "chapters": rows}), encoding="utf-8")
    out = tmp_path / "out"

    assert cli.main(["chapters", "--manifest", str(manifest), "--out-dir", str(out), "--m4b"]) == 0

    assert _read_m4b(out / "chapters.m4b", ffmpeg) == [
        (7, 17.25, "Chương đầu"),
        (17.25, third_start, "Chương kế"),
        (third_start, 51.75, "Chương cuối"),
    ]
    assert json.loads((out / "chapters.json").read_text(encoding="utf-8")) == rows
    assert (out / "chapters.txt").read_text(encoding="utf-8").splitlines() == [
        "00:00:00 Chương đầu", "00:00:17 Chương kế", f"00:00:{int(third_start)} Chương cuối",
    ]
    assert "INDEX 01 00:07:00" in (out / "chapters.cue").read_text(encoding="utf-8")


def test_single_delayed_chapter_is_exported(tmp_path):
    from conftest import write_wav

    ffmpeg = _ffmpeg_or_skip()
    audio = tmp_path / "intro.wav"
    write_wav(audio, seconds=12)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "audio": audio.name,
        "chapters": [{"title": "Một chương", "start": 7, "dur": 2}],
    }), encoding="utf-8")
    out = tmp_path / "out"

    assert cli.main(["chapters", "--manifest", str(manifest), "--out-dir", str(out), "--m4b"]) == 0
    assert _read_m4b(out / "chapters.m4b", ffmpeg) == [(7, 9, "Một chương")]


@pytest.mark.parametrize(("first", "second", "last_end", "fragments"), [
    (0, 17250, 30000, ("chương 1", "START", "7.000", "0.000")),
    (7000, 17251, 30000, ()),
    (7000, 17252, 30000, ("chương 2", "START", "17.250", "17.252")),
    (7000, 17250, 29999, ()),
    (7000, 17250, 29998, ("chương 2", "END", "30.000", "29.998")),
    (7000, None, 30000, ("2 chương", "1 chương")),
])
def test_m4b_readback_checks_timing_before_publish(tmp_path, capsys, monkeypatch,
                                                    first, second, last_end, fragments):
    from conftest import write_wav

    ffmpeg = _ffmpeg_or_skip()
    audio = tmp_path / "intro.wav"
    write_wav(audio, seconds=35)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "audio": audio.name,
        "chapters": [
            {"title": "Mở đầu", "start": 7, "dur": 10.25},
            {"title": "Chương hai", "start": 17.25, "dur": 12.75},
        ],
    }), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    old = {f"chapters.{ext}": f"previous {ext}".encode() for ext in ("txt", "json", "m4b", "cue")}
    for name, previous in old.items():
        (out / name).write_bytes(previous)

    metadata = f";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART={first}\nEND=17250\n"
    if second is not None:
        metadata += f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={second}\nEND={last_end}\n"
    version = subprocess.check_output([ffmpeg, "-version"]).splitlines()[0].decode("utf-8")
    real_run = subprocess.run
    attempts = []

    def override_readback(args, *extra, **kwargs):
        if args[-3:] == ["-f", "ffmetadata", "-"]:
            staged = Path(args[args.index("-i") + 1])
            assert args[0] == ffmpeg and staged.parent.parent == out.resolve() and staged.is_file()
            attempts.append(staged)
            return subprocess.CompletedProcess(args, 0, stdout=metadata.encode("utf-8"), stderr=b"")
        return real_run(args, *extra, **kwargs)

    monkeypatch.setattr(subprocess, "run", override_readback)
    code = cli.main(["chapters", "--manifest", str(manifest), "--out-dir", str(out), "--m4b", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert code == (1 if fragments else 0)
    assert len(attempts) == 1
    if fragments:
        assert not result["ok"] and result["code"] == 1
        assert all(fragment in result["error"] for fragment in (*fragments, version))
        assert {item.name: item.read_bytes() for item in out.iterdir()} == old
    else:
        assert result["ok"] and result["chapter_count"] == 2
        assert (out / "chapters.m4b").read_bytes() != old["chapters.m4b"]


def test_directory_chapters_use_decoded_sample_counts(tmp_path, capsys):
    import wave

    ffmpeg = _ffmpeg_or_skip()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    # Tạo file theo thứ tự ngược, sample rate khác nhau và mốc nhãn cố ý khác số mẫu.
    for name, rate, samples in [("02.wav", 24000, 24000), ("01.wav", 16000, 18200)]:
        with wave.open(str(audio_dir / name), "wb") as target:
            target.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            target.writeframes(b"\0\0" * samples)
    (audio_dir / "chapters.txt").write_text(
        "00:00:00 Một\n00:01:00 Hai\n", encoding="utf-8",
    )
    out = tmp_path / "out"
    assert cli.main(["chapters", "--audio-dir", str(audio_dir), "--out-dir", str(out),
                     "--m4b", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["chapter_count"] == 2
    rows = json.loads((out / "chapters.json").read_text(encoding="utf-8"))
    assert rows[0]["dur"] == pytest.approx(1.1375, abs=1 / 48000)
    assert rows[1]["start"] == rows[0]["dur"]
    assert rows[1]["dur"] == pytest.approx(1.0, abs=1 / 48000)
    marks = _read_m4b(out / "chapters.m4b", ffmpeg)
    assert [title for _, _, title in marks] == ["Một", "Hai"]
    assert [start for start, _, _ in marks] == pytest.approx([0, 1.1375], abs=0.05)


def test_command_exports_text_without_loading_audio(tmp_path, capsys):
    manifest = _manifest(tmp_path, "archived.mp3")
    out = tmp_path / "out"
    assert cli.main(["chapters", "--manifest", str(manifest), "--out-dir", str(out),
                     "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["chapter_count"] == 2
    assert {file.name for file in out.iterdir()} == {"chapters.txt", "chapters.json"}


def test_bad_manifest_returns_one_json_line_with_code_2(tmp_path, capsys):
    manifest = tmp_path / "bad.json"
    manifest.write_text("{", encoding="utf-8")
    out = tmp_path / "out"
    assert cli.main(["chapters", "--manifest", str(manifest), "--out-dir", str(out),
                     "--json"]) == 2
    stdout = capsys.readouterr().out
    assert len(stdout.splitlines()) == 1
    assert json.loads(stdout)["code"] == 2 and not out.exists()


@pytest.mark.parametrize(("start", "message"), [
    (0, "Chương 2 phải bắt đầu sau mốc bắt đầu của chương 1"),
    (1.249, "Chương 2 chồng lấn với chương 1"),
])
def test_manifest_rejects_invalid_chapter_order_or_overlap(tmp_path, capsys, start, message):
    manifest = _manifest(tmp_path, "archived.mp3")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["chapters"][1]["start"] = start
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "out"

    assert cli.main(["chapters", "--manifest", str(manifest), "--out-dir", str(out),
                     "--json"]) == 2
    captured = capsys.readouterr()
    assert message in json.loads(captured.out)["error"]
    assert message in captured.err
    assert not out.exists()


def test_manifest_accepts_adjacent_decimal_boundaries():
    chapters = _chapters_module()
    _, marks = chapters.parse_manifest(json.dumps({
        "audio": "episode.wav",
        "chapters": [
            {"title": "Một", "start": 0, "dur": 0.1},
            {"title": "Hai", "start": 0.1, "dur": 0.2},
            {"title": "Ba", "start": 0.3, "dur": 1},
        ],
    }))
    assert [chapter.start for chapter in marks] == [0, 0.1, 0.3]


@pytest.mark.parametrize("encode", [False, True])
def test_chapters_past_audio_end_warns_without_aborting(tmp_path, capsys, encode):
    from conftest import write_wav

    _ffmpeg_or_skip()
    audio = tmp_path / "episode.wav"
    write_wav(audio, seconds=2)
    manifest = _manifest(tmp_path, audio.name)
    out = tmp_path / "out"
    args = ["chapters", "--manifest", str(manifest), "--out-dir", str(out), "--json"]
    if encode:
        args.append("--m4b")

    assert cli.main(args) == 0
    result = capsys.readouterr()
    assert json.loads(result.out)["chapter_count"] == 2
    assert "Cảnh báo: chương 2 kết thúc ở 3.000 s, vượt độ dài audio 2.000 s" in result.err
    assert (out / "chapters.json").is_file()
    assert (out / "chapters.m4b").is_file() == encode


def test_encoder_failure_keeps_previous_export(tmp_path, capsys):
    _ffmpeg_or_skip()
    manifest = _manifest(tmp_path, "bad.wav")
    (tmp_path / "bad.wav").write_bytes(b"invalid waveform")
    out = tmp_path / "out"
    out.mkdir()
    old = out / "chapters.txt"
    old.write_text("previous export", encoding="utf-8")
    assert cli.main(["chapters", "--manifest", str(manifest), "--out-dir", str(out),
                     "--m4b", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == 1
    assert set(out.iterdir()) == {old} and old.read_text(encoding="utf-8") == "previous export"


def test_publish_failure_restores_previous_export(tmp_path, capsys, monkeypatch):
    manifest = _manifest(tmp_path, "archived.mp3")
    out = tmp_path / "out"
    out.mkdir()
    old = {out / "chapters.txt": "previous text", out / "chapters.json": "previous json"}
    for path, content in old.items():
        path.write_text(content, encoding="utf-8")
    replace = Path.replace

    def locked(path, target):
        if Path(target) == out / "chapters.json" and path.parent.name != "previous":
            raise PermissionError("destination open by another process")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", locked)
    assert cli.main(["chapters", "--manifest", str(manifest), "--out-dir", str(out),
                     "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == 1
    assert {path: path.read_text(encoding="utf-8") for path in out.iterdir()} == old


def test_ctrl_c_returns_code_2(monkeypatch, tmp_path, capsys):
    chapters = _chapters_module()

    def interrupted(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(chapters, "export_chapters", interrupted, raising=False)
    assert cli.main(["chapters", "--manifest", str(tmp_path / "any.json"),
                     "--out-dir", str(tmp_path / "out"), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == 2
