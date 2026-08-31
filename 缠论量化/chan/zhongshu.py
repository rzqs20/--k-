# -*- coding: utf-8 -*-
"""模块5：中枢识别（支持笔中枢/线段中枢）

输入：对应级别的走势单元列表（笔数组→笔中枢；线段数组→线段中枢）
输出：中枢列表（index/level/direction/start_time/end_time/ZD/ZG/unit_count/status）

规则：
1. 中枢 = 连续3个次级别走势单元的价格重叠区间
   ZD = max(3单元 low)，ZG = min(3单元 high)，ZD <= ZG 成立
2. 方向 = 进入中枢的第一个单元方向（向下→下降中枢 / 向上→上升中枢）
3. 延伸：后续单元与 [ZD,ZG] 有交集 → 延伸（unit_count+1，区间不变）
4. 终结（第三类买卖点）：
   - 上升中枢：单元向上离开后，回抽单元低点 > ZG → 三买，终结
   - 下降中枢：单元向下离开后，回抽单元高点 < ZD → 三卖，终结
5. 扩展：前后两个独立中枢价格重叠 → 合并为更高级别
   新区间 = [min(两ZD), max(两ZG)]
"""
from .models import ZhongShu


def _inter(unit, zg, zd):
    """单元与中枢区间是否有交集"""
    return min(unit.high, zg) - max(unit.low, zd) > 1e-9


def find_zhongshu(units, level='stroke'):
    """识别中枢。units 元素需有 direction/high/low/start_time/end_time"""
    zs_list = []
    i = 0
    n = len(units)
    while i < n - 2:
        u0, u1, u2 = units[i], units[i + 1], units[i + 2]
        # 方向交替（u0,u2 同向）
        if not (u0.direction != u1.direction and u1.direction != u2.direction):
            i += 1
            continue
        ZD = max(u0.low, u1.low, u2.low)
        ZG = min(u0.high, u1.high, u2.high)
        if ZD > ZG:
            i += 1
            continue
        direction = 'up' if u0.direction == 'up' else 'down'
        cand = [u0, u1, u2]
        j = i + 3
        while j < n:
            u = units[j]
            if _inter(u, ZG, ZD):
                cand.append(u)
                j += 1
                continue
            # 无交集：离开单元，三类买卖点终结判定
            if direction == 'up':
                if u.direction == 'up':
                    # 向上离开：后续回抽单元低点 > ZG → 三买终结
                    if j + 1 < n and units[j + 1].direction == 'down'                             and units[j + 1].low > ZG:
                        break
                    # 回抽回中枢 → 延伸
                    if j + 1 < n and _inter(units[j + 1], ZG, ZD):
                        cand.append(u)
                        cand.append(units[j + 1])
                        j += 2
                        continue
                break
            else:  # 下降中枢
                if u.direction == 'down':
                    if j + 1 < n and units[j + 1].direction == 'up'                             and units[j + 1].high < ZD:
                        break
                    if j + 1 < n and _inter(units[j + 1], ZG, ZD):
                        cand.append(u)
                        cand.append(units[j + 1])
                        j += 2
                        continue
                break
        zs = ZhongShu(
            index=len(zs_list) + 1,
            level=level,
            direction=direction,
            start_time=cand[0].start_time,
            end_time=cand[-1].end_time,
            ZD=ZD, ZG=ZG,
            unit_count=len(cand),
            status='finished',
            units=cand,
            gg=max(u.high for u in cand),
            dd=min(u.low for u in cand),
        )
        zs_list.append(zs)
        i = j

    # 扩展：相邻中枢价格重叠 → 合并为更高级别
    merged = []
    for zs in zs_list:
        if merged:
            last = merged[-1]
            if min(last.ZG, zs.ZG) - max(last.ZD, zs.ZD) > 1e-9:
                # 合并：区间 = [min ZD, max ZG]，单元拼接
                all_u = last.units + zs.units
                merged[-1] = ZhongShu(
                    index=last.index, level=last.level,
                    direction=last.direction,
                    start_time=last.start_time, end_time=zs.end_time,
                    ZD=min(last.ZD, zs.ZD), ZG=max(last.ZG, zs.ZG),
                    unit_count=len(all_u), status='finished',
                    units=all_u,
                    gg=max(last.gg, zs.gg), dd=min(last.dd, zs.dd),
                )
                continue
        merged.append(zs)
    return merged
