"""Context cho suy luận, giữ torch ngoài đường import CLI."""
from contextlib import AbstractContextManager, nullcontext


def no_grad_guard() -> AbstractContextManager:
    """Tắt autograd khi torch có sẵn, giữ lỗi nếu chính bản cài torch bị hỏng."""
    try:
        import torch
    except ImportError as exc:
        if exc.name != "torch":
            raise
        return nullcontext()
    no_grad = getattr(torch, "no_grad", None)
    return no_grad() if no_grad is not None else nullcontext()
