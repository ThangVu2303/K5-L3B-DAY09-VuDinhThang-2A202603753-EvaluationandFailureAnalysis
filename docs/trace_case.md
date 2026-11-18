# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

Output (rút gọn):

```text
== seeded_regression C-014@11  lab8 grader: FAIL (proposal_mismatch)
   2 investigator    {"lookup_order": {... "order_id": "O-515", "status": "delivered_late", ...}}
   3 quote           {"amount_vnd": 150000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03", "DMG-04"], ...}
   4 refund_history  {"refund_count": 1, "refunded_vnd": 30000}
   5 proposal        {"amount_vnd": 120000}
   6 reply           {"text": "Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."}
  refund_vnd     ledger=90000    label=120000   <-- differs

== fixed C-014@11  lab8 grader: PASS (ok)
   3 quote           {"amount_vnd": 150000, ...}
   4 reply           {"text": "Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."}
  refund_vnd     ledger=120000   label=120000
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, report `E-seeded_regression-20261118-93b1` (eval set `93b10a5744c7`) |
| Triệu chứng | `refund_amount_correct` fail (ledger 90.000, nhãn 120.000), `proposal_correct` fail (đề xuất 120.000, policy 150.000), `reply_matches_ledger` fail (reply nói 120.000, ledger ghi 90.000). Khách được báo một con số mà tài khoản sẽ không nhận được. |
| Bước sai đầu tiên | Event 5 `proposal {"amount_vnd": 120000}`: agent lấy quote 150.000 trừ 30.000 đã hoàn trước đó. |
| Vì sao là bước *đầu tiên* | Event 2 đọc đúng đơn O-515 (`damage_verified`, trễ 5 ngày). Event 3 quote 150.000 đúng nhãn `proposal_amount`. Event 4 chỉ *đọc* lịch sử hoàn, chưa sai. Event 5 là chỗ đầu tiên agent đổi số tiền: nó làm thay việc của host (host đã có luật "chỉ trả phần chênh"), nên khoản 30.000 bị trừ hai lần. Event 6 (reply) chỉ là hệ quả. |
| Failure mode | FM-05 `pre_deducted`, kéo theo FM-08 `misreport` |
| Đối chứng | `fixed C-014@11`: không có `refund_history`/`proposal`. Agent gửi đúng 150.000 cho host, host trừ 30.000, ledger 120.000 = nhãn, reply 120.000 = ledger. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_lab9_regression_c014_pre_deducted_is_caught` khẳng định 3 grader (`proposal_correct`, `reply_matches_ledger`, `refund_amount_correct`) cùng fail trên `seeded_regression`, và `test_lab9_regression_c014_fixed_passes` khẳng định cả 3 pass trên `fixed`. Đã chạy: 2/2 xanh (cùng bộ `-k "lab9 and not advanced"` mà CI chạy). |
| Chưa chắc chắn | Trace không có event riêng cho lần host trừ 30.000. Việc "host trừ lần hai" được suy ra từ ledger 90.000 = 120.000 − 30.000, chưa thấy trực tiếp. Mới kiểm seed 11; công tắc `pre_deducted` không phụ thuộc seed nên dự kiến cả 5 seed giống nhau (report xác nhận E-014 fail ở cả 5 seed). |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
