# -*- coding: utf-8 -*-
"""模块6：走势类型划分

输入：模块5 的同级别中枢列表
输出：走势类型列表（type: trend_up/trend_down/consolidation, level, 时间, 价格, center_list）

规则：
1. 盘整：仅 1 个中枢
2. 上涨趋势：至少 2 个依次上移的上升中枢（后.ZG > 前.ZG）且中枢间无价格重叠
3. 下跌趋势：至少 2 个依次下移的下降中枢（后.ZD < 前.ZD）且中枢间无价格重叠
4. 走势终结：出现反向走势的第一个中枢时，原走势终结
"""
from .models import Trend


def _overlap(z1, z2):
    return min(z1.ZG, z2.ZG) - max(z1.ZD, z2.ZD) > 1e-9


def classify_trend(zs_list, level='stroke'):
    """划分走势类型"""
    trends = []
    cur = None  # {'type', 'centers'}
    for zs in zs_list:
        if cur is None:
            cur = {'type': 'consolidation', 'centers': [zs]}
            continue
        last = cur['centers'][-1]
        # 延续判断
        if cur['type'] == 'trend_up':
            if zs.direction == 'up' and zs.ZG > last.ZG and not _overlap(zs, last):
                cur['centers'].append(zs)
                continue
        elif cur['type'] == 'trend_down':
            if zs.direction == 'down' and zs.ZD < last.ZD and not _overlap(zs, last):
                cur['centers'].append(zs)
                continue
        elif cur['type'] == 'consolidation':
            # 盘整升级为趋势：第二个同向移动中枢
            if zs.direction == 'up' and zs.ZG > last.ZG and not _overlap(zs, last):
                cur = {'type': 'trend_up', 'centers': cur['centers'] + [zs]}
                continue
            if zs.direction == 'down' and zs.ZD < last.ZD and not _overlap(zs, last):
                cur = {'type': 'trend_down', 'centers': cur['centers'] + [zs]}
                continue
        # 无法延续：终结当前，开始新走势
        trends.append(_make_trend(cur, level))
        cur = {'type': 'consolidation', 'centers': [zs]}
    if cur:
        trends.append(_make_trend(cur, level))
    return trends


def _make_trend(cur, level):
    centers = cur['centers']
    first, last = centers[0], centers[-1]
    return Trend(
        type=cur['type'],
        level=level,
        start_time=first.start_time,
        end_time=last.end_time,
        start_price=first.units[0].start_price if first.units else 0.0,
        end_price=last.units[-1].end_price if last.units else 0.0,
        center_list=centers,
    )
