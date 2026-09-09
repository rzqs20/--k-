# -*- coding: utf-8 -*-
"""尝试多个数据源拉取前复权真值：新浪源 akshare + tushare"""
import time, os
import pandas as pd

result = None
source = ""

# 1) akshare 新浪源
try:
    import akshare as ak
    for attempt in range(5):
        try:
            df = ak.stock_zh_a_daily(symbol="sz000001", start_date="20240801",
                                     end_date="20260909", adjust="qfq")
            if df is not None and len(df) > 100:
                result = df; source = "akshare-sina"
                break
        except Exception as e:
            print(f"akshare-sina 第{attempt+1}次失败: {type(e).__name__}")
            time.sleep(3)
except Exception as e:
    print("akshare 导入失败:", e)

# 2) tushare
if result is None:
    try:
        import tushare as ts
        tok = os.environ.get("TUSHARE_TOKEN", "")
        if not tok:
            # 常见本地配置
            for p in [r"C:\Users\xyz\.tushare_token", r"C:\Users\xyz\tushare_token.txt",
                      os.path.expanduser("~/.tushare/token"), "tushare_token.txt"]:
                if os.path.exists(p):
                    tok = open(p).read().strip()
                    break
        if tok:
            ts.set_token(tok)
            pro = ts.pro_api()
            df = pro.daily(ts_code="000001.SZ", start_date="20240801", end_date="20260909")
            if df is not None and len(df) > 100:
                # 前复权：daily * adj_factor/最新adj_factor
                af = pro.adj_factor(ts_code="000001.SZ", start_date="20240801", end_date="20260909")
                latest_af = af["adj_factor"].max()
                m = df.merge(af[["trade_date", "adj_factor"]], on="trade_date")
                m["open"] = m["open"] * m["adj_factor"] / latest_af
                m["date"] = pd.to_datetime(m["trade_date"]).dt.strftime("%Y-%m-%d")
                result = m[["date", "open"]]; source = "tushare"
                print("tushare token 可用")
        else:
            print("tushare 无 token，跳过")
    except Exception as e:
        print("tushare 失败:", type(e).__name__, e)

if result is None:
    raise SystemExit("所有在线源失败")
print(f"数据源: {source}, {len(result)} 天")

# 与数据库 front 对比
import duckdb
con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)
db = con.execute("""SELECT CAST(time AS DATE) AS d, open_front, open AS raw_open FROM kline_1d
                    WHERE time >= '2024-08-01' ORDER BY time""").fetchdf()
con.close()
db["d"] = db["d"].astype(str)

result = result.rename(columns={"open": "truth_open"})
result["date"] = result["date"].astype(str)
db["d"] = db["d"].astype(str)
m = db.merge(result[["date", "truth_open"]], left_on="d", right_on="date", how="inner")
m["db_err"] = m["open_front"] - m["truth_open"]
print(f"对比 {len(m)} 天，基准={source}")
print(f"数据库 front 平均绝对误差: {m['db_err'].abs().mean():.4f}，一致天数: {(m['db_err'].abs()<0.005).sum()}")
print(f"数据库 front 相对真值偏差中位数: {m['db_err'].median():.4f}")
print("\n关键日期:")
for t in ["2024-08-19", "2025-04-30", "2026-04-30", "2026-05-06", "2026-06-12", "2026-09-09"]:
    row = m[m["d"] == t]
    if len(row):
        r = row.iloc[0]
        print(f"{t}: 真值(新浪qfq)={r['truth_open']:.3f} | 数据库front={r['open_front']:.3f} | 差={r['db_err']:+.3f}")
m.to_csv(r"D:\量化k线\筹码结构类\docs\truth_compare.csv", index=False)
print("已保存 docs/truth_compare.csv")
