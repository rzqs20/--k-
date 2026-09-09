# -*- coding: utf-8 -*-
import akshare as ak

df = ak.stock_zh_a_daily(symbol="sz000001", start_date="20260420", end_date="20260515", adjust="qfq")
print(df.to_string())
print("\n列:", list(df.columns))
print("dtypes:", df.dtypes.to_dict())
# 单位校验
row = df[df["date"] == "2026-04-30"].iloc[0]
print(f"\n2026-04-30: open={row['open']} close={row['close']} volume={row['volume']} amount={row['amount']}")
print(f"outstanding_share={row['outstanding_share']} turnover={row['turnover']}")
print(f"amount/volume = {row['amount']/row['volume']:.4f}  (若为元/股应≈close {row['close']})")
print(f"turnover×outstanding_share/100 / volume = {row['turnover']*row['outstanding_share']/100/row['volume']:.4f} (≈1 则 turnover单位是%且volume=股)")
print(f"turnover×outstanding_share/10000 / volume = {row['turnover']*row['outstanding_share']/10000/row['volume']:.4f} (≈1 则 turnover是%且volume=手)")
