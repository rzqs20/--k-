# -*- coding: utf-8 -*-
import duckdb
con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)
print("=== kline_1d 完整列结构 ===")
print(con.execute("DESCRIBE kline_1d").fetchdf().to_string())
print("\n=== 全部表 ===")
print(con.execute("SHOW TABLES").fetchall())
con.close()
