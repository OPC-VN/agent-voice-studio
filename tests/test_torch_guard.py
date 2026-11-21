"""Guard mọi lời gọi model và giữ import nhẹ trên máy thiếu torch."""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

from voice_studio import engine, make_profile, mcp_server, profiles

ROOT = Path(__file__).resolve().parents[1]
MODEL_METHODS = {"generate", "create_voice_clone_prompt"}


def _is_guarded(node, parents):
    while node in parents:
        parent = parents[node]
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return False
        if isinstance(parent, ast.With) and node in parent.body:
            for item in parent.items:
                expr = item.context_expr
                if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
                    if expr.func.id == "no_grad_guard":
                        return True
        node = parent
    return False


def test_model_calls_are_inside_no_grad_guard():
    unguarded = []
    found = set()
    for path in sorted((ROOT / "voice_studio").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        nodes = list(ast.walk(tree))
        parents = {child: parent for parent in nodes for child in ast.iter_child_nodes(parent)}
        for node in nodes:
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in MODEL_METHODS:
                    found.add(node.func.attr)
                    if not _is_guarded(node, parents):
                        unguarded.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.func.attr}")
    assert found == MODEL_METHODS
    assert not unguarded, "\n".join(unguarded)


def test_inference_paths_disable_grad_and_restore_it(station, fake_engine, tmp_path):
    import torch

    assert torch.is_grad_enabled()

    engine.synth("Xin chào", "demo")
    assert fake_engine.grad_calls == [
        ("create_voice_clone_prompt", False), ("generate", False),
    ]
    assert torch.is_grad_enabled()

    profiles.get_clone_prompt(fake_engine, "other")
    assert fake_engine.grad_calls[-1] == ("create_voice_clone_prompt", False)

    name = profiles.save_profile_from_instruct(fake_engine, "female", "frozen", set_as_default=False)
    assert fake_engine.grad_calls[-1] == ("generate", False)
    assert (station / "omnivoice" / "voices" / f"{name}.wav").is_file()

    fake_engine.grad_calls.clear()
    ok, _ = make_profile.check_stutter_leak(fake_engine, "frozen", "Đây là lời mẫu.")
    assert ok
    assert fake_engine.grad_calls == [
        ("create_voice_clone_prompt", False), ("generate", False), ("generate", False),
    ]

    ref = station / "omnivoice" / "voices" / "demo.wav"
    msg = mcp_server.clone_voice("Xin chào", str(tmp_path / "out.wav"), str(ref), "Lời mẫu")
    assert msg.startswith("OK")
    assert fake_engine.grad_calls[-1] == ("generate", False)
    assert torch.is_grad_enabled()


def test_import_engine_and_guard_does_not_import_torch():
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys, voice_studio.engine, voice_studio._torchguard; "
         "assert 'torch' not in sys.modules"],
        cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("has_torch", [True, False])
def test_guard_without_no_grad(monkeypatch, has_torch):
    from types import ModuleType

    from voice_studio import _torchguard

    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch") if has_torch else None)
    with _torchguard.no_grad_guard():
        pass


def test_guard_exposes_a_broken_torch_dependency(monkeypatch):
    import builtins

    from voice_studio import _torchguard

    original = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("torch dependency is broken", name="torch_dependency")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)
    with pytest.raises(ImportError, match="dependency is broken"):
        _torchguard.no_grad_guard()
