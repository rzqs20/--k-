# -*- coding: utf-8 -*-
"""模块2：顶底分型识别（复制 chan_trend.py / czsc 的 check_fx + check_fxs）

check_fx：三根无包含K线
  顶分型 = 中K高点最高 且 低点最高（k1.high < k2.high > k3.high 且 k1.low < k2.low > k3.low）
  底分型 = 中K低点最低 且 高点最低（k1.low > k2.low < k3.low 且 k1.high > k2.high < k3.high）
check_fxs：滑动窗口遍历所有三连K线，连续同向分型跳过（顶底交替）
"""
from .models import FenXing


def check_fx(k1, k2, k3):
    """三根无包含K线构成分型。返回 (type, time, price, high, low) 或 None"""
    if k1.high < k2.high > k3.high and k1.low < k2.low > k3.low:
        return ('top', k2.time, k2.high, k2.high, k2.low)
    if k1.low > k2.low < k3.low and k1.high > k2.high < k3.high:
        return ('bottom', k2.time, k2.low, k2.high, k2.low)
    return None


def check_fxs(klines):
    """扫描无包含K线序列，找出所有分型（强制顶底交替）"""
    fxs = []
    for i in range(len(klines) - 2):
        r = check_fx(klines[i], klines[i + 1], klines[i + 2])
        if r is None:
            continue
        ftype, t, price, high, low = r
        if fxs and ftype == fxs[-1].type:
            continue  # 顶底交替
        fxs.append(FenXing(type=ftype, time=t, price=price, k_index=i + 1,
                           high=high, low=low))
    return fxs


def find_fenxing(klines):
    """顶底分型识别（= check_fxs）"""
    return check_fxs(klines)
