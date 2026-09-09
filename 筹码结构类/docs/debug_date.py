# -*- coding: utf-8 -*-
import akshare as ak
import duckdb

df = ak.stock_zh_a_daily(symbol="sz000001", start_date="20240801", end_date="20260909", adjust="qfq")
print("列:", list(df.columns))
print("date 样例:", df["date"].head(3).tolist(), df["date"].dtype)
print("open 样例:", df["open"].head(3).tolist())

con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)
db = con.execute("SELECT CAST(time AS DATE) AS d FROM kline_1d WHERE time >= '2024-08-01' ORDER BY time LIMIT 3").fetchdf()
print("db d 样例:", db["d"].tolist(), db["d"].dtype)
con.close()
