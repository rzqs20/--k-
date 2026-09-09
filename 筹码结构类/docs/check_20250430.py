# -*- coding: utf-8 -*-
import duckdb, re, json, sys
sys.path.insert(0, r"D:\量化k线\筹码结构类")

# 1) 数据库：2025-04-25 ~ 2025-05-09 原始 vs front
con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)
df = con.execute("""SELECT time, open, high, low, close,
                    open_front, high_front, low_front, close_front
                    FROM kline_1d
                    WHERE time BETWEEN '2025-04-25' AND '2025-05-09'
                    ORDER BY time""").fetchdf()
con.close()
print("=== 数据库 kline_1d: 原始 vs front（2025-04-25 ~ 05-09）===")
print(df.to_string())

# 2) 报告 HTML 里实际显示
html = open(r"D:\量化k线\筹码结构类\reports\000001_SZ_筹码结构_20260909.html", encoding="utf-8").read()
m = re.search(r"const DATA = (\{.*?\});\nconst bins", html, re.S)
data = json.loads(m.group(1))
dates = data["dates"]; kline = data["kline"]
print("\n=== 报告 HTML 中 2025-04-25 ~ 05-09 的 K 线 [open,close,low,high] ===")
for t in dates:
    if "2025-04-25" <= t <= "2025-05-09":
        i = dates.index(t)
        print(t, kline[i])
