# -*- coding: utf-8 -*-
"""
趋势识别器（TrendFinder）
基于缠论线段的趋势判断：每根线段就是一个趋势，与箱体重叠的部分不标记。

逻辑：
  1. 遍历所有已完成线段
  2. 向上线段 = 上涨趋势，向下线段 = 下跌趋势
  3. 线段与箱体有重叠的部分不标记，只标记箱体外的部分
  4. 若线段被箱体分割成多段，每段单独标记为趋势

用法：
    from core.trend_finder import TrendFinder
    tf = TrendFinder()
    trends = tf.find(boxes, segments, bars)
"""
import bisect


class TrendFinder:
    """
    基于缠论线段的趋势识别器。
    每根线段就是一个趋势，与箱体重叠的部分不标记。
    """

    def __init__(self):
        pass

    def find(self, boxes, segments, bars):
        """
        执行趋势识别。

        Parameters
        ----------
        boxes : list[dict]
            BoxFinder 输出的箱体列表
        segments : list
            缠论线段列表（CZSC.segments）
        bars : list
            原始K线列表

        Returns
        -------
        list[dict]
            每个趋势含 direction/start_time/end_time/start_price/end_price/
            change_pct/bar_count/seg_idx/reason
        """
        if not segments:
            return []

        dts = [b.dt for b in bars]

        def _idx(dt):
            return bisect.bisect_right(dts, dt) - 1

        trends = []
        for i, seg in enumerate(segments):
            if not seg.finished:
                continue

            seg_start_idx = _idx(seg.fx_a.dt)
            seg_end_idx = _idx(seg.fx_b.dt)
            direction = "up" if seg.direction == "Up" else "down"

            # 构建禁止标记区间：箱体 + 箱体之间短间隔（<=15根且涨跌幅<=10%）
            forbidden = []
            for box in boxes:
                forbidden.append((_idx(box["start"]), _idx(box["end"])))
            # 箱体之间的短间隔也加入禁止标记区
            for bi in range(len(boxes) - 1):
                gap_start = _idx(boxes[bi]["end"])
                gap_end = _idx(boxes[bi + 1]["start"])
                gap_bars = gap_end - gap_start
                if gap_bars > 0 and gap_bars <= 15:
                    gap_change = (bars[gap_end].close - bars[gap_start].close) / bars[gap_start].close * 100
                    if abs(gap_change) <= 10:
                        forbidden.append((gap_start, gap_end))

            # 找到与该线段有交集的禁止标记区
            overlap_boxes = []
            for f_start, f_end in forbidden:
                if seg_start_idx < f_end and seg_end_idx > f_start:
                    overlap_boxes.append((f_start, f_end))

            if not overlap_boxes:
                # 完全在箱体外，整根线段标记
                sub_ranges = [(seg_start_idx, seg_end_idx)]
            else:
                # 从线段区间中减去所有箱体重叠区间
                sub_ranges = [(seg_start_idx, seg_end_idx)]
                for box_start, box_end in overlap_boxes:
                    new_ranges = []
                    for r_start, r_end in sub_ranges:
                        # 无交集
                        if r_end <= box_start or r_start >= box_end:
                            new_ranges.append((r_start, r_end))
                            continue
                        # 有交集，拆分
                        if r_start < box_start:
                            new_ranges.append((r_start, box_start))
                        if r_end > box_end:
                            new_ranges.append((box_end, r_end))
                    sub_ranges = new_ranges

            # 对每个子区间标记趋势
            for sub_start, sub_end in sub_ranges:
                if sub_end <= sub_start:
                    continue
                start_price = bars[sub_start].close
                end_price = bars[sub_end].close
                change_pct = (end_price - start_price) / start_price * 100 if start_price != 0 else 0
                bar_count = sub_end - sub_start + 1

                cn_dir = "上涨" if direction == "up" else "下跌"
                if not overlap_boxes:
                    reason = f"线段{cn_dir}方向，未触碰任何箱体"
                else:
                    reason = f"线段{cn_dir}方向，扣除箱体部分后的剩余区间"

                trends.append({
                    "idx": len(trends) + 1,
                    "direction": direction,
                    "start_time": bars[sub_start].dt,
                    "end_time": bars[sub_end].dt,
                    "start_price": round(start_price, 3),
                    "end_price": round(end_price, 3),
                    "change_pct": round(change_pct, 2),
                    "bar_count": bar_count,
                    "seg_idx": i + 1,
                    "reason": reason,
                })

        return trends
