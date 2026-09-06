# -*- coding: utf-8 -*-
"""
缠论分析器（ChanAnalyzer）
只负责分析：分型/笔/线段（CZSC）+ 线段大趋势 + 箱体识别。
渲染（终端/HTML）由 ReportRenderer 负责，改前端展示请编辑 core/report_renderer.py。

用法：
    from core.chan_analyzer import ChanAnalyzer
    from core.report_renderer import ReportRenderer
    ana = ChanAnalyzer(bars, symbol="000300.SH", freq="30分钟")
    boxes = ana.find_boxes(slope_quantile=0.5)   # 不同股票可调不同参数
    trends = ana.analyze_segments_trend(trend_pct=5.0)
    ReportRenderer(ana).print_terminal()
    ReportRenderer(ana).render_html("report.html")

注意：
- 缠论核心（K线合并/分型/笔/线段）由 CZSC 类完成，内部自动去包含
- 分型为笔端点分型（从 bi_list 提取 fx_a/fx_b 去重）
- 箱体识别由 BoxFinder 类完成，改盘整算法请编辑 core/box_finder.py
"""
import os
import sys

# 确保能 import 到父目录的 chan_report
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from chan_report import cb
from .box_finder import BoxFinder
from .trend_finder import TrendFinder
from .daily_trend_classifier import DailyTrendClassifier
from .box_quality_analyzer import BoxQualityAnalyzer
from .secondary_breakout_analyzer import SecondaryBreakoutAnalyzer
from .unified_breakout_analyzer import UnifiedBreakoutAnalyzer


class ChanAnalyzer:
    """
    缠论分析器：整合分型/笔/线段 + 线段大趋势 + 箱体识别。
    只输出结构化数据，不负责渲染。

     Parameters
    ----------
    bars : list[RawBar]
        原始K线（未去包含）。内部 CZSC 会自动做K线合并、分型、笔、线段。
    symbol : str
        标的代码，如 "000300.SH"
    freq : str
        周期，如 "30分钟" / "日线"
    max_bi_num : int
        CZSC 最大笔数
    min_bi_len : int
        最小笔长度（去包含K线根数）
    """

    def __init__(self, bars, symbol="", freq="", max_bi_num=None, min_bi_len=6):
        self.bars = bars
        self.symbol = symbol
        self.freq = freq
        if max_bi_num is None:
            max_bi_num = max(200, len(bars))
        # 缠论核心：内部自动做 K线合并 → 分型 → 笔 → 线段
        self.czsc = cb.CZSC(bars, max_bi_num=max_bi_num, min_bi_len=min_bi_len)
        # 笔端点分型（按 (dt, mark) 去重）
        self.fxs = self._extract_bi_fxs()
        # 箱体识别器（独立封装，改盘整算法只动 box_finder.py）
        self.box_finder = BoxFinder()
        # 趋势识别器（独立封装，改趋势算法只动 trend_finder.py）
        self.trend_finder = TrendFinder()
        # 趋势分类器（独立封装，改分类逻辑只动 trend_classifier.py）
        self.trend_classifier = DailyTrendClassifier()
        # 盘整质量分析器（独立封装，改质量算法只动 box_quality_analyzer.py）
        self.box_quality_analyzer = BoxQualityAnalyzer()
        # 二次突破分析器（第一次突破失败后监测二次突破）
        self.secondary_breakout_analyzer = SecondaryBreakoutAnalyzer()
        # 统一突破分析器（多次尝试循环，直到成功或新箱体）
        self.unified_breakout_analyzer = UnifiedBreakoutAnalyzer()

    # ------------------------------------------------------------------
    # 基础属性
    # ------------------------------------------------------------------
    @property
    def bi_list(self):
        return self.czsc.bi_list

    @property
    def segments(self):
        return self.czsc.segments

    @property
    def finished_segments(self):
        return [s for s in self.czsc.segments if s.finished]

    @property
    def last_bi_extend(self):
        return self.czsc.last_bi_extend

    def _extract_bi_fxs(self):
        """从 bi_list 提取笔端点分型，按 (dt, mark) 去重，保持时间顺序。"""
        seen = set()
        fxs = []
        for b in self.bi_list:
            for fx in (b.fx_a, b.fx_b):
                k = (fx.dt, fx.mark)
                if k not in seen:
                    seen.add(k)
                    fxs.append(fx)
        return fxs

    # ------------------------------------------------------------------
    # 线段大趋势分析
    # ------------------------------------------------------------------
    def analyze_segments_trend(self, trend_pct=3.0, trend_bars=20):
        """
        [DEPRECATED] 旧版单根线段阈值法，已被 find_trends 替代。
        对每根已完成线段单独分析，根据涨幅和持续时间判断是否为大趋势线段。

        Parameters
        ----------
        trend_pct : float
            大趋势涨跌幅阈值（%）
        trend_bars : int
            大趋势持续K线阈值

        Returns
        -------
        list[dict]
            每根线段一个 dict，含 idx/direction/change_pct/bar_count/
            slope/is_trend/trend_dir/reason/start_time/end_time/start_price/end_price
        """
        results = []
        for i, seg in enumerate(self.finished_segments, 1):
            base = seg.fx_a.fx
            change_pct = (seg.fx_b.fx - base) / base * 100 if base != 0 else 0
            bar_count = sum(len(b.bars) for b in seg.bis)
            slope = change_pct / bar_count if bar_count > 0 else 0

            is_trend = False
            trend_dir = "none"
            if seg.direction == "Up" and change_pct >= trend_pct and bar_count >= trend_bars:
                is_trend = True
                trend_dir = "up"
            elif seg.direction == "Down" and change_pct <= -trend_pct and bar_count >= trend_bars:
                is_trend = True
                trend_dir = "down"

            if is_trend:
                if trend_dir == "up":
                    reason = f"大趋势上涨：涨幅{change_pct:.2f}%>={trend_pct}%，持续{bar_count}根>={trend_bars}根"
                else:
                    reason = f"大趋势下跌：跌幅{abs(change_pct):.2f}%>={trend_pct}%，持续{bar_count}根>={trend_bars}根"
            else:
                if seg.direction == "Up":
                    reason = f"普通反弹：涨幅{change_pct:.2f}%，持续{bar_count}根"
                else:
                    reason = f"普通回调：跌幅{abs(change_pct):.2f}%，持续{bar_count}根"

            results.append({
                "idx": i, "seg": seg, "direction": seg.direction,
                "change_pct": change_pct, "bar_count": bar_count, "slope": slope,
                "is_trend": is_trend, "trend_dir": trend_dir, "reason": reason,
                "start_time": seg.fx_a.dt, "end_time": seg.fx_b.dt,
                "start_price": seg.fx_a.fx, "end_price": seg.fx_b.fx,
            })
        return results

    # ------------------------------------------------------------------
    # 箱体识别（代理方法）
    # ------------------------------------------------------------------
    def find_boxes(self, slope_quantile=None, chg_quantile=None, min_fx=None,
                   min_h_pct=None, max_h_pct=None):
        """
        箱体识别（代理方法，实际逻辑在 BoxFinder 类中）。
        传参则临时覆盖 BoxFinder 的参数，不传则用 BoxFinder 默认参数。
        改盘整算法请编辑 core/box_finder.py。
        """
        bf = self.box_finder
        if slope_quantile is not None:
            bf.slope_quantile = slope_quantile
        if chg_quantile is not None:
            bf.chg_quantile = chg_quantile
        if min_fx is not None:
            bf.min_fx = min_fx
        if min_h_pct is not None:
            bf.min_h_pct = min_h_pct
        if max_h_pct is not None:
            bf.max_h_pct = max_h_pct
        boxes = bf.find(self.fxs, self.bars)
        # 先找趋势（用于成交量分析中的"前一段趋势"判断）
        trends = self.find_trends()
        # 自动调用盘整质量分析（标准度+成交量，带去极值），改算法请编辑 core/box_quality_analyzer.py
        boxes = self.box_quality_analyzer.analyze(boxes, self.bars, fxs=self.fxs, trends=trends)
        return boxes

    # ------------------------------------------------------------------
    # 趋势识别（代理方法）
    # ------------------------------------------------------------------
    def find_trends(self, min_gap_bars=None, min_gap_pct=None):
        """
        趋势识别（代理方法，实际逻辑在 TrendFinder 类中）。
        基于箱体的趋势判断：每根线段=一个趋势，与箱体重叠的部分不标记。
        改趋势算法请编辑 core/trend_finder.py。

        Parameters
        ----------
        min_gap_bars : int, optional
            箱体之间短间隔的最大K线数（默认15）
        min_gap_pct : float, optional
            箱体之间短间隔的最大涨跌幅%（默认10.0）
        """
        tf_kwargs = {}
        if min_gap_bars is not None:
            tf_kwargs['min_gap_bars'] = min_gap_bars
        if min_gap_pct is not None:
            tf_kwargs['min_gap_pct'] = min_gap_pct
        if tf_kwargs:
            tf = TrendFinder(**tf_kwargs)
        else:
            tf = self.trend_finder
        boxes = self.box_finder.find(self.fxs, self.bars)
        return tf.find(boxes, self.segments, self.bars)

    # ------------------------------------------------------------------
    # 趋势分类（代理方法）
    # ------------------------------------------------------------------
    def classify(self, boxes=None, trends=None):
        """
        对箱体和趋势进行多维度分类。

        Parameters
        ----------
        boxes : list[dict], optional
            箱体列表，不传则自动调用 find_boxes()
        trends : list[dict], optional
            趋势列表，不传则自动调用 find_trends()

        Returns
        -------
        dict
            含 "boxes"（带位置标签的箱体列表）和 "trends"（带分类标签的趋势列表）
        """
        if boxes is None:
            boxes = self.find_boxes()
        if trends is None:
            trends = self.find_trends()
        labeled_boxes = self.trend_classifier.classify_boxes(boxes, self.bars)
        labeled_trends = self.trend_classifier.classify_trends(trends, boxes, self.bars)
        return {"boxes": labeled_boxes, "trends": labeled_trends}
