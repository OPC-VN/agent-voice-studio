"""Lớp tương thích tên cũ (`compat`) + 8 tool MCP, với engine GIẢ.

`compat` là thứ shim ở trạm sẽ `import *` — chữ ký cũ phải giữ nguyên, kể cả hành vi lùi về
`instruct` khi không có profile. MCP: tool gọi thẳng như hàm; `build_server()` đăng ký đủ 8 tool.
"""
import os
import shutil
import subprocess
import sys
import types

import pytest

from voice_studio import av, compat, engine, mcp_server, profiles

pytest.importorskip("numpy")
pytest.importorskip("soundfile")


# ── compat ─────────────────────────────────────────────────────────────────────────────

def test_compat_exports_legacy_names():
    for name in ("_get_model", "_synth", "_save", "_mux", "_mix_bgm", "_ffmpeg_exe",
                 "_video_duration", "normalize_rms"):
        assert name in compat.__all__ and callable(getattr(compat, name)), name
    assert compat.VOICE_OPTIONS is engine.VOICE_OPTIONS and compat.MODEL_ID == engine.MODEL_ID


def test_compat_exposes_subprocess_for_station_regression_gate():
    """Cổng hồi quy ở trạm vá `mcp_server.subprocess.run`; shim phải giải được tên đó.

    Engine đơn khối cũ `import subprocess` ở cấp module, nên `ov.subprocess` là một phần bề
    mặt mà pipeline đang dùng. Thiếu nó thì cổng canh sự cố 30/08 (file `.__tmp.wav` 21 MB →
    `git add -A` → object git hỏng) **chết câm**: AttributeError, không phải FAIL.
    """
    import subprocess as _sp
    assert compat.subprocess is _sp
    assert "subprocess" in compat.__all__


def test_legacy_subprocess_hook_still_catches_tmp_leak(tmp_path, monkeypatch):
    """Chạy y hệt cổng của trạm, nhưng qua `compat`: ffmpeg sập ⇒ lỗi nổi lên, không rò file tạm."""
    import subprocess as _sp

    import numpy as np
    monkeypatch.setattr(engine, "ffmpeg", lambda: "ffmpeg")   # không đòi ffmpeg thật trên CI
    out = str(tmp_path / "all.mp3")
    tmp = out[:-4] + ".__tmp.wav"

    def boom(*a, **k):
        raise _sp.CalledProcessError(1, "ffmpeg")

    real, compat.subprocess.run = compat.subprocess.run, boom
    try:
        with pytest.raises(_sp.CalledProcessError):
            compat._save(np.zeros(24000, dtype="float32"), out, 24000)
    finally:
        compat.subprocess.run = real
    assert not os.path.exists(tmp), "RÒ: .__tmp.wav còn sau khi ffmpeg lỗi"


def test_compat_synth_uses_named_profile(station, fake_engine):
    m = compat._get_model()
    assert m is fake_engine and compat._model is fake_engine
    a = compat._synth(m, "Xin chào", "Vietnamese", "female", 1.0, "demo")
    assert len(a) > 0
    assert fake_engine.calls[-1]["voice_clone_prompt"] is not None
    assert "instruct" not in fake_engine.calls[-1]


def test_compat_synth_falls_back_to_instruct_like_before(tmp_path, monkeypatch, fake_engine):
    """Hành vi CŨ có chủ đích: không profile nào ⇒ dùng instruct (API mới thì báo lỗi)."""
    monkeypatch.setenv("VOICE_STATION", str(tmp_path / "trong"))
    compat._synth(compat._get_model(), "x", "Vietnamese", "male, low pitch", 1.0, None)
    assert fake_engine.calls[-1]["instruct"] == "male, low pitch"


def test_compat_mux_and_mix_forward_to_av(monkeypatch):
    seen = []
    monkeypatch.setattr(av, "mux", lambda v, w, o, mode="fit", **k: seen.append(("mux", mode)))
    monkeypatch.setattr(av, "mix_bgm", lambda p, **k: seen.append(("mix", p)))
    compat._mux("v.mp4", "a.wav", "o.mp4", mode="shortest")
    compat._mix_bgm("o.mp4")
    assert seen == [("mux", "shortest"), ("mix", "o.mp4")]


def test_compat_normalize_rms_is_engine_normalize():
    import numpy as np
    a = (0.01 * np.ones(2000)).astype("float32")
    assert np.allclose(compat.normalize_rms(a), engine.normalize(a))


# ── MCP tools ──────────────────────────────────────────────────────────────────────────

def test_eight_tools_are_plain_documented_functions():
    assert len(mcp_server.TOOLS) == 8
    for name in mcp_server.TOOLS:
        fn = getattr(mcp_server, name)
        assert callable(fn) and (fn.__doc__ or "").strip(), name


def test_build_server_registers_all_tools(monkeypatch):
    registered = []

    class FastMCP:
        def __init__(self, name):
            self.name = name

        def tool(self):
            def deco(fn):
                registered.append(fn.__name__)
                return fn
            return deco
    pkg = types.ModuleType("mcp")
    srv = types.ModuleType("mcp.server")
    fm = types.ModuleType("mcp.server.fastmcp")
    fm.FastMCP = FastMCP
    for n, m in (("mcp", pkg), ("mcp.server", srv), ("mcp.server.fastmcp", fm)):
        monkeypatch.setitem(sys.modules, n, m)
    server = mcp_server.build_server()
    assert server.name == mcp_server.SERVER_NAME
    assert registered == list(mcp_server.TOOLS)


def test_synthesize_speech_with_profile(station, fake_engine, tmp_path):
    out = tmp_path / "a.wav"
    msg = mcp_server.synthesize_speech("Xin chào", str(out), voice_profile="demo")
    assert msg.startswith("OK") and "voice: demo" in msg and out.is_file()


def test_synthesize_speech_unknown_profile_is_error_not_other_voice(station, fake_engine, tmp_path):
    msg = mcp_server.synthesize_speech("x", str(tmp_path / "a.wav"), voice_profile="khong-co")
    assert msg.startswith("ERROR") and fake_engine.calls == []


def test_narrate_video_tool(station, fake_engine, tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"v")
    monkeypatch.setattr(av, "video_duration", lambda p: 2.0)
    monkeypatch.setattr(av, "mux", lambda v, w, o, mode="fit", **k: open(o, "wb").write(b"x"))
    msg = mcp_server.narrate_video(str(video), "x", str(tmp_path / "f.mp4"), voice_profile="demo")
    assert msg.startswith("OK — narrated") and "mode=fit" in msg
    assert not os.path.exists(str(tmp_path / "f.mp4") + ".__voice.wav")
    assert mcp_server.narrate_video(str(video), "x", "o.mp4", mode="loop").startswith("ERROR")


def test_clone_voice_tool(station, fake_engine, tmp_path):
    from conftest import write_wav
    ref = write_wav(tmp_path / "ref.wav")
    msg = mcp_server.clone_voice("x", str(tmp_path / "c.wav"), ref, "lời mẫu")
    assert msg.startswith("OK — cloned") and fake_engine.calls[-1]["ref_audio"] == ref
    assert mcp_server.clone_voice("x", "c.wav", str(tmp_path / "khong.wav")).startswith("ERROR")


@pytest.mark.parametrize("generation_fails", [False, True])
def test_clone_converts_mp3_reference_and_cleans_wav(
    fake_engine, tmp_path, monkeypatch, generation_fails,
):
    from pathlib import Path

    from conftest import write_wav

    source = write_wav(tmp_path / "ref.mp3")  # Nội dung WAV tổng hợp cho ffmpeg giả.
    converted = []

    def copy_ffmpeg(cmd, **kwargs):
        assert cmd[cmd.index("-i") + 1] == source
        assert cmd[cmd.index("-protocol_whitelist") + 1] == "file"
        formats = cmd[cmd.index("-format_whitelist") + 1].split(",")
        assert "mp3" in formats and "mov" in formats
        assert "concat" not in formats and "hls" not in formats
        converted.append(Path(cmd[-1]))
        shutil.copyfile(source, converted[-1])
        return subprocess.CompletedProcess(cmd, 0)

    generate = fake_engine.generate

    def model_generate(**kwargs):
        ref = Path(kwargs["ref_audio"])
        assert ref.suffix == ".wav" and ref.is_file()
        assert converted == [ref]
        return generate(**kwargs)

    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setattr(engine, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(subprocess, "run", copy_ffmpeg)
    monkeypatch.setattr(fake_engine, "generate", model_generate)
    fake_engine.fail = generation_fails
    output = str(tmp_path / "out.wav")

    if generation_fails:
        with pytest.raises(RuntimeError, match="CUDA out of memory"):
            mcp_server.clone_voice("x", output, source)
    else:
        assert mcp_server.clone_voice("x", output, source).startswith("OK")
    assert not converted[0].parent.exists()


def test_clone_returns_ffmpeg_stderr_tail_and_cleans_temp(tmp_path, monkeypatch):
    from pathlib import Path

    source = tmp_path / "ref.mp3"
    source.touch()
    outputs = []
    stderr = "phần đầu " + "x" * 600 + " đuôi lỗi giải mã"

    def failed_decode(cmd, **kwargs):
        outputs.append(Path(cmd[-1]))
        raise subprocess.CalledProcessError(1, cmd, stderr=stderr.encode("utf-8"))

    def load_never_called():
        pytest.fail("Không nạp engine khi chuyển tham chiếu thất bại")

    monkeypatch.setattr(engine, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(engine, "load", load_never_called)
    monkeypatch.setattr(subprocess, "run", failed_decode)
    result = mcp_server.clone_voice("x", str(tmp_path / "out.wav"), str(source))

    assert result == f"ERROR: ffmpeg failed: {stderr[-500:]}"
    assert len(outputs) == 1 and not outputs[0].parent.exists()


@pytest.mark.parametrize("error", [FileNotFoundError, RuntimeError])
def test_clone_returns_error_when_ffmpeg_is_unavailable(tmp_path, monkeypatch, error):
    source = tmp_path / "ref.mp3"
    source.touch()

    def missing_ffmpeg():
        raise error("không tìm thấy FFmpeg")

    monkeypatch.setattr(engine, "ffmpeg", missing_ffmpeg)
    assert mcp_server.clone_voice("x", str(tmp_path / "out.wav"), str(source)) == (
        "ERROR: ffmpeg failed: không tìm thấy FFmpeg"
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="cần FFmpeg thật trên PATH")
@pytest.mark.parametrize(("suffix", "codec"), [("m4a", "aac"), ("ogg", "flac")])
def test_extract_local_audio_with_real_ffmpeg(tmp_path, suffix, codec):
    import soundfile as sf

    from voice_studio import make_profile

    source = tmp_path / f"ref.{suffix}"
    target = tmp_path / "ref.wav"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=0.25", "-c:a", codec, str(source)],
        check=True, capture_output=True, timeout=15,
    )

    assert make_profile.extract(str(source), str(target), local_only=True) == str(target)
    info = sf.info(target)
    assert (info.format, info.samplerate, info.channels) == ("WAV", 24000, 1)
    assert info.duration == pytest.approx(0.25, abs=0.06)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="cần FFmpeg thật trên PATH")
def test_extract_local_rejects_http_playlist_with_real_ffmpeg(tmp_path):
    from voice_studio import make_profile

    playlist = tmp_path / "ref.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\n"
        "http://127.0.0.1:9/example.ts\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    target = tmp_path / "ref.wav"
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        make_profile.extract(str(playlist), str(target), local_only=True)

    assert b"not on whitelist" in exc_info.value.stderr.lower()
    assert not target.exists()


def test_profile_management_tools(station, fake_engine, tmp_path):
    from conftest import write_wav
    assert mcp_server.list_voice_profiles()["profiles"] == ["demo", "other"]
    assert mcp_server.set_default_voice("khong-co").startswith("ERROR")
    assert mcp_server.set_default_voice("other").startswith("OK")
    assert mcp_server.list_voice_profiles()["default"] == "other"
    ref = write_wav(tmp_path / "moi.wav")
    assert mcp_server.make_voice_profile("moi", ref_audio=ref).startswith("ERROR")   # thiếu lời
    msg = mcp_server.make_voice_profile("moi", ref_audio=ref, ref_text="Lời.", set_default=False)
    assert msg.startswith("OK") and "moi" in profiles.list_profiles()
    assert mcp_server.make_voice_profile("frozen", instruct="female, low pitch").startswith("OK")
    assert mcp_server.make_voice_profile("rong").startswith("ERROR")


def test_options_and_status_without_torch(station, monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    opts = mcp_server.list_voice_options()
    assert set(opts["valid_keywords"]) == {"gender", "age", "pitch", "accent"}
    st = mcp_server.get_status()
    assert st["model_loaded"] is False and str(st["device_available"]).startswith("unavailable")
