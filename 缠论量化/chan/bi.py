# -*- coding: utf-8 -*-
"""模块3：笔的生成与确认（复制 chan_trend.py 的 CZSC 增量逻辑）

check_bi：从无包含K线序列识别一笔（fx_a 起分型，选反向极值 fx_b，
          bars_a 长度 >= MIN_BI_LEN 且分型无包含 → 成笔）
build_bis：逐根K线增量处理（去包含 + _update_bi），与旧程序 CZSC 完全一致
"""
import bisect

from .models import Bi, FenXing
from .fenxing import check_fxs
from .include import remove_include
from . import config


def _new(k):
    from .models import KLine
    return KLine(time=k.time, open=k.open, high=k.high, low=k.low,
                 close=k.close, volume=k.volume, amount=k.amount,
                 elements=[k])


def _fx_elem_time(bars, fx, pos):
    """分型第 pos 根K线的时间：elements[0]=中K前一根, [1]=中K, [2]=中K后一根"""
    idx = fx.k_index + (pos - 1)
    idx = max(0, min(idx, len(bars) - 1))
    return bars[idx].time


def check_bi(bars, min_bi_len=6):
    """从无包含K线序列中识别一笔（复制 chan_trend.py check_bi）。
    bars: 去包含K线列表（KLine）
    返回 (Bi or None, 剩余bars)"""
    fxs = check_fxs(bars)
    if len(fxs) < 2:
        return None, bars
    fx_a = fxs[0]
    if fx_a.type == 'bottom':
        cands = [x for x in fxs if x.type == 'top' and x.time > fx_a.time and x.price > fx_a.price]
        if not cands:
            return None, bars
        fx_b = max(cands, key=lambda x: x.high)
    else:
        cands = [x for x in fxs if x.type == 'bottom' and x.time > fx_a.time and x.price < fx_a.price]
        if not cands:
            return None, bars
        fx_b = min(cands, key=lambda x: x.low)

    dts = [b.time for b in bars]
    start_idx = bisect.bisect_left(dts, _fx_elem_time(bars, fx_a, 0))
    end_idx = bisect.bisect_right(dts, _fx_elem_time(bars, fx_b, 2))
    if start_idx >= end_idx:
        return None, bars
    bars_a = bars[start_idx:end_idx]

    new_start_idx = bisect.bisect_left(dts, _fx_elem_time(bars, fx_b, 0))
    bars_b = bars[new_start_idx:]

    ab_include = (fx_a.high > fx_b.high and fx_a.low < fx_b.low) or                  (fx_a.high < fx_b.high and fx_a.low > fx_b.low)

    if not ab_include and len(bars_a) >= min_bi_len:
        direction = 'up' if fx_a.type == 'bottom' else 'down'
        bi = Bi(
            index=0,
            direction=direction,
            start_time=fx_a.time,
            end_time=fx_b.time,
            start_price=fx_a.price,
            end_price=fx_b.price,
            high=max(b.high for b in bars_a),
            low=min(b.low for b in bars_a),
            is_confirmed=True,
            fx_start=fx_a,
            fx_end=fx_b,
            bars=bars_a,
        )
        return bi, bars_b
    return None, bars


def _update_bi(bis, bars_ubi, min_bi_len):
    """成笔增量逻辑（复制 chan_trend.py CZSC._update_bi）"""
    if len(bars_ubi) < 3:
        return
    if not bis:
        fxs = check_fxs(bars_ubi)
        if not fxs:
            return
        first = fxs[0]
        if first.type == 'bottom':
            fx_a = min([x for x in fxs if x.type == 'bottom'], key=lambda x: x.low)
        else:
            fx_a = max([x for x in fxs if x.type == 'top'], key=lambda x: x.high)
        dts = [b.time for b in bars_ubi]
        idx = bisect.bisect_left(dts, _fx_elem_time(bars_ubi, fx_a, 0))
        bars = bars_ubi[idx:]
        bi, rest = check_bi(bars, min_bi_len)
        if bi:
            bi.index = len(bis) + 1
            bis.append(bi)
        bars_ubi[:] = rest
        return

    bi, rest = check_bi(bars_ubi, min_bi_len)
    if bi:
        bi.index = len(bis) + 1
        bis.append(bi)
    bars_ubi[:] = rest

    # 笔破坏后处理：未完成笔超出最后一笔极值 → 合并回退
    if not bis or not bars_ubi:
        return
    last_bi = bis[-1]
    if last_bi.direction == 'up' and bars_ubi[-1].high > last_bi.high:
        merge_point = last_bi.bars[-2].time
        merged = list(last_bi.bars[:-2]) +                  [b for b in bars_ubi if b.time >= merge_point]
        bars_ubi[:] = merged
        bis.pop()
    elif last_bi.direction == 'down' and bars_ubi[-1].low < last_bi.low:
        merge_point = last_bi.bars[-2].time
        merged = list(last_bi.bars[:-2]) +                  [b for b in bars_ubi if b.time >= merge_point]
        bars_ubi[:] = merged
        bis.pop()


def generate_bi(raw_klines, min_bi_len=None):
    """增量生成笔（复制 chan_trend.py CZSC.update_bar 流程）。
    返回 (笔列表, 未完成笔 或 None)"""
    min_bi_len = min_bi_len or config.MIN_BI_LEN
    bis = []
    bars_ubi = []
    for k in raw_klines:
        # 去包含（单次合并，czsc 逻辑）
        if len(bars_ubi) < 2:
            bars_ubi.append(_new(k))
        else:
            has_inc, merged = remove_include(bars_ubi[-2], bars_ubi[-1], k)
            if has_inc:
                bars_ubi[-1] = merged
            else:
                bars_ubi.append(_new(k))
        # 成笔
        _update_bi(bis, bars_ubi, min_bi_len)
    # 未完成笔
    unfinished = None
    if bars_ubi and bis:
        last_bi = bis[-1]
        direction = 'up' if last_bi.direction == 'down' else 'down'
        if bars_ubi:
            unfinished = Bi(
                index=len(bis) + 1, direction=direction,
                start_time=bars_ubi[0].time, end_time=bars_ubi[-1].time,
                start_price=bars_ubi[0].open, end_price=bars_ubi[-1].close,
                high=max(b.high for b in bars_ubi),
                low=min(b.low for b in bars_ubi),
                is_confirmed=False,
                fx_start=last_bi.fx_end, fx_end=None, bars=list(bars_ubi),
            )
    return bis, unfinished
