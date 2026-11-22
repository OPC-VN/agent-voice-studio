"""
organize.py — sắp xếp kho giọng theo từng profile, và archive file cũ.

  voice-studio lab organize --keep narrator voice-b voice-c
  voice-studio lab organize --keep ... --apply      # không có --apply = chỉ xem trước, không đụng gì

## Hai kiểu bố cục (xem `voice_studio.profiles`)

KIỂU MỚI (trạm có `profiles/`): clip tham chiếu đã nằm trong thư mục riêng của profile, nên chỉ còn việc dọn:

    profiles/<tên>/
        voice/<tên>.wav .txt .prompt.pt .profile.json <tên>.variants/   <- hợp đồng với hệ cũ, KHÔNG đụng
        README.md                          <- nguồn, mốc cắt, số đo, lịch sử (tạo nếu chưa có)
        products/ref.wav  products/demo/   <- bản sao clip mẫu + output demo
    archive/<ngày>-voices/                 <- file của profile không còn giữ, KHÔNG xoá thẳng

KIỂU CŨ (kho phẳng `<engine>/voices`): hai file hợp đồng ở phẳng, mọi thứ khác vào thư mục riêng của profile:

    voices/
        narrator.wav  .txt  .prompt.pt     <- hợp đồng với hệ cũ
        narrator/README.md ref.wav demo/   <- sổ tay, bản sao clip mẫu, output demo
        _archive/<ngày>/                   <- file không còn dùng, KHÔNG xoá thẳng

Vì sao KHÔNG chuyển .wav kiểu cũ vào thư mục con: `list_profiles()` đọc đúng `voices/<tên>.wav` và các
pipeline cùng tác vụ định kỳ thường pin cứng TÊN GIỌNG; dời hai file đó là gãy mọi thứ đang tiêu thụ giọng —
lỗi sẽ nổ lúc chạy tự động ban đêm chứ không nổ lúc mình đang ngồi trước máy. Muốn sang kiểu mới thì dùng
`voice-studio station migrate-layout` (có sổ, có `--undo`).

Archive chứ không xoá: kho giọng không nằm trong git, xoá là mất vĩnh viễn.
"""
import argparse
import datetime
import json
import os
import shutil
import sys

from .. import _env, engine, profiles

CONTRACT = (".wav", ".txt", ".prompt.pt")


def _records():
    return profiles.profile_records()


def profile_names():
    """Tên các profile hệ cũ nhìn thấy (tên thật trên đĩa, dạng NFC)."""
    return [r["name"] for r in _records()]


def _arch_dir(rec, stamp):
    if rec["kind"] == "new":
        return os.path.join(_env.station_dir(), _env.ARCHIVE_DIRNAME, f"{stamp}-voices")
    return os.path.join(rec["voice_dir"], "_archive", stamp)


def _readme(name, stamp):
    return (f"# {name}\n\n"
            f"Sổ tay của giọng `{name}` (tạo {stamp} bởi `voice-studio lab organize`). Ghi vào đây: nguồn thu âm, "
            f"mốc cắt, số đo, lịch sử chỉnh. Bản ghi gốc ở `raw/`, chỗ đào clip ở `lab/`, "
            f"demo ở `products/`.\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", nargs="+", required=True, help="Profile giữ lại.")
    ap.add_argument("--apply", action="store_true", help="Thực thi (mặc định chỉ xem trước).")
    args = ap.parse_args(argv)

    stamp = datetime.date.today().isoformat()
    dry = not args.apply
    tag = "[xem trước]" if dry else "[thực thi]"

    recs = {r["name"]: r for r in _records()}
    have = sorted(recs)
    keep = {profiles.nfc(k) for k in args.keep}
    missing = keep - set(have)
    if missing:
        sys.exit(f"[organize] DỪNG: không thấy profile {sorted(missing)}. "
                 f"Có: {have}")

    plan_arch = []      # (đường nguồn, thư mục archive)
    plan_dir = []       # profile giữ lại

    # 1) profile không nằm trong --keep -> archive (chỉ ba file hợp đồng)
    for n in have:
        if n in keep:
            continue
        r = recs[n]
        stem = profiles._disk_name(n)
        for e in CONTRACT:
            f = os.path.join(r["voice_dir"], stem + e)
            if os.path.isfile(f):
                plan_arch.append((f, _arch_dir(r, stamp)))

    # 2) kiểu cũ: file rác/tạm bắt đầu bằng '_' trong kho phẳng (trừ _default.txt và thư mục _archive)
    legacy_dirs = {r["voice_dir"] for r in recs.values() if r["kind"] == "legacy"}
    for d in sorted(legacy_dirs):
        for fn in sorted(os.listdir(d)):
            full = os.path.join(d, fn)
            if os.path.isfile(full) and fn.startswith("_") and fn != "_default.txt":
                plan_arch.append((full, os.path.join(d, "_archive", stamp)))

    # 3) thư mục riêng cho từng profile giữ lại
    plan_dir = sorted(keep)

    print(f"[organize] {tag} archive {len(plan_arch)} file")
    for src, dst in plan_arch:
        print(f"           - {os.path.basename(src)} -> {dst}")
    print(f"[organize] {tag} tạo {len(plan_dir)} thư mục profile")

    if dry:
        print("[organize] chưa đụng gì. Thêm --apply để thực thi.")
        return

    arch_dirs = set()
    for src, dst in plan_arch:
        os.makedirs(dst, exist_ok=True)
        arch_dirs.add(dst)
        if os.path.isfile(src):
            shutil.move(src, os.path.join(dst, os.path.basename(src)))

    for n in plan_dir:
        r = recs[n]
        stem = profiles._disk_name(n)
        wav = os.path.join(r["voice_dir"], stem + ".wav")
        if r["kind"] == "new":
            d = os.path.dirname(r["voice_dir"])              # profiles/<tên>/
            prod = os.path.join(d, "products")
            os.makedirs(os.path.join(prod, "demo"), exist_ok=True)
            if os.path.isfile(wav):
                shutil.copyfile(wav, os.path.join(prod, "ref.wav"))
            rd = os.path.join(d, "README.md")
            if not os.path.isfile(rd):
                with open(rd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(_readme(n, stamp))
        else:
            d = os.path.join(r["voice_dir"], stem)
            os.makedirs(os.path.join(d, "demo"), exist_ok=True)
            if os.path.isfile(wav):
                shutil.copyfile(wav, os.path.join(d, "ref.wav"))

    # sổ tay: ai đó (hoặc chính mình sau này) mở archive ra phải biết vì sao nó ở đó
    for arch in sorted(arch_dirs):
        with open(os.path.join(arch, "_README.md"), "w", encoding="utf-8") as f:
            f.write(f"# Archive {stamp}\n\n"
                    f"File chuyển vào đây khi sắp xếp lại kho giọng.\n"
                    f"Profile giữ lại lúc đó: {', '.join(sorted(keep))}\n\n"
                    f"KHÔNG xoá thẳng vì kho giọng không nằm trong git — mất là mất hẳn.\n"
                    f"Muốn khôi phục: chuyển ngược file `<tên>.wav` + `.txt` về thư mục giọng của profile.\n")
    for d in sorted(legacy_dirs):
        with open(os.path.join(d, "_layout.json"), "w", encoding="utf-8") as f:
            json.dump({"organized_at": stamp, "keep": sorted(keep),
                       "archived": [os.path.basename(s) for s, t in plan_arch if t.startswith(d)],
                       "note": "wav/txt phải ở PHẲNG — kho profile đọc <kho>/<tên>.wav"},
                      f, ensure_ascii=False, indent=2)
    print(f"[organize] xong. Còn lại: {profile_names()}")


if __name__ == "__main__":
    sys.exit(main())
