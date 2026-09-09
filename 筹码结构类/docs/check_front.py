# -*- coding: utf-8 -*-
import duckdb
con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)

print("=== front 字段非空统计 ===")
r = con.execute("""SELECT COUNT(*) total,
  COUNT(open_front) AS of_c, COUNT(high_front) AS hf, COUNT(low_front) AS lf,
  COUNT(close_front) AS cf, COUNT(open) AS o_c, COUNT(close) AS c_c FROM kline_1d""").fetchone()
print(f"total={r[0]} open_front={r[1]} high_front={r[2]} low_front={r[3]} close_front={r[4]} open={r[5]} close={r[6]}")

print("\n=== front vs 原始 差异最大的 8 个日期 ===")
df = con.execute("""SELECT time, open, close, open_front, close_front,
  ROUND(ABS(open_front-open),3) AS d FROM kline_1d ORDER BY d DESC LIMIT 8""").fetchdf()
print(df.to_string())

print("\n=== 2024-08 前后 front vs 原始 ===")
df = con.execute("""SELECT time, open, open_front, close, close_front FROM kline_1d
  WHERE time BETWEEN '2024-07-25' AND '2024-08-05' ORDER BY time""").fetchdf()
print(df.to_string())

print("\n=== 2025-06~08 除权附近 ===")
df = con.execute("""SELECT time, open, open_front, close, close_front FROM kline_1d
  WHERE time BETWEEN '2025-06-20' AND '2025-07-15' ORDER BY time""").fetchdf()
print(df.to_string())
con.close()
