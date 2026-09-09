# -*- coding: utf-8 -*-
import akshare as ak
import pandas as pd

df = ak.stock_zh_a_hist(
    symbol="000001", period="daily",
    start_date="20260401", end_date="20260515",
    adjust="qfq",
)
print("akshare qfq 列:", list(df.columns))
print()
print(df.to_string())
