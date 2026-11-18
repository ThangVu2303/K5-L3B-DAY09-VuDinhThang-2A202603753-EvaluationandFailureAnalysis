# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY: kết luận judge lưu sẵn trong CSV). Lớp dương = FAIL (việc của judge là tìm lỗi).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt | **dùng** (chỉ cho tiêu chí giọng văn, không chặn release) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không (κ, R) | **loại** |

Ma trận nhầm lẫn:
- tone_ok: TP 24 · FP 4 · FN 6 · TN 66. Tỉ lệ FAIL judge báo 0.28, sau hiệu chỉnh Rogan-Gladen là 0.30.
- helpful: TP 9 · FP 0 · FN 21 · TN 70. Tỉ lệ FAIL judge báo 0.09, sau hiệu chỉnh là 0.30. Judge chỉ thấy **1/3** số lỗi thật.

## ≥5 case audit thủ công (tone_ok, cộng 2 case helpful)

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã. Thêm vào rubric: *xưng hô phải là "LogiX" / "anh/chị"; "em", "bạn", "nha", "nhé" ⇒ FAIL*, kèm 1 ví dụ FAIL. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…" | PASS | FAIL | Người | Cùng lỗi xưng hô ("bạn ơi"). Luật xưng hô ở #1 sẽ phủ case này. |
| 3 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ nhìn kính ngữ đầu câu. Thêm: *câu mệnh lệnh / cấm khách liên hệ ("không cần nhắn thêm") ⇒ FAIL dù có "Dạ".* |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". Thêm: *xin lỗi không bắt buộc khi yêu cầu đã được giải quyết; ngắn mà đủ ý vẫn PASS.* |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | Người | CS LogiX cho phép từ "refund". Thêm danh sách từ mượn được phép (refund, ship, voucher). |
| 6 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Ghi chú CSV: người đọc nhầm ticket. Sửa **nhãn người**, không sửa rubric. Cần người thứ hai gán lại các nhãn có tranh chấp. |
| 7 | H-070 "…đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Thêm: *emoji trong phản hồi khiếu nại ⇒ FAIL.* |
| 8 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (helpful) | PASS | FAIL | Người | Ledger ghi 40.000đ. Judge không thấy ledger nên không thể biết reply nói sai. Đây là FM-08, phải chấm bằng code (`reply_matches_ledger`), không phải judge. |
| 9 | HL-016 xin lỗi dài + "đã hoàn 55.000đ" (helpful) | PASS | FAIL | Người | Ledger 35.000đ. Lời văn dài và nhiều xin lỗi khiến judge cho PASS (thiên vị độ dài/lịch sự). |

## Kết luận

- **helpful bị loại.** Recall 0.30: judge bỏ sót 21/30 câu trả lời không hữu ích, κ 0.375 < 0.6. Precision 1.0 không cứu được: judge hầu như không bao giờ nói FAIL, nên khi nói FAIL thì đúng, nhưng **gần như mọi lỗi đều lọt**. 18/21 ca bỏ sót có ghi chú "ledger ghi …": reply nói số tiền khác ledger, mà judge chỉ đọc text nên không thể kiểm. 3 ca còn lại là "Ok bạn, đơn … xử lý rồi nhé" (không nói kết quả). Dùng judge này làm gate sẽ **cho lọt đúng loại lỗi nguy hiểm nhất (sai tiền)** và tạo cảm giác an toàn giả. Thay thế: số tiền chấm bằng code (`reply_matches_ledger`, FM-08); phần "có nói rõ kết quả không" cần rubric mới và calibrate lại.
- **tone_ok dùng được** nhưng chỉ làm metric theo dõi, không chặn release. 6 FN (judge bỏ sót giọng văn kém) chủ yếu là xưng hô suồng sã và giọng mệnh lệnh, sửa được bằng các luật ở #1, #3, #7.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (người viết rubric đã thấy các case này). Cần nhãn người mới để có held-out thật, và cần người thứ hai gán lại để đo độ đồng thuận giữa người với người (case #6 cho thấy nhãn người cũng sai).
