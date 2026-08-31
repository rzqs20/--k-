# -*- coding: utf-8 -*-
"""模块1：K线包含关系处理（复制 chan_trend.py / czsc 逻辑）

方向判定：只看 high 比较（k1.high < k2.high → 向上；k1.high > k2.high → 向下；相等不合并）
包含判定：k2 与 k3 高低点互相覆盖
合并：向上 high=max(low=max)；向下 high=min(low=min)
增量流程：每根新K线与队列倒数第二、倒数第一做一次 remove_include（与 czsc CZSC 一致，不循环合并）
"""
from .models import KLine


def _new(k):
    return KLine(time=k.time, open=k.open, high=k.high, low=k.low,
                 close=k.close, volume=k.volume, amount=k.amount,
                 elements=[k])


def remove_include(k1, k2, k3):
    """去除包含关系。输入 k1,k2 为无包含相邻K线，k3 为原始新K线。
    返回 (has_include, NewBar/KLine)  —— 复制 chan_trend.py remove_include"""
    if k1.high < k2.high:
        direction = 'up'
    elif k1.high > k2.high:
        direction = 'down'
    else:
        return False, _new(k3)

    has_inclusion = (k2.high <= k3.high and k2.low >= k3.low) or                     (k2.high >= k3.high and k2.low <= k3.low)
    if not has_inclusion:
        return False, _new(k3)

    if direction == 'up':
        high = max(k2.high, k3.high)
        low = max(k2.low, k3.low)
        t = k2.time if k2.high > k3.high else k3.time
    else:
        high = min(k2.high, k3.high)
        low = min(k2.low, k3.low)
        t = k2.time if k2.low < k3.low else k3.time

    open_, close = (high, low) if k3.open > k3.close else (low, high)
    elements = [x for x in k2.elements if x.time != k3.time] + [k3]
    merged = KLine(time=t, open=open_, high=high, low=low, close=close,
                   volume=k2.volume + k3.volume, amount=k2.amount + k3.amount,
                   elements=elements)
    return True, merged


def process_inclusion(klines):
    """K线包含关系处理（czsc 增量逻辑：每根K线合并一次，不循环）
    返回处理后K线列表"""
    result = []
    for k in klines:
        if len(result) < 2:
            result.append(_new(k))
            continue
        k1, k2 = result[-2], result[-1]
        has_inc, merged = remove_include(k1, k2, k)
        if has_inc:
            result[-1] = merged
        else:
            result.append(_new(k))
    return result
