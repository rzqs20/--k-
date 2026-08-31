# -*- coding: utf-8 -*-
"""全链路流水线：原始K线 → 分型 → 笔 → 线段 → 中枢 → 走势 → 背驰 → 买卖点"""
from . import config
from .include import process_inclusion
from .fenxing import find_fenxing
from .bi import generate_bi
from .segment import generate_segment
from .zhongshu import find_zhongshu
from .trend import classify_trend
from .beichi import calc_macd, calc_beichi
from .bs_points import find_bs_points
from .models import KLine


def run_pipeline(raw_klines, level='stroke', compute_segment=True):
    """完整递归链路。

    raw_klines: 原始K线列表（字段 time/open/high/low/close/volume/amount）
    level: 'stroke' 笔中枢 / 'segment' 线段中枢
    返回 dict：
      klines_processed 处理后K线
      fxs              分型
      bis              笔（+unfinished_bi 未完成笔）
      segments         线段（level='segment' 时计算）
      zhongshu         中枢
      trends           走势类型
      beichis          背驰
      bs_points        买卖点
      macd             (dif, dea, hist) 用于报告
    """
    # 模块1：包含处理
    klines = process_inclusion(raw_klines)
    # 模块2：分型
    fxs = find_fenxing(klines)
    # 模块3：笔
    bis, unfinished_bi = generate_bi(fxs, klines)
    # 模块5-8 的单元（笔或线段）
    units = bis
    segments = []
    if level == 'segment' and compute_segment:
        segments = generate_segment(bis)
        if segments:
            units = segments
    # 模块5：中枢
    zhongshu = find_zhongshu(units, level=level)
    # 模块6：走势类型
    trends = classify_trend(zhongshu, level=level)
    # 模块7：背驰（需要 MACD）
    closes = [k.close for k in raw_klines]
    dif, dea, hist = calc_macd(closes)
    dts = [k.time for k in raw_klines]
    beichis = calc_beichi(trends, closes, dts, dif, hist, units, level=level)
    # 模块8：买卖点
    bs = find_bs_points(bis, zhongshu, trends, beichis, level=level)

    return {
        'klines_processed': klines,
        'fxs': fxs,
        'bis': bis,
        'unfinished_bi': unfinished_bi,
        'segments': segments,
        'zhongshu': zhongshu,
        'trends': trends,
        'beichis': beichis,
        'bs_points': bs,
        'macd': (dif, dea, hist),
    }
