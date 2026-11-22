# Trạm giọng

Thư mục này là **trạm giọng** của bạn: nơi chứa engine (venv), giọng của riêng bạn, nhạc nền và
output. Repo `agent-voice-studio` chỉ chứa mã; mọi thứ ở đây là của bạn và **không bao giờ vào git**.

Cây do `voice-studio init` dựng từ `templates/workspaces/` của repo. Giải thích từng thư mục —
cái nào là nội dung, cái nào là quản lý, cái nào được sao lưu, cái nào xoá được — ở
`docs/WORKSPACE.md` của repo.

```
station.json          cấu hình trạm (hợp đồng, venv, profiles_dir, music_dir, bgm_dir, default_profile)
profiles/<tên>/       MỖI GIỌNG MỘT THƯ MỤC: voice/ (clip tham chiếu) · raw/ · lab/ · report/ · products/ · README.md
profiles/_default.txt tên profile mặc định (tuỳ chọn; station.json: default_profile thắng)
music/library/       thư viện nhạc nền: bgm-library.json + <style>.mp3
music/channels/      nhạc nhận diện từng kênh (intro/outro/nền riêng)
music/generated/     bản thô sinh bằng MusicGen (nháp)
out/                  output và nháp, xoá được (VOICE_STUDIO_WORK)
archive/              đồ nghỉ hưu: archive/<ngày>-<slug>/
cache/                cache dựng lại được
omnivoice/.venv/      venv engine CHỈ khi máy không có OpcOS — bạn tự tạo theo lệnh `init` in ra; máy có OpcOS: ở runtime/
```

Kiểm trạm: `voice-studio doctor`. Sao lưu: `voice-studio backup --out <file.zip>`.
Chuyển máy: `voice-studio export --personal --out <file.zip>` rồi `voice-studio import` ở máy mới.
