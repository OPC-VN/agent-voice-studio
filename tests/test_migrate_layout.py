"""`voice-studio station migrate-layout`: dời trạm kiểu cũ sang cây profiles/ + music/ (dry-run · apply · undo).

Trạm tạm trong tmp_path, HOME giả (conftest) — không đọc trạm thật.
"""
import hashlib
import json
import os
import shutil
import subprocess

import pytest

from conftest import last_json
from voice_studio import _env, cli, layout, profiles


def snapshot(root):
    """{đường tương đối: sha256 | None (thư mục)} của cả cây, trừ .git và sổ."""
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in (".git", layout.LEDGER_DIR)]
        rel = os.path.relpath(dp, root).replace(os.sep, "/")
        if rel != ".":
            out[rel + "/"] = None
        for n in fn:
            p = os.path.join(dp, n)
            out[os.path.relpath(p, root).replace(os.sep, "/")] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def put(root, rel, data="x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return p


@pytest.fixture
def old(tmp_path, monkeypatch):
    """Trạm kiểu cũ đủ loại thứ: giọng đơn, giọng đa sắc thái, sổ tay organize, kho nghỉ hưu, bgm, lab, thứ ngoài hợp đồng."""
    st = tmp_path / "station"
    v = "omnivoice/voices/"
    for n in ("narrator", "solo"):
        put(st, f"{v}{n}.wav", f"wav-{n}")
        put(st, f"{v}{n}.txt", f"lời {n}")
        put(st, f"{v}{n}.prompt.pt", "cache")
    put(st, f"{v}multi.wav", "wav-multi")
    put(st, f"{v}multi.txt", "lời multi")
    put(st, f"{v}multi.profile.json", json.dumps({"name": "multi", "variants": {"a": {"wav": "multi.variants/a.wav"}}}))
    put(st, f"{v}multi.variants/a.wav", "wav-a")
    put(st, f"{v}narrator/README.md", "# sổ tay")
    put(st, f"{v}narrator/ref.wav", "ref")
    put(st, f"{v}narrator/demo/d.mp3", "demo")
    put(st, f"{v}_default.txt", "narrator")
    put(st, f"{v}_layout.json", "{}")
    put(st, f"{v}_archive/2026-01-01/old.wav", "old")
    put(st, f"{v}_example/README.md", "mẫu")
    put(st, "assets/bgm/bgm-library.json", "{}")
    put(st, "assets/bgm/calm.mp3", "mp3")
    put(st, "data/voicelab/lab/narrator/candidates.json", json.dumps({"name": "narrator"}))
    put(st, "data/voicelab/lab/narrator/clips/c.wav", "clip")
    put(st, "raw/Nguon/a.m4a", "raw")
    put(st, "out/narrator/report.md", "rp")
    put(st, "omnivoice/truyen-out/x.mp3", "t")
    put(st, "station.json", json.dumps({"contract": "1.0.0", "mode": "separate", "default_profile": "narrator",
                                        "engine_dir": "omnivoice", "bgm_dir": "assets/bgm", "keep": 1}))
    monkeypatch.setenv("VOICE_STATION", str(st))
    monkeypatch.setenv("VOICE_STUDIO_WORK", str(st / "data" / "voicelab"))
    profiles.set_voices_dir(None)
    profiles.clear_cache()
    yield st
    profiles.clear_cache()


def run(args, capsys):
    code = cli.main(["station", "migrate-layout", *args, "--json"])
    cap = capsys.readouterr()
    return code, last_json(cap.out), cap.err


def git(st, *args):
    return subprocess.run(["git", "-C", str(st), *args], capture_output=True, text=True, encoding="utf-8")


need_git = pytest.mark.skipif(not shutil.which("git"), reason="cần git")


# ── dry-run ──────────────────────────────────────────────────────────────────────────

def test_dry_run_is_default_and_touches_nothing(old, capsys):
    before = snapshot(old)
    code, res, err = run([], capsys)
    assert code == 0 and res["action"] == "dry-run"
    assert snapshot(old) == before and not (old / layout.LEDGER_DIR).exists()
    assert "XEM TRƯỚC" in err
    moves = {m["src"]: m["dst"] for m in res["moves"]}
    assert moves["omnivoice/voices/narrator.wav"] == "profiles/narrator/voice/narrator.wav"
    assert moves["omnivoice/voices/multi.variants"] == "profiles/multi/voice/multi.variants"
    assert moves["omnivoice/voices/narrator/README.md"] == "profiles/narrator/README.md"
    assert moves["omnivoice/voices/narrator/demo"] == "profiles/narrator/products/demo"
    assert moves["omnivoice/voices/_default.txt"] == "profiles/_default.txt"
    assert moves["assets/bgm"] == "music/library"
    assert moves["data/voicelab/lab/narrator"] == "profiles/narrator/lab"
    assert moves["omnivoice/voices/_archive"].startswith("archive/") and moves["omnivoice/voices/_archive"].endswith("-voices")
    assert res["station_json"]["changed"] is True
    man = {m["path"]: m["hint"] for m in res["manual"]}
    assert "raw/Nguon" in man and "profiles/" in man["raw/Nguon"]
    assert "omnivoice/truyen-out" in man and "out/narrator" in man
    assert "omnivoice/voices/_example" in man
    assert res["conflicts"] == []


def test_explicit_dry_run_flag(old, capsys):
    assert run(["--dry-run"], capsys)[1]["action"] == "dry-run"


# ── apply ────────────────────────────────────────────────────────────────────────────

def test_apply_builds_the_new_tree_and_loader_reads_it(old, capsys):
    code, res, _ = run(["--apply"], capsys)
    assert code == 0 and res["action"] == "apply"
    for rel in ("profiles/narrator/voice/narrator.wav", "profiles/narrator/voice/narrator.txt",
                "profiles/narrator/voice/narrator.prompt.pt", "profiles/solo/voice/solo.wav",
                "profiles/multi/voice/multi.profile.json", "profiles/multi/voice/multi.variants/a.wav",
                "profiles/narrator/README.md", "profiles/narrator/products/ref.wav",
                "profiles/narrator/products/demo/d.mp3", "profiles/_default.txt",
                "profiles/narrator/lab/candidates.json", "profiles/narrator/lab/clips/c.wav",
                "music/library/bgm-library.json", "music/library/calm.mp3"):
        assert (old / rel).is_file(), rel
    assert (old / "music" / "channels").is_dir() and (old / "music" / "generated").is_dir()
    assert list((old / "archive").glob("*-voices/2026-01-01/old.wav"))
    assert list((old / "archive").glob("*-voices/_layout.json"))
    # không xoá gì: ngoài hợp đồng còn nguyên
    assert (old / "raw" / "Nguon" / "a.m4a").is_file() and (old / "omnivoice" / "truyen-out" / "x.mp3").is_file()
    assert (old / "omnivoice" / "voices" / "_example" / "README.md").is_file()
    info = json.loads((old / "station.json").read_text(encoding="utf-8"))
    assert info["profiles_dir"] == "profiles" and info["music_dir"] == "music" and info["bgm_dir"] == "music/library"
    assert info["keep"] == 1 and info["default_profile"] == "narrator" and info["mode"] == "separate"
    # loader: cả ba profile, kiểu mới; lab_dir và bgm_dir theo cây mới (dù biến VOICE_STUDIO_WORK còn đặt cũ)
    assert {r["name"]: r["kind"] for r in profiles.profile_records()} == {
        "multi": "new", "narrator": "new", "solo": "new"}
    assert profiles.get_default() == "narrator"
    assert _env.bgm_dir() == str(old / "music" / "library")
    assert _env.lab_dir("narrator") == str(old / "profiles" / "narrator" / "lab")
    ledger = json.loads(open(res["ledger"], encoding="utf-8").read())
    assert ledger["status"] == "applied" and ledger["steps"]
    assert all(not os.path.isabs(s.get("src", s.get("path", "x"))) for s in ledger["steps"])   # sổ ghi đường tương đối


def test_second_apply_finds_nothing_left_to_move(old, capsys):
    run(["--apply"], capsys)
    code, res, _ = run(["--dry-run"], capsys)
    assert code == 0 and res["moves"] == [] and res["station_json"]["changed"] is False


def test_rerun_on_already_migrated_station_does_nothing(old, capsys):
    """Review Opus 6: trạm đã dời + omnivoice/ giải thể (station.json không có engine_dir) -> chạy lại 0 bước,
    --apply không ghi station.json, không đẻ thêm sổ."""
    run(["--apply"], capsys)
    # mô phỏng trạm thật sau giải thể: omnivoice/ không còn, station.json không khai engine_dir
    shutil.rmtree(old / "omnivoice")
    info = json.loads((old / "station.json").read_text(encoding="utf-8"))
    info.pop("engine_dir", None)
    (old / "station.json").write_text(json.dumps(info), encoding="utf-8")
    ledgers = sorted(os.listdir(old / layout.LEDGER_DIR))
    before = (old / "station.json").read_bytes()
    code, res, _ = run(["--dry-run"], capsys)
    assert code == 0 and res["moves"] == [] and res["station_json"]["changed"] is False
    code, res, _ = run(["--apply"], capsys)
    assert code == 0, res
    assert (old / "station.json").read_bytes() == before
    assert sorted(os.listdir(old / layout.LEDGER_DIR)) == ledgers


def test_map_rename_matches_names_in_nfc_even_if_disk_is_nfd(old, tmp_path, capsys):
    """Review Opus 5: macOS giữ tên file dạng NFD; khoá NFC trong --map vẫn phải khớp."""
    import unicodedata
    nfd = unicodedata.normalize("NFD", "Giọng tiên hiệp")
    nfc = unicodedata.normalize("NFC", "Giọng tiên hiệp")
    assert nfd != nfc
    v = old / "omnivoice" / "voices"
    put(old, f"omnivoice/voices/{nfd}.wav", "wav-tien-hiep")
    put(old, f"omnivoice/voices/{nfd}.txt", "lời")
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps({"rename": {nfc: "giong-tien-hiep"}}), encoding="utf-8")
    code, res, _ = run(["--apply", "--map", str(mp)], capsys)
    assert code == 0, res
    assert (old / "profiles/giong-tien-hiep/voice/giong-tien-hiep.wav").is_file()
    assert res["renamed"] == {nfc: "giong-tien-hiep"}


# ── undo ─────────────────────────────────────────────────────────────────────────────

def test_undo_restores_tree_hash_for_hash(old, capsys):
    before = snapshot(old)
    run(["--apply"], capsys)
    assert snapshot(old) != before
    code, res, _ = run(["--undo"], capsys)
    assert code == 0 and res["action"] == "undo"
    assert snapshot(old) == before                      # từng file (sha256) và từng thư mục y hệt
    assert res["changed_since"] == [] and res["skipped_files"] == []
    code, res2, _ = run(["--undo"], capsys)             # sổ đã đảo thì không còn gì để đảo
    assert code == 2 and res2["ok"] is False


def test_undo_does_not_overwrite_newer_edits(old, capsys):
    run(["--apply"], capsys)
    p = old / "station.json"
    info = json.loads(p.read_text(encoding="utf-8"))
    info["device"] = "cpu"
    p.write_text(json.dumps(info), encoding="utf-8")                 # người dùng sửa sau khi dời
    (old / "profiles" / "solo" / "voice" / "solo.txt").write_text("sửa tay", encoding="utf-8")
    code, res, _ = run(["--undo"], capsys)
    assert code == 0 and res["skipped_files"] == ["station.json"]
    assert json.loads(p.read_text(encoding="utf-8"))["device"] == "cpu"     # không ghi đè bản mới
    assert "omnivoice/voices/solo.txt" in res["changed_since"]
    assert (old / "omnivoice" / "voices" / "solo.txt").read_text(encoding="utf-8") == "sửa tay"


def test_failure_midway_rolls_back_everything(old, capsys, monkeypatch):
    before = snapshot(old)
    real, calls = layout._do_move, {"n": 0}

    def flaky(st, step):
        calls["n"] += 1
        if calls["n"] == 5:
            raise OSError("đĩa đầy (giả)")
        return real(st, step)
    monkeypatch.setattr(layout, "_do_move", flaky)
    code, res, _ = run(["--apply"], capsys)
    assert code == 2 and "hoàn tác" in res["error"]
    assert snapshot(old) == before
    sổ = sorted((old / layout.LEDGER_DIR).glob("layout-*.json"))
    assert json.loads(sổ[-1].read_text(encoding="utf-8"))["status"] == "rolled-back"


# ── xung đột, an toàn ────────────────────────────────────────────────────────────────

def test_conflict_stops_before_touching_anything(old, capsys):
    put(old, "profiles/narrator/voice/narrator.wav", "đã có")
    before = snapshot(old)
    code, res, _ = run(["--apply"], capsys)
    assert code == 2 and "đích đã có" in res["error"]
    assert snapshot(old) == before


def test_moves_only_never_deletes(old, capsys):
    before = {k: v for k, v in snapshot(old).items() if v is not None}
    run(["--apply"], capsys)
    after = {k: v for k, v in snapshot(old).items() if v is not None}
    lost = {k for k, v in before.items() if v not in after.values()}
    assert lost == {"station.json"}, lost               # mọi nội dung có trước đều còn (chỉ đổi chỗ); trừ station.json được sửa
    assert len(after) >= len(before)                    # không file nào biến mất


def test_station_without_old_data_is_a_noop(tmp_path, monkeypatch, capsys):
    st = tmp_path / "empty"
    st.mkdir()
    monkeypatch.setenv("VOICE_STATION", str(st))
    code, res, _ = run(["--apply"], capsys)
    assert code == 0 and res["moves"] == []


def test_missing_station_is_exit_3(tmp_path, capsys):
    code, res, _ = run(["--station", str(tmp_path / "nope")], capsys)
    assert code == 3


# ── --map ────────────────────────────────────────────────────────────────────────────

def test_map_moves_manual_items_and_undo_reverts_them(old, tmp_path, capsys):
    mp = tmp_path / "map.json"
    mp.write_text(json.dumps({"moves": [{"from": "raw/Nguon", "to": "profiles/narrator/raw/Nguon"},
                                        {"from": "omnivoice/truyen-out", "to": "archive/2026-11-22-truyen-out"}]}),
                  encoding="utf-8")
    before = snapshot(old)
    code, res, _ = run(["--apply", "--map", str(mp)], capsys)
    assert code == 0
    assert (old / "profiles/narrator/raw/Nguon/a.m4a").is_file() and (old / "archive/2026-11-22-truyen-out/x.mp3").is_file()
    assert "raw/Nguon" not in {m["path"] for m in res["manual"]}
    assert run(["--undo"], capsys)[0] == 0
    assert snapshot(old) == before


@pytest.mark.parametrize("bad", ["../x", "/abs", "a/../b", "C:/x", ".git/config"])
def test_map_rejects_unsafe_paths(old, tmp_path, capsys, bad):
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps({"moves": [{"from": "raw/Nguon", "to": bad}]}), encoding="utf-8")
    code, res, _ = run(["--dry-run", "--map", str(mp)], capsys)
    assert code == 2 and res["ok"] is False


def test_map_rename_profile_without_manifest(old, tmp_path, capsys):
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps({"rename": {"narrator": "giong-moi"}}), encoding="utf-8")
    code, res, _ = run(["--apply", "--map", str(mp)], capsys)
    assert code == 0
    assert (old / "profiles/giong-moi/voice/giong-moi.wav").is_file()
    assert (old / "profiles/giong-moi/lab/candidates.json").is_file()
    assert json.loads((old / "station.json").read_text(encoding="utf-8"))["default_profile"] == "giong-moi"
    assert any("profiles/_default.txt" in n for n in res["notes"])


def test_map_rename_refuses_profile_with_manifest(old, tmp_path, capsys):
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps({"rename": {"multi": "khac"}}), encoding="utf-8")
    code, res, _ = run(["--dry-run", "--map", str(mp)], capsys)
    assert code == 2 and "manifest" in res["error"]


# ── .gitignore của trạm git ──────────────────────────────────────────────────────────

@need_git
def test_gitignore_guard_adds_lines_before_moving_and_undo_restores(old, capsys):
    git(old, "init", "-q")
    (old / ".gitignore").write_text("/raw/\n*.mp3\n", encoding="utf-8")
    before_ignore = (old / ".gitignore").read_bytes()
    code, res, _ = run(["--dry-run"], capsys)
    assert res["gitignore"]["git"] is True and "/profiles/*/raw/" in res["gitignore"]["add"]
    assert "profiles/*/raw/" in res["gitignore"]["unprotected_now"]
    assert (old / ".gitignore").read_bytes() == before_ignore       # dry-run không sửa
    code, res, _ = run(["--apply"], capsys)
    assert code == 0
    text = (old / ".gitignore").read_text(encoding="utf-8")
    for line in ("/profiles/*/raw/", "/profiles/*/lab/", "/profiles/*/products/", "/music/generated/",
                 "/out/", "/archive/", "!/profiles/*/voice/**/*.wav"):
        assert line in text
    assert layout.gitignore_unprotected(str(old)) == []
    assert git(old, "check-ignore", "-q", "profiles/narrator/raw/x.wav").returncode == 0
    assert git(old, "check-ignore", "-q", "profiles/narrator/voice/narrator.wav").returncode == 1   # clip tham chiếu vẫn theo dõi
    git(old, "add", "-A")
    staged = git(old, "diff", "--cached", "--name-only").stdout
    assert "profiles/narrator/voice/narrator.wav" in staged and "/raw/" not in staged
    assert run(["--undo"], capsys)[0] == 0
    assert (old / ".gitignore").read_bytes() == before_ignore


@need_git
def test_gitignore_already_protecting_is_left_alone(old, capsys):
    git(old, "init", "-q")
    (old / ".gitignore").write_text("\n".join(layout.GITIGNORE_LINES) + "\n" + layout.GITIGNORE_KEEP + "\n",
                                    encoding="utf-8")
    before = (old / ".gitignore").read_bytes()
    code, res, _ = run(["--apply"], capsys)
    assert code == 0 and res["gitignore"]["add"] == []
    assert (old / ".gitignore").read_bytes() == before


@need_git
def test_gitignore_guard_stops_if_a_rule_still_exposes_raw(old, capsys):
    git(old, "init", "-q")
    # `!` sau cùng mở lại thư mục raw: dòng thêm vào không đủ chặn → dừng trước khi dời byte nào
    (old / ".gitignore").write_text("!/profiles/*/raw/\n!/profiles/\n", encoding="utf-8")
    before = snapshot(old)
    ig = (old / ".gitignore").read_bytes()
    orig = layout._gitignore_edit

    def edit_putting_negation_last(st):
        b, a, add = orig(st)
        return b, a + b"!/profiles/*/raw/\n", add
    layout_edit = layout._gitignore_edit
    layout._gitignore_edit = edit_putting_negation_last
    try:
        code, res, _ = run(["--apply"], capsys)
    finally:
        layout._gitignore_edit = layout_edit
    assert code == 2 and "chưa chặn" in res["error"]
    assert snapshot(old) == before and (old / ".gitignore").read_bytes() == ig


def test_non_git_station_skips_gitignore(old, capsys):
    code, res, _ = run(["--apply"], capsys)
    assert code == 0 and res["gitignore"]["git"] is False
    assert not (old / ".gitignore").exists()


# ── export / init / doctor trên cây mới ──────────────────────────────────────────────

def test_export_personal_packs_voice_and_music_not_raw_or_lab(old, tmp_path, capsys):
    import zipfile
    run(["--apply"], capsys)
    put(old, "profiles/narrator/raw/big.wav", "RAW")
    out = tmp_path / "g.zip"
    assert cli.main(["export", "--personal", "--out", str(out), "--json"]) == 0
    names = set(zipfile.ZipFile(out).namelist())
    assert "profiles/narrator/voice/narrator.wav" in names and "music/library/calm.mp3" in names
    assert "profiles/_default.txt" in names and "station.json" in names
    assert not any("/raw/" in n or "/lab/" in n or n.endswith(".prompt.pt") for n in names)
    out2 = tmp_path / "g2.zip"
    assert cli.main(["export", "--personal", "--with-lab", "--out", str(out2), "--json"]) == 0
    names2 = set(zipfile.ZipFile(out2).namelist())
    assert "profiles/narrator/lab/clips/c.wav" in names2 and not any("/raw/" in n for n in names2)


def test_doctor_json_has_profiles_dir_and_flags_stale_env(old, tmp_path, capsys, monkeypatch):
    from voice_studio import doctor
    run(["--apply"], capsys)
    monkeypatch.setenv("OMNIVOICE_DIR", str(old / "omnivoice"))
    monkeypatch.setenv("VOICE_BGM_DIR", str(old / "assets" / "bgm"))
    monkeypatch.setenv("VOICE_STUDIO_WORK", str(old / "data" / "voicelab"))
    cli.main(["doctor", "--json"])
    res = last_json(capsys.readouterr().out)
    assert res["profiles_dir"] == str(old / "profiles") and "voices_dir" in res and res["layout"] == "new"
    names = {c["name"]: c for c in res["checks"]}
    assert names["profiles"]["level"] == "ok" and "3 profile" in names["profiles"]["detail"]
    for k in ("env-omnivoice-dir", "env-voice-bgm-dir", "env-voice-studio-work"):
        assert names[k]["level"] == "warn", k


def test_doctor_on_legacy_station_stays_passing(old, capsys):
    cli.main(["doctor", "--json"])
    res = json.loads([ln for ln in capsys.readouterr().out.splitlines() if ln.strip()][-1])
    names = {c["name"]: c for c in res["checks"]}
    assert names["voices"]["level"] == "ok" and names["layout"]["level"] == "ok"
    assert "env-voice-bgm-dir" not in names


@need_git
def test_doctor_warns_when_git_station_does_not_ignore_raw(old, capsys):
    run(["--apply"], capsys)
    git(old, "init", "-q")
    cli.main(["doctor", "--json"])
    res = json.loads([ln for ln in capsys.readouterr().out.splitlines() if ln.strip()][-1])
    g = {c["name"]: c for c in res["checks"]}["gitignore"]
    assert g["level"] == "warn" and "profiles/*/raw/" in g["detail"]
