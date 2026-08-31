# -*- coding: utf-8 -*-
"""缠论量化逻辑 - 可配置参数"""

# ---- 全局容错 ----
# 所有价格比较的浮点容错阈值（0.01% = 0.0001）
PRICE_TOLERANCE = 0.0001

# ---- 数据 ----
KHDATA_ROOT = r"D:\khData"          # DuckDB 数据库根目录
PREWARM_BARS = 300                   # 分析预热K线数

# ---- 模块1：包含处理 ----

# ---- 模块2：分型 ----
# （分型筛选对齐 czsc check_fxs：连续同向跳过，无独立K线间隔约束）

# ---- 模块3：笔 ----
# 笔最小长度：两分型中K之间的去包含K线数（对应 czsc check_bi 的 min_bi_len=6）
MIN_BI_LEN = 6

# ---- 模块5：中枢 ----
# 中枢最小构成单元数（连续 N 个次级别走势单元重叠）
ZS_MIN_UNITS = 3
# 背驰容错（MACD 面积比较阈值，1.05 = 5% 容错）
DIV_TOLERANCE = 1.05

# ---- 模块7：背驰 ----
# MACD 参数
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ---- 模块8：买卖点 ----

# ---- 输出 ----
REPORTS_DIR = None   # 由 main 设置
