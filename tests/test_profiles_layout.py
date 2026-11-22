"""Bố cục trạm kiểu mới `profiles/<tên>/voice/` + lùi kho phẳng cũ (TK2 voice-station-restructure).

Mọi test dùng trạm tạm (VOICE_STATION trỏ tmp_path) — không đọc trạm thật của máy.
"""
import json
import os
import unicodedata

import pytest

from conftest import last_json
from voice_studio import _env, cli, profiles


def _clip(d, name, text="lời mẫu"):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.wav").write_bytes(b"RIFF" + name.encode("utf-8"))
    (d / f"{name}.txt").write_text(text, encoding="utf-8")


@pytest.fixture
def st(tmp_path, monkeypatch):
    s = tmp_path / "station"
    s.mkdir()
    monkeypatch.setenv("VOICE_STATION", str(s))
    profiles.set_voices_dir(None)
    profiles.clear_cache()
    yield s
    profiles.set_voices_dir(None)
    profiles.clear_cache()


def new_voice(st, name, **kw):
    _clip(st / "profiles" / name / "voice", name, **kw)


def old_voice(st, name, **kw):
    _clip(st / "omnivoice" / "voices", name, **kw)


# ── đọc hai kiểu, kiểu mới thắng ─────────────────────────────────────────────────────

def test_reads_new_layout(st):
    new_voice(st, "alpha")
    assert profiles.layout() == "new"
    assert profiles.list_profiles() == ["alpha"]
    wav, txt = profiles._paths("alpha")
    assert wav == str(st / "profiles" / "alpha" / "voice" / "alpha.wav")
    assert profiles.voice_dir("alpha") == str(st / "profiles" / "alpha" / "voice")


def test_falls_back_to_legacy_flat_store(st):
    old_voice(st, "beta")
    assert profiles.layout() == "legacy"
    assert profiles.list_profiles() == ["beta"]
    assert profiles._paths("beta")[0] == str(st / "omnivoice" / "voices" / "beta.wav")


def test_union_of_both_new_wins_on_duplicate(st):
    new_voice(st, "alpha", text="MỚI")
    old_voice(st, "alpha", text="CŨ")
    old_voice(st, "beta")
    assert profiles.list_profiles() == ["alpha", "beta"]
    recs = {r["name"]: r for r in profiles.profile_records()}
    assert recs["alpha"]["kind"] == "new" and recs["beta"]["kind"] == "legacy"
    assert profiles._paths("alpha")[0].endswith(os.path.join("profiles", "alpha", "voice", "alpha.wav"))
    txt = profiles._paths("alpha")[1]
    assert open(txt, encoding="utf-8").read() == "MỚI"


def test_listing_skips_underscore_dot_and_archive(st):
    new_voice(st, "alpha")
    new_voice(st, "_example")
    new_voice(st, ".hidden")
    new_voice(st, "archive")                 # `archive` không bao giờ là một giọng
    (st / "profiles" / "no-voice" / "raw").mkdir(parents=True)     # có thư mục nhưng chưa có clip
    (st / "profiles" / "_default.txt").write_text("alpha", encoding="utf-8")   # file, không phải profile
    assert profiles.list_profiles() == ["alpha"]


def test_names_match_nfc_on_directories(st):
    nfd = unicodedata.normalize("NFD", "giọng-tiên")
    nfc = unicodedata.normalize("NFC", "giọng-tiên")
    assert nfd != nfc
    _clip(st / "profiles" / nfd / "voice", nfd)
    assert profiles.list_profiles() == [nfc]
    wav = profiles._paths(nfc)[0]
    assert os.path.isfile(wav) and nfd in wav            # mở đúng thư mục NFD thật trên đĩa, không đổi tên
    assert profiles._exists(nfc)


def test_marker_count_in_records(st):
    new_voice(st, "alpha")
    (st / "profiles" / "alpha" / "voice" / "alpha.profile.json").write_text(
        json.dumps({"name": "alpha", "variants": {"a": {}, "b": {}}}), encoding="utf-8")
    assert profiles.profile_records()[0]["markers"] == 2


# ── ghi: kiểu mới khi trạm đã có profiles/, ngược lại kiểu cũ ───────────────────────────

def test_new_profile_goes_to_new_layout_when_station_has_profiles(st, tmp_path):
    (st / "profiles").mkdir()
    src = tmp_path / "src.wav"
    _write_real_wav(src)
    profiles.save_profile_from_wav(str(src), "lời", "gamma", set_as_default=False)
    assert (st / "profiles" / "gamma" / "voice" / "gamma.wav").is_file()
    assert (st / "profiles" / "gamma" / "voice" / "gamma.txt").read_text(encoding="utf-8") == "lời"
    assert not (st / "omnivoice").exists()


def test_new_profile_goes_to_legacy_when_station_has_no_profiles(st, tmp_path):
    src = tmp_path / "src.wav"
    _write_real_wav(src)
    profiles.save_profile_from_wav(str(src), "lời", "gamma", set_as_default=False)
    assert (st / "omnivoice" / "voices" / "gamma.wav").is_file()
    assert not (st / "profiles").exists()


def test_existing_legacy_profile_is_rewritten_in_place(st, tmp_path):
    (st / "profiles").mkdir()
    old_voice(st, "beta")
    src = tmp_path / "src.wav"
    _write_real_wav(src)
    profiles.save_profile_from_wav(str(src), "mới", "beta", set_as_default=False)
    assert (st / "omnivoice" / "voices" / "beta.txt").read_text(encoding="utf-8") == "mới"
    assert not (st / "profiles" / "beta").exists()


def test_pinned_flat_store_wins_for_new_profiles(st, tmp_path, monkeypatch):
    (st / "profiles").mkdir()
    flat = tmp_path / "flat"
    monkeypatch.setenv("VOICES_DIR", str(flat))
    src = tmp_path / "src.wav"
    _write_real_wav(src)
    profiles.save_profile_from_wav(str(src), "lời", "gamma", set_as_default=False)
    assert (flat / "gamma.wav").is_file() and not (st / "profiles" / "gamma").exists()


@pytest.mark.parametrize("bad", ["../x", "a/b", "_x", ".x", "archive", "a:b"])
def test_new_layout_rejects_unsafe_profile_names(st, bad):
    (st / "profiles").mkdir()
    from voice_studio.contract import ContractError
    with pytest.raises(ContractError):
        profiles.voice_dir(bad)


def _write_real_wav(path):
    import numpy as np
    import soundfile as sf
    sf.write(str(path), (0.1 * np.sin(np.arange(2400) / 7)).astype("float32"), 24000)


# ── mặc định ─────────────────────────────────────────────────────────────────────────────

def test_default_reads_station_json_first_in_new_layout(st):
    new_voice(st, "alpha")
    new_voice(st, "beta")
    (st / "profiles" / "_default.txt").write_text("alpha", encoding="utf-8")
    (st / "station.json").write_text(json.dumps({"default_profile": "beta"}), encoding="utf-8")
    assert profiles.get_default() == "beta"                       # station.json thắng
    (st / "station.json").write_text(json.dumps({"default_profile": None}), encoding="utf-8")
    assert profiles.get_default() == "alpha"                      # rồi tới profiles/_default.txt


def test_set_default_updates_the_winning_source(st):
    new_voice(st, "alpha")
    new_voice(st, "beta")
    profiles.set_default("alpha")
    assert (st / "profiles" / "_default.txt").read_text(encoding="utf-8") == "alpha"
    (st / "station.json").write_text(json.dumps({"default_profile": "alpha", "x": 1}), encoding="utf-8")
    profiles.set_default("beta")
    assert json.loads((st / "station.json").read_text(encoding="utf-8")) == {"default_profile": "beta", "x": 1}
    assert profiles.get_default() == "beta"


def test_default_legacy_order_unchanged(st):
    old_voice(st, "alpha")
    old_voice(st, "beta")
    (st / "omnivoice" / "voices" / "_default.txt").write_text("beta", encoding="utf-8")
    (st / "station.json").write_text(json.dumps({"default_profile": "alpha"}), encoding="utf-8")
    assert profiles.get_default() == "beta"                       # trạm cũ: _default.txt vẫn thắng


# ── lab_dir, candidates tương đối, bgm_dir ────────────────────────────────────────────

def test_lab_dir_new_layout(st):
    (st / "profiles").mkdir()
    assert _env.lab_dir("alpha", "candidates.json") == str(st / "profiles" / "alpha" / "lab" / "candidates.json")


def test_lab_dir_legacy_station_unchanged(st):
    assert _env.lab_dir("alpha") == str(st / "out" / "lab" / "alpha")


def test_lab_dir_keeps_old_workspace_with_one_line_warning(st, capsys):
    (st / "profiles").mkdir()
    (st / "out" / "lab" / "alpha").mkdir(parents=True)
    assert _env.lab_dir("alpha", "x.json") == str(st / "out" / "lab" / "alpha" / "x.json")
    _env.lab_dir("alpha")
    err = capsys.readouterr().err
    assert err.count("kiểu cũ") == 1                              # nhắc đúng MỘT lần
    (st / "profiles" / "alpha" / "lab").mkdir(parents=True)       # có chỗ mới thì chỗ mới thắng
    assert _env.lab_dir("alpha") == str(st / "profiles" / "alpha" / "lab")


def test_candidates_use_relative_paths_and_fallback_to_clips(st, tmp_path):
    from voice_studio.lab import build, mine
    lab = tmp_path / "lab"
    (lab / "clips").mkdir(parents=True)
    clip = lab / "clips" / "cao_1.wav"
    clip.write_bytes(b"x")
    assert mine._rel(str(clip), str(lab)) == "clips/cao_1.wav"
    assert build.clip_path(str(lab), "clips/cao_1.wav") == str(clip)            # tương đối
    gone = "C:\\May\\Cu\\lab\\clips\\cao_1.wav" if os.name == "nt" else "/may/cu/lab/clips/cao_1.wav"
    assert build.clip_path(str(lab), gone) == str(clip)                         # tuyệt đối cũ không còn → clips/
    assert build.clip_path(str(lab), str(clip)) == str(clip)                    # tuyệt đối còn thì giữ


def test_load_candidates_rewrites_paths(st):
    from voice_studio.lab import build
    (st / "profiles").mkdir()
    lab = st / "profiles" / "alpha" / "lab"
    (lab / "clips").mkdir(parents=True)
    (lab / "clips" / "m_1.wav").write_bytes(b"x")
    (lab / "candidates.json").write_text(json.dumps({"clusters": {"m": {"candidates": [
        {"rank": 1, "wav": "D:/cu/clips/m_1.wav"}]}}}), encoding="utf-8")
    got = build.load_candidates("alpha")
    assert got["clusters"]["m"]["candidates"][0]["wav"] == str(lab / "clips" / "m_1.wav")


def test_lab_build_add_with_every_marker_present_is_a_clean_noop(st, monkeypatch, capsys):
    """Fable PS2: `lab build --mode add` khi mọi marker đã có từng vỡ FileNotFoundError ...\\lab\\_stage."""
    from voice_studio import engine
    from voice_studio.lab import build
    new_voice(st, "alpha")
    vd = st / "profiles" / "alpha" / "voice"
    manifest = {"name": "alpha", "neutral": "m", "variants": {"m": {"wav": "alpha.variants/m.wav"}}}
    (vd / "alpha.profile.json").write_text(json.dumps(manifest), encoding="utf-8")
    lab = st / "profiles" / "alpha" / "lab"
    lab.mkdir(parents=True)
    (lab / "candidates.json").write_text(json.dumps(
        {"neutral": "m", "clusters": {"m": {"size": 3, "centroid_pte": 0.0, "candidates": []}}}), encoding="utf-8")
    monkeypatch.setattr(engine, "load", lambda *a, **k: object())
    before = (vd / "alpha.profile.json").read_bytes()
    assert build.main(["--name", "alpha", "--mode", "add", "--no-demo"]) is None       # không SystemExit, không traceback
    out = capsys.readouterr().out
    assert "không có marker mới" in out
    assert not (lab / "_stage").exists()
    assert (vd / "alpha.profile.json").read_bytes() == before                           # manifest không bị ghi lại


def test_bgm_dir_defaults(st):
    assert _env.bgm_dir() == str(st / "music" / "library")                      # trạm trống: mặc định mới
    (st / "assets" / "bgm").mkdir(parents=True)
    assert _env.bgm_dir() == str(st / "assets" / "bgm")                         # trạm cũ chưa có music/
    (st / "music").mkdir()
    assert _env.bgm_dir() == str(st / "music" / "library")                      # có music/ thì kiểu mới
    (st / "station.json").write_text(json.dumps({"bgm_dir": "kho/nhac"}), encoding="utf-8")
    assert _env.bgm_dir() == str(st / "kho" / "nhac")                           # station.json thắng
    os.environ["VOICE_BGM_DIR"] = str(st / "bien")
    try:
        assert _env.bgm_dir() == str(st / "bien")                               # biến thắng tất
    finally:
        del os.environ["VOICE_BGM_DIR"]


# ── vlab đọc manifest + biến thể trong thư mục voice/ ─────────────────────────────────

def test_vlab_manifest_lives_next_to_the_clip(st):
    from voice_studio.lab import vlab
    new_voice(st, "alpha")
    vd = st / "profiles" / "alpha" / "voice"
    (vd / "alpha.variants").mkdir()
    (vd / "alpha.variants" / "a.wav").write_bytes(b"x")
    (vd / "alpha.profile.json").write_text(json.dumps(
        {"name": "alpha", "neutral": "a", "variants": {"a": {"wav": "alpha.variants/a.wav"}}}), encoding="utf-8")
    prof = vlab.load_profile("alpha")
    assert prof["neutral"] == "a"
    assert vlab._variant_paths(prof, "a")[1] == str(vd / "alpha.variants" / "a.wav")


# ── CLI `profiles list --json` ───────────────────────────────────────────────────────

def test_profiles_list_json(st, capsys):
    new_voice(st, "alpha")
    old_voice(st, "beta")
    (st / "profiles" / "_default.txt").write_text("alpha", encoding="utf-8")
    assert cli.main(["profiles", "list", "--json"]) == 0
    res = last_json(capsys.readouterr().out)
    assert res["ok"] is True and res["layout"] == "new" and res["default"] == "alpha"
    by = {p["name"]: p for p in res["profiles"]}
    assert by["alpha"]["kind"] == "new" and by["alpha"]["default"] is True
    assert by["beta"]["kind"] == "legacy" and by["beta"]["default"] is False
    assert set(by["alpha"]) == {"name", "kind", "markers", "default", "voice_dir"}
    assert res["profiles_dir"] == str(st / "profiles")
    assert res["voices_dir"] == str(st / "omnivoice" / "voices")


def test_profiles_list_human_table_goes_to_stdout(st, capsys):
    new_voice(st, "alpha")
    assert cli.main(["profiles", "list"]) == 0
    assert "alpha" in capsys.readouterr().out


def test_profiles_list_without_station_is_exit_3(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("VOICE_STATION", raising=False)
    assert cli.main(["profiles", "list", "--json"]) == 3
    assert last_json(capsys.readouterr().out)["ok"] is False


def test_profiles_command_is_registered():
    assert "profiles" in cli.COMMANDS and "station" in cli.COMMANDS
