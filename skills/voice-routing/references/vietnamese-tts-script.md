# Viết kịch bản để engine TTS tiếng Việt đọc đúng

Mọi quy tắc ở đây đều đã được **đo**, không phải đoán: văn bản được tổng hợp thành tiếng, rồi
Whisper phiên âm ngược audio đó, và cột "engine đọc thành" là thứ nó nghe ra. Quy tắc nào chưa
đo thì ghi rõ là chưa đo.

Đo trên OmniVoice 0.2.1 với clip tham chiếu dài 18 giây. Trên engine khác, chi tiết sẽ khác,
nhưng *dạng lỗi* thì lặp lại: ký tự phân cách bị nuốt, từ viết tắt dính vào chữ số liền kề,
và mảnh câu ngắn đứng riêng thì render chập chờn.

---

## 1. Việc cần làm

Văn bản thô → kịch bản để nói. **Không phải chép lại văn bản viết.** Văn viết để đọc bằng mắt
và văn viết để đọc thành tiếng là hai thứ khác nhau; ghép nối các câu của một bài báo sẽ cho
ra nhịp đọc phẳng như đọc danh sách — thứ ai cũng nhận ra là giọng máy.

Viết lại trước, rồi áp các quy tắc dưới đây, rồi gắn marker, rồi kiểm tra.

## 2. Bảng phát âm

| Trường hợp | Viết SAI | Engine đọc thành | Viết ĐÚNG |
|---|---|---|---|
| **Số phiên bản** | `GLM-5.3` | "GLM-53" — mất `.3` | `GLM phiên bản 5.3` |
| | `GLM 5.3` | "GOM53" — cả cụm bị méo | |
| | `GPT 5.2` | "GPT-52" | `GPT phiên bản 5.2` |
| **Giờ** | `14:30` | "14.30" — mất chữ "giờ" | `14 giờ 30` |
| **Ngày** | `22/8/2026` | "22.8.2026" — mất dấu gạch chéo | `22 tháng 8 năm 2026` |
| **Tên miền** | `Z.ai` | **"Z đây"** — sai hẳn | `Z chấm AI` |
| **Hàng nghìn** | — | đúng | `2.436` *hoặc* `2436` — cả hai đều được |
| **Số viết bằng chữ** | — | đúng | `hai nghìn bốn trăm ba mươi sáu` — cũng được |
| **Tiền** | — | đúng | `1.250.000 đồng` |
| **Phần trăm** | — | đọc thành "phần trăm" | `15%` |
| **Thuật ngữ công nghệ tiếng Anh phổ biến** | — | đúng | `API`, `OpenAI`, `Microsoft`, `Google` — để nguyên |

### Quy tắc nằm bên dưới bảng

**Từ viết tắt dính sát vào số sẽ dính liền và méo.** `GLM 5.3` → "GOM53",
`GPT 5.2` → "GPT-52". Chèn một từ thường vào giữa là hết:
`GLM phiên bản 5.3` đọc đúng. Đây là dòng hữu ích nhất trong tài liệu này — nó áp cho tên
model, phiên bản sản phẩm, tiêu chuẩn, bất cứ thứ gì có dạng `CHỮ CÁI + chữ số`.

**Ký tự phân cách bị nuốt.** `:` `/` `.` trong giờ, ngày và số phiên bản biến mất. Viết chúng
thành chữ: `giờ`, `tháng`, `năm`, `chấm`.

**Số trơn thì an toàn.** Cả chữ số lẫn số viết bằng chữ đều đọc đúng, kể cả dấu chấm hàng
nghìn kiểu Việt. Để nguyên.

> **Một quy tắc đã bị thay thế, giữ lại vì lý do của nó quan trọng.** Bản trước của ghi chú
> này bắt buộc giữ số ở dạng chữ số vì số viết bằng chữ bị nén lại
> ("một nghìn một trăm bốn mươi mốt" co thành "141"). Đo lại với một clip tham chiếu tốt:
> **cả hai dạng đều đúng.** Lỗi gốc chưa bao giờ nằm ở cách viết — mà ở một clip tham chiếu
> chỉ dài vài giây. Clip ngắn làm giảm chất lượng mọi thứ, và triệu chứng tình cờ lộ ra ở con
> số trước. Khi một quy tắc có vẻ là về văn bản, hãy kiểm xem thực ra nó có phải về clip không.

**Không bao giờ bật bộ chuẩn hoá văn bản của engine cho tiếng Việt.** Trong OmniVoice,
`normalize_text` đưa zh/en qua một bộ chuẩn hoá đúng nghĩa, còn mọi ngôn ngữ khác đi qua một
regex chỉ biết `\d+`. Dấu chấm hàng nghìn kiểu Việt bị vỡ thành mảnh — tệ hơn không chuẩn hoá.
Luôn tắt.

### Từ nước ngoài — chuẩn hoá ngay trong kịch bản, mỗi lần viết

Agent tự chuẩn hoá từ tiếng Anh (và ngôn ngữ khác) **trong chính đoạn thoại đang làm, trước khi
chạy model**. Không lập hay tra từ điển dùng chung: mỗi kịch bản tự xử lý, vì cùng một từ có
thể đọc khác nhau tuỳ câu và seed.

Đo ngày 22/11/2026, OmniVoice 0.6.0, giọng nền clip khoảng 16 giây: 25 thuật ngữ Data/AI,
145 cách viết, mỗi cách 2 seed, ASR Whisper nghe lại bằng cả `vi` và `en`.

| Loại từ | Cách viết | Ví dụ đã đo |
|---|---|---|
| Thuật ngữ, tên sản phẩm phổ biến | **để nguyên chữ gốc** | `Power BI`, `Power Query`, `Excel`, `Python`, `dashboard`, `measure`, `data model`, `pipeline`, `Copilot`, `ChatGPT`, `Lakehouse`, `insight`, `prompt`: đúng |
| Viết tắt đọc từng chữ cái | để nguyên, viết hoa | `KPI`, `SQL`, `ETL`, `API`, `AI`: đúng |
| Từ đọc liền như một từ nhưng viết hoa toàn bộ | **chỉ viết hoa chữ đầu** | `DAX` → "Dex/Desk" (0/6 lần đúng); `Dax` → đúng 5/6. `CALCULATE` chập chờn; `Calculate` ổn |
| Ghép chữ cái với một từ (`SUMX`) | viết tách theo âm, nên viết lại câu để từ không đứng một mình | `SUMX` → "Zoom X"; `Sam-ếch` ổn định nhưng nguyên âm lệch; chưa có cách viết đạt hẳn |

**Không phiên âm kiểu Việt khi chưa đo.** Phiên âm thường làm tệ hơn: `pai-lai` nghe ra "byline",
`lây-hao` ra "layout", `in-sai` ra "inside". Chỉ phiên âm khi bản viết gốc đo ra sai **và** bản
phiên âm đo ra đúng.

Các bước cho mỗi kịch bản:
1. Liệt kê mọi từ nước ngoài trong đoạn thoại.
2. Áp bảng trên. Từ chưa có trong bảng thì để nguyên chữ gốc.
3. Tổng hợp, rồi ASR nghe lại **theo câu** (mỗi đoạn dưới 30 giây, vì ASR bịa câu ở mép khối 30 giây).
4. Từ nào nghe ra sai: thử 2–3 cách viết với seed ghim, giữ cách đo ra đúng.
5. Ghi trong báo cáo những từ đã đổi cách viết.

ASR chỉ chứng minh từ **nhận ra được**, không chứng minh đọc đúng giọng Anh. Nếu người nghe báo
một từ vẫn lơ lớ dù ASR nghe đúng, thì tai người quyết định: thử cách viết khác cho riêng từ đó.

### Chưa đo — kiểm khi gặp

Tên riêng nước ngoài ít gặp (một lần thử nghe `Claude` thành "Cloud", và không rõ engine phát
âm sai hay ASR nghe nhầm); đơn vị như `km/h` và `GB`; số La Mã.

## 3. Marker

```
[marker-name] First sentence. Second sentence.
[other-marker] Now the delivery changes.
```

Một marker giữ hiệu lực **đến marker kế tiếp**. Đoạn không gắn marker dùng clip trung tính
của profile.

Tên marker lấy từ profile, không phải tự nghĩ ra — đọc `<profile>.profile.json` trong thư mục giọng (`profiles/<profile>/voice/`) trước, hoặc `voice-studio profiles list --json` để biết giọng có bao nhiêu marker.
Marker không có trong manifest sẽ bị gỡ bỏ và đoạn đó quay về marker đang có hiệu lực, chỉ
được báo bằng một dòng console rất dễ bỏ qua.

Chọn theo **ý nghĩa**, không rải cho có biến hoá: câu mở móc (hook), nhấn mạnh hoặc kết luận,
kể chuyện nhỏ nhẹ, liệt kê nhanh, giải thích thông thường.

### Phân bổ sắc thái theo bố cục video

Khi profile được dựng từ bộ thu theo tình huống, manifest có 8 marker: `trung-tinh`,
`giai-thich`, `gan-gui`, `nhan-manh`, `hao-hung`, `ke-chuyen`, `hoi-dap`, `tram-lang`. Đọc
manifest trước; profile thiếu marker nào thì bỏ dòng đó trong bảng, không tự đặt tên.

| Phần của video | Marker chính | Marker đi kèm |
|---|---|---|
| Mở đầu, câu móc | `hao-hung` | `gan-gui` khi chào người xem |
| Dàn bài, chuyển phần, hướng dẫn thao tác | `trung-tinh` | — |
| Giảng khái niệm, đi từng bước | `giai-thich` | `trung-tinh` cho câu nối |
| Ví dụ thực tế, tình huống dự án | `ke-chuyen` | — |
| Câu hỏi tu từ, hỏi–đáp | `hoi-dap` | `giai-thich` cho lời đáp dài |
| Chốt ý, cảnh báo sai lầm | `nhan-manh` | — |
| Động viên, kêu gọi hành động | `gan-gui` | — |
| Suy ngẫm, kết bài | `tram-lang` | `trung-tinh` cho câu chào cuối (hoặc để câu chào nằm luôn trong đoạn `tram-lang`; không đặt `gan-gui` liền sau `tram-lang` — hai marker này thường đo ra khó phân biệt) |

Quy ước biên tập (chưa đo bằng số, kiểm bằng tai khi giao):

1. **Đủ sắc thái.** Video từ khoảng 3 phút (khoảng 30 câu) trở lên dùng đủ 8 marker, mỗi marker ít
   nhất một đoạn. Video ngắn hơn dùng ít nhất 5 marker, luôn có `hao-hung` ở mở và
   `nhan-manh` hoặc `tram-lang` ở kết.
2. **Không marker nào chiếm quá 35 % số câu.** `trung-tinh` và `giai-thich` thường nhiều nhất,
   cộng lại không quá 60 %.
3. **Nhịp đổi.** Một đoạn marker dài 1–5 câu. Quá 5 câu liền (khoảng 30–40 giây) cùng một
   marker nghe đều đều. Đổi marker từng câu một thì nghe giật.
4. **Chọn theo ý nghĩa, không rải cho đủ.** Bài thiếu chỗ cho `ke-chuyen` hay `hoi-dap` thì
   viết thêm một ví dụ ngắn hoặc một câu hỏi tu từ thật, không gắn marker lên câu không hợp.
5. **Đọc báo cáo kiểm thử của profile** để biết cặp marker nào đo ra khó phân biệt. Đừng đặt
   cặp đó liền nhau khi muốn người nghe cảm thấy đổi giọng.
6. **In bảng phân bổ trong báo cáo giao:** marker · số câu · %. Câu đầu mỗi phần của video
   luôn có marker ghi rõ, không dựa vào marker còn hiệu lực từ phần trước.

Khung bài giảng 5 phút mẫu: `hao-hung` (2 câu) → `gan-gui` (1) → `trung-tinh` dàn bài (2) →
`giai-thich` (4) → `ke-chuyen` (3) → `hoi-dap` (2) → `giai-thich` (3) → `nhan-manh` (2) →
`trung-tinh` chuyển phần (1) → `giai-thich` (4) → `nhan-manh` tóm tắt (2) → `tram-lang` (3, kể cả
câu chào cuối). Kết bằng `nhan-manh` tóm tắt rồi `tram-lang`; nếu cần tách riêng câu chào cuối thì
dùng `trung-tinh`, không dùng `gan-gui`.

**Tag phi ngôn ngữ** — các âm nội tuyến của chính engine như tiếng cười, thở dài và thán từ
ngạc nhiên — được chuyển thẳng qua, và yếu. Chúng là tiếng động rời rạc; không diễn đạt được
"đọc cả đoạn này trầm hơn". Dùng tiết chế; trong văn bản tin tức chúng nghe giả rất nhanh.

## 4. Seed

Pin một seed. Engine không tái lập được nếu thiếu nó, và một phép A/B không pin seed đo nhiễu
lấy mẫu chứ không đo thay đổi của bạn. Chi tiết ở `engine-limits.md`.

Seed không làm giọng hay hơn — nó làm một lần render lặp lại được. Các lần lấy mẫu khác nhau
*đúng là* có lần tốt lần kém, nên dò seed là một kỹ thuật thật, nhưng máy chỉ **loại được lần
lấy mẫu hỏng** (lỗi ASR cao). Không có chỉ số nào cho biết lần nào nghe người hơn. Chỉ dò seed
cho những câu trượt cổng ASR; đừng dò cho tất cả.

## 5. Kiểm trước khi bàn giao

1. Không còn ngoặc lạc — mọi marker đều có trong manifest, mọi tag đều là tag thật của engine.
2. **Không có mảnh câu ngắn đứng một mình.** Tiêu đề, nhãn hay một con số trơn render riêng
   sẽ chập chờn: token đầu bị méo hoặc một từ bị nuốt. Gộp nó vào đầu một câu dài hơn.
3. Câu quá dài (khoảng trên 380 ký tự) tách tại dấu phẩy, không bao giờ tách giữa cụm từ.
4. Mọi từ nước ngoài đã qua các bước ở mục "Từ nước ngoài".
5. Profile nhiều sắc thái: phân bổ marker đạt quy ước ở mục "Phân bổ sắc thái theo bố cục video".
6. Tổng hợp → ASR ngược lại → tỉ lệ lỗi ký tự (CER) trên 0.25 nghĩa là sửa *cách viết* của
   phần đó rồi thử lại.

## 6. Ví dụ hoàn chỉnh

**Thô:**
> Z.ai công bố GLM-5.3 ngày 14/8/2026. Mô hình đã phát hiện 2.436 lỗ hổng bảo mật, tăng 15% so với bản trước.

**Kịch bản:**
```
[hook] Ngày 14 tháng 8 năm 2026, công ty Z chấm AI công bố một mô hình mới.
[neutral] Nó tên là GLM phiên bản 5.3.
[emphasis] Và đây mới là con số đáng chú ý: mô hình này đã phát hiện 2.436 lỗ hổng bảo mật, tăng 15% so với bản trước.
```

Đã đổi: viết tên miền thành chữ · tách số phiên bản khỏi từ viết tắt · viết ngày bằng chữ ·
chia thành câu ngắn · gắn marker theo ý nghĩa. Để nguyên: `2.436` và `15%`, vì cả hai đều đã
đo là đúng.

*(Tên marker ở trên chỉ là ví dụ — dùng tên trong manifest của bạn.)*
