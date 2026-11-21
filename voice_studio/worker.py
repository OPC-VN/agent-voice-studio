"""worker.py — worker nền giữ model TTS & STT warm trong VRAM kèm tự xả khi idle.

Giao tiếp qua JSON từng dòng trên stdin/stdout (mọi log nhiễu từ thư viện con được
chuyển sang stderr để không làm vỡ khung JSON). Tự xả toàn bộ cache + `torch.cuda.empty_cache()`
sau `idle_timeout_sec` (mặc định 1800 giây = 30 phút) không có yêu cầu tts/stt/warmup.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field

from . import engine, listen, profiles

DEFAULT_IDLE_TIMEOUT_SEC = 1800.0
DEFAULT_INSTRUCT = "female, young adult, moderate pitch"


def _norm_tts_device(dev: str | None) -> str | None:
    """Chuyển `'auto'` hoặc chuỗi rỗng thành `None` để `engine.load()` tự chọn GPU/CPU."""
    val = (dev or "").strip()
    return None if (not val or val.lower() == "auto") else val


def _norm_path(p: str) -> str:
    return os.path.normpath(os.path.abspath(os.path.expanduser(p)))


@dataclass
class WorkerState:
    idle_timeout_sec: float = DEFAULT_IDLE_TIMEOUT_SEC
    tts_device: str = "auto"
    stt_model: str = "small"
    stt_device: str = "auto"
    stt_compute_type: str = "auto"
    last_active_mono: float = field(default_factory=time.monotonic)
    unloaded_at: str | None = None
    auto_unload_count: int = 0
    busy_count: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)


_DEFAULT_STATE = WorkerState()


def status_snapshot(state: WorkerState | None = None) -> dict:
    st = state or _DEFAULT_STATE
    with st.lock:
        tts_dev = engine.loaded_device()
        tts_loaded = tts_dev is not None
        stt_models = listen.loaded_stt_info()
        stt_loaded = bool(stt_models)
        any_loaded = tts_loaded or stt_loaded
        idle_s = max(0.0, time.monotonic() - st.last_active_mono) if any_loaded else 0.0
        remaining = (
            max(0.0, st.idle_timeout_sec - idle_s)
            if (any_loaded and st.idle_timeout_sec > 0)
            else 0.0
        )
        return {
            "ok": True,
            "pid": os.getpid(),
            "tts_loaded": tts_loaded,
            "tts_device": tts_dev,
            "stt_loaded": stt_loaded,
            "stt_models": stt_models,
            "idle_timeout_sec": float(st.idle_timeout_sec),
            "idle_seconds": round(idle_s, 1),
            "remaining_idle_sec": round(remaining, 1),
            "auto_unload_count": st.auto_unload_count,
            "unloaded_at": st.unloaded_at,
        }


def unload_all(state: WorkerState | None = None, *, auto: bool = False) -> dict:
    st = state or _DEFAULT_STATE
    with st.lock:
        engine.unload()
        profiles.clear_cache()
        listen.unload_stt()
        st.unloaded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if auto:
            st.auto_unload_count += 1
        return status_snapshot(st)


def maybe_idle_unload(state: WorkerState | None = None) -> bool:
    st = state or _DEFAULT_STATE
    with st.lock:
        if st.idle_timeout_sec <= 0 or st.busy_count > 0:
            return False
        tts_loaded = engine.loaded_device() is not None
        stt_loaded = bool(listen.loaded_stt_info())
        if not (tts_loaded or stt_loaded):
            return False
        if (time.monotonic() - st.last_active_mono) < st.idle_timeout_sec:
            return False
        unload_all(st, auto=True)
        return True


def _apply_config(req: dict, st: WorkerState) -> dict:
    with st.lock:
        if "idle_timeout_sec" in req and req["idle_timeout_sec"] is not None:
            st.idle_timeout_sec = max(0.0, float(req["idle_timeout_sec"]))
        if "tts_device" in req and req["tts_device"]:
            new_dev = str(req["tts_device"]).strip()
            loaded_dev = engine.loaded_device()
            if (
                new_dev != st.tts_device
                and loaded_dev is not None
                and new_dev.lower() not in ("auto", str(loaded_dev).lower())
            ):
                engine.unload()
                profiles.clear_cache()
            st.tts_device = new_dev
        if "stt_model" in req and req["stt_model"]:
            new_m = str(req["stt_model"]).strip()
            if new_m != st.stt_model and listen.loaded_stt_info():
                listen.unload_stt()
            st.stt_model = new_m
        if "stt_device" in req and req["stt_device"]:
            new_sdev = str(req["stt_device"]).strip()
            if new_sdev != st.stt_device and listen.loaded_stt_info():
                listen.unload_stt()
            st.stt_device = new_sdev
        if "stt_compute_type" in req and req["stt_compute_type"]:
            new_sc = str(req["stt_compute_type"]).strip()
            if new_sc != st.stt_compute_type and listen.loaded_stt_info():
                listen.unload_stt()
            st.stt_compute_type = new_sc
    return status_snapshot(st)


def _do_warmup(req: dict, st: WorkerState) -> dict:
    targets = req.get("targets") or ["tts", "stt"]
    tts_dev = req.get("tts_device") or st.tts_device
    stt_m = req.get("stt_model") or st.stt_model
    stt_dev = req.get("stt_device") or st.stt_device
    stt_comp = req.get("stt_compute_type") or st.stt_compute_type

    with st.lock:
        st.last_active_mono = time.monotonic()
        if "tts" in targets:
            engine.load(device=_norm_tts_device(tts_dev))
        if "stt" in targets:
            req_m, req_c, req_d = listen._pick_stt_preset(stt_m, stt_dev, stt_comp)
            listen._get_whisper_model(req_m, req_d, req_c, keep_warm=True)
        st.last_active_mono = time.monotonic()
    return status_snapshot(st)


def _do_tts(req: dict, st: WorkerState) -> dict:
    text = str(req.get("text") or "")
    out_path = str(req.get("out") or "")
    if not out_path:
        raise ValueError("thiếu đường dẫn file đầu ra `out`")
    profile = str(req.get("profile") or "").strip()
    instruct = str(req.get("instruct") or "").strip()
    language = str(req.get("language") or engine.DEFAULT_LANGUAGE)
    speed = float(req.get("speed") or 1.0)
    device = str(req.get("device") or st.tts_device or "auto")
    num_step = req.get("num_step")
    guidance_scale = req.get("guidance_scale")
    denoise = req.get("denoise")

    with st.lock:
        st.last_active_mono = time.monotonic()
    m = engine.load(device=_norm_tts_device(device))
    prompt = None
    if not (instruct and not profile):
        if profile:
            prompt = profiles.get_clone_prompt(m, profile)
        else:
            try:
                prompt = profiles.get_clone_prompt(m, None)
            except profiles.ProfileError:
                prompt = None
            if prompt is None and not instruct:
                instruct = DEFAULT_INSTRUCT
    audio, sr = engine.synth(
        text,
        prompt=prompt,
        language=language,
        speed=speed,
        instruct=(instruct or None) if prompt is None else None,
        model=m,
        num_step=num_step,
        guidance_scale=guidance_scale,
        denoise=denoise,
    )
    saved = engine.save(audio, out_path, sr)
    with st.lock:
        st.last_active_mono = time.monotonic()
    return {"ok": True, "out": saved, "sampling_rate": sr, "status": status_snapshot(st)}


def _do_stt(req: dict, st: WorkerState) -> dict:
    audio_path = str(req.get("audio_path") or "")
    with st.lock:
        st.last_active_mono = time.monotonic()
    res = listen.transcribe_file(
        audio_path,
        language=str(req.get("language") or ""),
        model_size=str(req.get("model") or st.stt_model),
        device=str(req.get("device") or st.stt_device),
        compute_type=str(req.get("compute_type") or st.stt_compute_type),
        beam_size=int(req.get("beam_size") or 1),
        vad_filter=bool(req.get("vad_filter", True)),
        min_rms=float(req.get("min_rms", 0.01)),
        keep_warm=True,
    )
    with st.lock:
        st.last_active_mono = time.monotonic()
    return {"ok": True, "result": res, "status": status_snapshot(st)}


def handle_request(req: dict, state: WorkerState | None = None) -> dict:
    """Xử lý một yêu cầu JSON đơn lẻ; không tự thoát tiến trình."""
    st = state or _DEFAULT_STATE
    req_id = req.get("id")
    op = str(req.get("op") or "").strip().lower()
    try:
        if op == "status":
            resp = status_snapshot(st)
        elif op == "config":
            resp = _apply_config(req, st)
        elif op == "unload":
            resp = unload_all(st, auto=False)
        elif op == "quit":
            unload_all(st, auto=False)
            resp = {"ok": True, "quit": True}
        elif op in ("warmup", "tts", "stt"):
            with st.lock:
                st.busy_count += 1
            try:
                if op == "warmup":
                    resp = _do_warmup(req, st)
                elif op == "tts":
                    resp = _do_tts(req, st)
                else:
                    resp = _do_stt(req, st)
            finally:
                with st.lock:
                    st.busy_count = max(0, st.busy_count - 1)
        else:
            resp = {"ok": False, "error": f"unknown op: {op}"}
    except Exception as exc:
        resp = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}

    if req_id is not None:
        resp["id"] = req_id
    return resp


def _watchdog_loop(state: WorkerState, stop_event: threading.Event, poll_sec: float = 2.0):
    while not stop_event.wait(poll_sec):
        try:
            maybe_idle_unload(state)
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Persistent warm TTS/STT worker cho Agent Voice Studio")
    ap.add_argument("--station", default="", help="Gốc trạm giọng (đặt VOICE_STATION)")
    ap.add_argument("--omnivoice-dir", default="", help="Thư mục engine OmniVoice (đặt OMNIVOICE_DIR)")
    ap.add_argument("--voices-dir", default="", help="Kho profile giọng (đặt VOICES_DIR)")
    ap.add_argument("--hf-cache", default="", help="Thư mục cache model HuggingFace (đặt HF_HUB_CACHE)")
    ap.add_argument("--idle-timeout", type=float, default=None, help="Số giây idle trước khi tự xả VRAM")
    return ap


def _apply_cli_env(args: argparse.Namespace) -> None:
    if args.station:
        os.environ["VOICE_STATION"] = _norm_path(args.station)
    if args.omnivoice_dir:
        os.environ["OMNIVOICE_DIR"] = _norm_path(args.omnivoice_dir)
    if args.voices_dir:
        os.environ["VOICES_DIR"] = _norm_path(args.voices_dir)
    if args.hf_cache:
        val = _norm_path(args.hf_cache)
        os.environ["HF_HUB_CACHE"] = val
        os.environ["VOICE_MODELS_DIR"] = val
    engine.apply_offline_env()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _apply_cli_env(args)
    idle_sec = DEFAULT_IDLE_TIMEOUT_SEC if args.idle_timeout is None else max(0.0, float(args.idle_timeout))

    proto_out = sys.stdout
    sys.stdout = sys.stderr
    state = WorkerState(idle_timeout_sec=idle_sec)
    stop_event = threading.Event()
    wd = threading.Thread(target=_watchdog_loop, args=(state, stop_event), daemon=True)
    wd.start()

    try:
        for raw in sys.stdin:
            line = (raw or "").strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                resp = {"ok": False, "error": f"invalid json: {exc}"}
            else:
                resp = handle_request(req, state)
            proto_out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            proto_out.flush()
            if resp.get("quit"):
                break
    finally:
        stop_event.set()
        unload_all(state, auto=False)
        sys.stdout = proto_out
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
