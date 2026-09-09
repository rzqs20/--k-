# -*- coding: utf-8 -*-
import duckdb
con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)
r = con.execute("SELECT time, close, volume, amount FROM kline_1d ORDER BY time DESC LIMIT 1").fetchone()
print("2026-09-02: close=%s volume=%s amount=%s" % (r[1], r[2], r[3]))
print("amount/volume =", r[3] / r[2], " (元/手)")
print("amount/(volume*100) =", r[3] / r[2] / 100, " (元/股)")
print("若 volume 是股: amount/volume 应为股价附近 ->", r[3] / r[2], "≠ close", r[1])
print("若 volume 是手: amount/(vol*100) =", r[3] / r[2] / 100, "≈ close", r[1])
con.close()
