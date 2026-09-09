# -*- coding: utf-8 -*-
import duckdb
con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)

print("=== 2026-03-20 ~ 2026-06-30：原始 vs front vs back ===")
df = con.execute("""SELECT time, open, close, open_front, close_front, open_back,
                    ROUND(close_front/close, 4) AS f_ratio
                    FROM kline_1d
                    WHERE time BETWEEN '2026-03-20' AND '2026-06-30'
                    ORDER BY time""").fetchdf()
print(df.to_string())

print("\n=== 2026-04-30 精确值 ===")
r = con.execute("""SELECT open, high, low, close, open_front, high_front, low_front, close_front
                   FROM kline_1d WHERE time BETWEEN '2026-04-30 00:00:00' AND '2026-04-30 23:59:59'""").fetchone()
print("原始 open/high/low/close =", r[:4])
print("front open/high/low/close =", r[4:])
con.close()
