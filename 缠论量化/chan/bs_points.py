# -*- coding: utf-8 -*-
"""模块8：六大买卖点识别

输入：中枢数组 + 走势类型 + 背驰信号 + 分型数据（笔/线段）
输出：买卖点列表（type: 1B/2B/3B/1S/2S/3S, level, time, price, status, invalid）

通用规则：所有买卖点均需反向分型成立才正式确认（反向分型 = 走势单元末端分型），
未确认信号标记为 unconfirmed。

1B/1S：完整趋势 a+A+b+B+c 中 c 段相对 b 段背驰 + 末端反向分型
2B/2S：1B/1S 后的回踩/反弹确认（不破前低/前高），含强弱区分
3B/3S：中枢突破回踩（离开后回调不回到中枢区间）
"""
from .models import BSPoint


def find_bs_points(bis, zs_list, trends, beichis, level='stroke'):
    """识别全部买卖点。bis: 笔列表（作为时间/价格参考）"""
    points = []
    n = len(bis)

    def idx_of_time(dt):
        for k in range(n):
            if bis[k].end_time == dt:
                return k
        return -1

    def confirm_status(k, n, step=1):
        return 'confirmed' if k + step < n else 'unconfirmed'

    # ---- 1B / 1S：趋势背驰 ----
    for bc in beichis:
        c_idx = idx_of_time(bc.time)
        if c_idx < 0:
            continue
        if bc.type == 'bottom':
            points.append(BSPoint(type='1B', level=level, time=bc.time,
                                  price=bc.price,
                                  status=confirm_status(c_idx, n),
                                  desc=f"趋势底背驰({bc.method})：{bc.compare_segments[1]}"))
        else:
            points.append(BSPoint(type='1S', level=level, time=bc.time,
                                  price=bc.price,
                                  status=confirm_status(c_idx, n),
                                  desc=f"趋势顶背驰({bc.method})：{bc.compare_segments[1]}"))

    # ---- 失效标记：1B 后续创新低（背驰失败作废）；1S 后续创新高 ----
    for p in [x for x in points if x.type in ('1B', '1S')]:
        c_idx = idx_of_time(p.time)
        if c_idx < 0:
            continue
        for k in range(c_idx + 1, n):
            bk = bis[k]
            if p.type == '1B' and not bk.is_up and bk.low < p.price:
                p.invalid = True
                p.desc += "（失效：后续创新低，背驰失败）"
                break
            if p.type == '1S' and bk.is_up and bk.high > p.price:
                p.invalid = True
                p.desc += "（失效：后续创新高，背驰失败）"
                break

    # ---- 2B / 2S：1B/1S 后回踩确认（含强弱区分）----
    # 记录 1B/1S 对应的最后一个下跌/上升中枢（用于强弱判断）
    last_down_zd = None
    last_up_zg = None
    for z in zs_list:
        if not z.is_up:
            last_down_zd = z.ZD   # 最后一个下降中枢 ZD
        else:
            last_up_zg = z.ZG     # 最后一个上升中枢 ZG
    for p in [x for x in points if x.type in ('1B', '1S') and not x.invalid]:
        c_idx = idx_of_time(p.time)
        if c_idx < 0 or c_idx + 2 >= n:
            continue
        reb, call = bis[c_idx + 1], bis[c_idx + 2]
        if p.type == '1B':
            if reb.is_up and not call.is_up and call.low > p.price:
                strength = ''
                if last_down_zd is not None:
                    strength = '强' if call.low > last_down_zd else '弱'
                points.append(BSPoint(
                    type='2B', level=level, time=call.end_time, price=call.low,
                    status=confirm_status(c_idx, n, 3), strength=strength,
                    desc=f"一买后回踩不破前低（{call.low:.3f} > 一买{p.price:.3f}）"
                         + (f"【{strength}二买】" if strength else "")))
        else:
            if not reb.is_up and call.is_up and call.high < p.price:
                strength = ''
                if last_up_zg is not None:
                    strength = '强' if call.high < last_up_zg else '弱'
                points.append(BSPoint(
                    type='2S', level=level, time=call.end_time, price=call.high,
                    status=confirm_status(c_idx, n, 3), strength=strength,
                    desc=f"一卖后反弹不破前高（{call.high:.3f} < 一卖{p.price:.3f}）"
                         + (f"【{strength}二卖】" if strength else "")))

    # ---- 3B / 3S：中枢突破回踩 ----
    for zs in zs_list:
        # 中枢末单元之后的笔
        last_unit = zs.units[-1]
        bl_idx = idx_of_time(last_unit.end_time)
        if bl_idx < 0:
            continue
        for k in range(bl_idx, min(bl_idx + 3, n - 1)):
            bk = bis[k]
            if zs.is_up:
                if bk.is_up and bk.high > zs.ZG and k + 1 < n                         and not bis[k + 1].is_up and bis[k + 1].low > zs.ZG:
                    call = bis[k + 1]
                    points.append(BSPoint(
                        type='3B', level=level, time=call.end_time, price=call.low,
                        status=confirm_status(k, n, 2),
                        desc=f"向上离开中枢后回调低点{call.low:.3f} > 上沿{zs.ZG:.3f}"))
                    break
            else:
                if not bk.is_up and bk.low < zs.ZD and k + 1 < n                         and bis[k + 1].is_up and bis[k + 1].high < zs.ZD:
                    call = bis[k + 1]
                    points.append(BSPoint(
                        type='3S', level=level, time=call.end_time, price=call.high,
                        status=confirm_status(k, n, 2),
                        desc=f"向下离开中枢后反弹高点{call.high:.3f} < 下沿{zs.ZD:.3f}"))
                    break

    # 去重 + 排序
    seen = set()
    out = []
    for p in sorted(points, key=lambda x: x.time):
        key = (p.type, p.time)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out