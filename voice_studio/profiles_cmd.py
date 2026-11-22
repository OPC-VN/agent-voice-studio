"""profiles_cmd.py — `voice-studio profiles list [--json]`: liệt kê profile giọng của trạm.

Dành cho pipeline khác (marketing, video) hỏi "trạm có giọng nào" mà KHÔNG đọc thẳng thư mục kho: một lệnh,
một dòng JSON cuối stdout (hợp đồng như `speak`/`doctor`):

    {"ok": true, "layout": "new"|"legacy", "profiles_dir": "...", "voices_dir": "...", "default": "<tên>"|null,
     "profiles": [{"name", "kind": "new"|"legacy", "markers": N, "default": bool, "voice_dir": "..."}]}

`kind` = giọng nằm ở `profiles/<tên>/voice/` (new) hay kho phẳng cũ (legacy); `markers` = số marker sắc thái
trong `<tên>.profile.json` (0 = giọng đơn). Chưa xác định được trạm và không có VOICES_DIR ⇒ mã 3.
"""
import argparse
import sys

from . import _env, contract, profiles


def list_result():
    if not profiles.store_exists():
        raise contract.StationMissing(
            "chưa có kho giọng: không thấy profiles/ lẫn kho phẳng. Dựng trạm bằng `voice-studio init` "
            f"(hoặc đặt VOICE_STATION). {_env.OLD_DATA_HINT}")
    default = profiles.get_default()
    recs = profiles.profile_records()
    for r in recs:
        r["default"] = r["name"] == default
    return {"layout": profiles.layout(), "profiles_dir": profiles.profiles_dir(),
            "voices_dir": profiles._legacy_dir(), "default": default, "profiles": recs}


def _table(res):
    rows = [("TÊN", "KIỂU", "MARKER", "MẶC ĐỊNH", "THƯ MỤC GIỌNG")]
    rows += [(r["name"], r["kind"], str(r["markers"]), "*" if r["default"] else "", r["voice_dir"])
             for r in res["profiles"]]
    w = [max(len(row[i]) for row in rows) for i in range(4)]
    return "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(row[:4])) + "  " + row[4] for row in rows)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("Cách dùng: voice-studio profiles list [--json]\n  list   liệt kê profile giọng "
              "(kiểu mới profiles/<tên>/voice/ ∪ kho phẳng cũ), mặc định, số marker")
        return contract.OK if argv else contract.CONTRACT_ERROR
    if argv[0] != "list":
        contract.log(f"lệnh con lạ: '{argv[0]}' (có: list)")
        return contract.CONTRACT_ERROR
    ap = argparse.ArgumentParser(prog="voice-studio profiles list",
                                 description="Liệt kê profile giọng của trạm.")
    ap.add_argument("--json", action="store_true", help="một dòng JSON cuối stdout")
    args, code = contract.parse(ap, argv[1:])
    if args is None:
        return code

    def fn(_a):
        res = list_result()
        contract.log(f"[profiles] {len(res['profiles'])} profile · kiểu trạm: {res['layout']} · "
                     f"mặc định: {res['default'] or '(không)'}")
        if not args.json:
            print(_table(res))
        return res
    return contract.run(fn, args, args.json)


if __name__ == "__main__":
    sys.exit(main())
