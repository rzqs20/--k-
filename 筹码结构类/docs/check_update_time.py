# -*- coding: utf-8 -*-
import duckdb
con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)

print("=== update_time 分布（按天）===")
df = con.execute("""SELECT CAST(update_time AS DATE) AS upd, COUNT(*) AS n
                    FROM kline_1d GROUP BY 1 ORDER BY 1 DESC LIMIT 10""").fetchdf()
print(df.to_string())

print("\n=== 2026-04-30 与 2026-05-06 的 update_time / turn / dividend_type ===")
df2 = con.execute("""SELECT time, update_time, turn, dividend_type, preClose, open, close, open_front, close_front
                     FROM kline_1d
                     WHERE time IN ('2026-04-30 09:30:00','2026-05-06 09:30:00','2026-09-09 09:30:00')
                     ORDER BY time""").fetchdf()
print(df2.to_string())

print("\n=== turn 非空统计（全表）===")
print(con.execute("SELECT COUNT(*) total, COUNT(turn) turn_nonnull FROM kline_1d").fetchone())

print("\n=== preClose 检查：5-06 preClose vs 4-30 close ===")
print(con.execute("""SELECT time, preClose, close FROM kline_1d
                     WHERE time IN ('2026-05-06 09:30:00','2026-06-12 09:30:00')""").fetchall())
con.close()
