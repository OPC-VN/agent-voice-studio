# profiles/ — mỗi giọng một thư mục

```
profiles/<tên>/
  voice/      clip tham chiếu: <tên>.wav · <tên>.txt · <tên>.prompt.pt (cache) · <tên>.profile.json · <tên>.variants/
  raw/        bản ghi gốc (nặng, không vào git, không vào export)
  lab/        chỗ đào clip: candidates.json, clips/ (dựng lại được)
  report/     hồ sơ kiểm của giọng
  products/   demo, bản đọc thử về giọng này
  README.md   nguồn, mốc cắt, lịch sử
profiles/_default.txt   (tuỳ chọn) tên profile mặc định; station.json: default_profile thắng
```

Thư mục bắt đầu bằng `_` hoặc `.` (như `_example/`) và thư mục tên `archive` không phải profile.
Tên profile so theo Unicode NFC. Đọc thử: `voice-studio profiles list`.
