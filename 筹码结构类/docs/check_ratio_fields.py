# -*- coding: utf-8 -*-
import duckdb
con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)

print("=== 2026-04-30 ~ 2026-05-08：front vs front_ratio vs back vs back_ratio ===")
df = con.execute("""SELECT time, open, close,
                    open_front, close_front,
                    open_front_ratio, close_front_ratio,
                    open_back, close_back,
                    open_back_ratio, close_back_ratio
                    FROM kline_1d
                    WHERE time BETWEEN '2026-04-28' AND '2026-05-08'
                    ORDER BY time""").fetchdf()
print(df.to_string())

# 2025-04-30 也看一眼（对比之前发现 2025 年 front 是对的）
print("\n=== 2025-04-30 ~ 2025-05-07 ===")
df2 = con.execute("""SELECT time, open, close,
                    open_front, close_front,
                    open_front_ratio, close_front_ratio
                    FROM kline_1d
                    WHERE time BETWEEN '2025-04-28' AND '2025-05-07'
                    ORDER BY time""").fetchdf()
print(df2.to_string())
con.close()
