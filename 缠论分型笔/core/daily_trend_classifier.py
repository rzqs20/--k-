# -*- coding: utf-8 -*-
"""
日K趋势分类器（DailyTrendClassifier）
独立封装，对箱体和趋势进行多维度分类。

分类维度：
  箱体位置：高位 / 中位 / 低位（三指标综合判断）
  趋势方向：上涨 / 下跌
  趋势结构：盘整后突破 / 无盘整直接走
  趋势强度：强势 / 普通 / 弱势
  趋势位置：高位 / 中位 / 低位（基于起点价格）
  终结方式：遇箱体终结 / 极值反转 / 未完成

用法：
    from core.daily_trend_classifier import DailyTrendClassifier
    tc = DailyTrendClassifier()
    box_labels = tc.classify_boxes(boxes, bars)
    trend_labels = tc.classify_trends(trends, boxes, bars)
"""
import bisect


class DailyTrendClassifier:
    """
    趋势分类器：对箱体位置和趋势进行多维度分类。

    Parameters
    ----------
    high_pct_threshold : float
        高位百分位阈值（默认0.66）
    low_pct_threshold : float
        低位百分位阈值（默认0.33）
    high_abs_threshold : float
        高位绝对位置阈值（默认0.6）
    low_abs_threshold : float
        低位绝对位置阈值（默认0.4）
    dist_threshold : float
        距高低点距离阈值（默认0.2，即20%）
    strong_pct : float
        强势趋势涨跌幅阈值（默认5.0%）
    weak_pct : float
        弱势趋势涨跌幅阈值（默认2.0%）
    """

    def __init__(self, high_pct_threshold=0.66, low_pct_threshold=0.33,
                 high_abs_threshold=0.6, low_abs_threshold=0.4,
                 dist_threshold=0.2, strong_pct=10.0, weak_pct=5.0):
        self.high_pct_threshold = high_pct_threshold
        self.low_pct_threshold = low_pct_threshold
        self.high_abs_threshold = high_abs_threshold
        self.low_abs_threshold = low_abs_threshold
        self.dist_threshold = dist_threshold
        self.strong_pct = strong_pct
        self.weak_pct = weak_pct

    # ------------------------------------------------------------------
    # 箱体内部价格分位计算
    # ------------------------------------------------------------------
    def calc_box_percentiles(self, boxes, bars):
        """
        计算每个箱体内部K线收盘价的分位值（P10/P50/P90），用于判断突破有效性。

        Parameters
        ----------
        boxes : list[dict]
            BoxFinder 输出的箱体列表
        bars : list
            原始K线列表

        Returns
        -------
        list[dict]
            每个箱体含原字段 + p10/p50/p90/avg_volume
        """
        if not boxes or not bars:
            return []

        import bisect
        dts = [b.dt for b in bars]

        def _idx(dt):
            return bisect.bisect_right(dts, dt) - 1

        result = []
        for box in boxes:
            si = _idx(box["start"])
            ei = _idx(box["end"])
            box_bars = bars[si:ei + 1]
            if not box_bars:
                labeled = dict(box)
                labeled.update({"p10": 0, "p50": 0, "p90": 0, "avg_volume": 0})
                result.append(labeled)
                continue

            closes = sorted(b.close for b in box_bars)
            volumes = [b.vol for b in box_bars]
            n = len(closes)

            def _percentile(data, p):
                if not data:
                    return 0
                k = (len(data) - 1) * p / 100.0
                f = int(k)
                c = min(f + 1, len(data) - 1)
                if f == c:
                    return data[f]
                return data[f] + (data[c] - data[f]) * (k - f)

            labeled = dict(box)
            labeled["p10"] = round(_percentile(closes, 10), 3)
            labeled["p50"] = round(_percentile(closes, 50), 3)
            labeled["p90"] = round(_percentile(closes, 90), 3)
            labeled["avg_volume"] = round(sum(volumes) / n, 0)
            result.append(labeled)

        return result

    # ------------------------------------------------------------------
    # 箱体突破监测
    # ------------------------------------------------------------------
    def analyze_breakouts(self, boxes, bars, segments=None, monitor_window=10, vol_multiplier=1.0):
        """
        监测每个箱体结束后的突破情况，判断是否为有效突破。

        逻辑：
          1. 箱体结束后，监测后续K线，直到收盘价触碰P90（向上）或P10（向下）
          2. 突破那根K线成交量 > 箱体平均成交量 * vol_multiplier → 标记"监测"
          3. 次日依旧放量 + 创新高/新低 → "有效突破"
          4. 否则 → "突破失败"或"无量突破"

        Parameters
        ----------
        boxes : list[dict]
            BoxFinder 输出的箱体列表（需已含p10/p90/avg_volume，可由calc_box_percentiles生成）
        bars : list
            原始K线列表
        segments : list
            缠论线段列表（用于计算突破后涨幅：找到包含突破日的线段，算到线段结束）
        monitor_window : int
            箱体结束后最多监测多少根K线（默认10）
        vol_multiplier : float
            放量倍数阈值（默认1.0，即成交量>平均成交量即算放量）

        Returns
        -------
        list[dict]
            每个箱体含原字段 + breakout分析结果
        """
        if not boxes or not bars:
            return []

        dts = [b.dt for b in bars]

        def _idx(dt):
            return bisect.bisect_right(dts, dt) - 1

        result = []
        for box in boxes:
            labeled = dict(box)
            p90 = box.get("p90", box["gg"])
            p10 = box.get("p10", box["dd"])
            avg_vol = box.get("avg_volume", 0)
            vol_threshold = avg_vol * vol_multiplier

            end_idx = _idx(box["end"])
            monitor_bars = bars[end_idx + 1:end_idx + 1 + monitor_window]

            breakout = {
                "direction": "none",
                "observe_time": None,
                "observe_price": 0,
                "observe_volume": 0,
                "observe_vol_pct": 0,
                "breakout_time": None,
                "breakout_price": 0,
                "breakout_volume": 0,
                "breakout_vol_pct": 0,
                "breakout_pct": 0,
                "breakout_end_time": None,
                "score": 0,
                "score_detail": "",
                "score_history": [],
                "status": "未突破",
                "detail": "",
            }

            if not monitor_bars:
                labeled["breakout"] = breakout
                result.append(labeled)
                continue

            # 寻找第一根触碰P90或P10的K线
            breakout_idx = -1
            for i, bar in enumerate(monitor_bars):
                if bar.close > p90:
                    breakout["direction"] = "up"
                    breakout_idx = i
                    break
                elif bar.close < p10:
                    breakout["direction"] = "down"
                    breakout_idx = i
                    break

            if breakout_idx == -1:
                breakout["status"] = "未突破"
                breakout["detail"] = f"监测{len(monitor_bars)}根K线未触碰P90/P10"
                labeled["breakout"] = breakout
                result.append(labeled)
                continue

            bo_bar = monitor_bars[breakout_idx]
            # 观察日（T日）= 触碰P90/P10的那天
            breakout["observe_time"] = bo_bar.dt
            breakout["observe_price"] = bo_bar.close
            breakout["observe_volume"] = bo_bar.vol
            # 计算观察日成交量在箱体内部成交量分布中的百分位
            box_vols = sorted([b.vol for b in bars[end_idx - box.get("bars", 10) + 1:end_idx + 1] if b.vol > 0])
            if box_vols:
                breakout["observe_vol_pct"] = sum(1 for v in box_vols if v < bo_bar.vol) / len(box_vols) * 100

            # === 逐日动态评分 ===
            gg = box.get("gg", box.get("full_high", 0))
            dd = box.get("dd", box.get("full_low", 0))
            score_history = []  # 每天的评分记录

            def calc_daily_score(day_idx, obs_start_idx, is_breakout_day=False, breakout_day_offset=0):
                """计算某一天的监测中评分（只用当天及之前的数据）
                监测期间不给时间分，只有突破当日才加时间分"""
                bars_so_far = monitor_bars[obs_start_idx:day_idx + 1]
                days_observed = day_idx - obs_start_idx  # T+0=0, T+1=1, ...
                # 1. 时间分：只有突破当日才给，监测期间=0
                if is_breakout_day:
                    time_score = max(0, 4 - breakout_day_offset)  # T+1=3, T+2=2, T+3=1, T+4+=0
                else:
                    time_score = 0  # 监测期间不给时间分
                # 2. 平均量能百分位
                avg_vol = sum(b.vol for b in bars_so_far) / len(bars_so_far)
                avg_vol_pct = sum(1 for v in box_vols if v < avg_vol) / len(box_vols) * 100 if box_vols else 50
                if avg_vol_pct >= 80:
                    vol_score = 2
                elif avg_vol_pct >= 60:
                    vol_score = 0
                else:
                    vol_score = -2
                # 3. 当日量能>80%
                day_vol_pct = sum(1 for v in box_vols if v < bars_so_far[-1].vol) / len(box_vols) * 100 if box_vols else 50
                day_vol_score = 1 if day_vol_pct > 80 else 0
                # 4. 稳步放量：平均量>70%
                steady_score = 1 if avg_vol_pct > 70 else 0
                total = time_score + vol_score + day_vol_score + steady_score
                return {
                    "day": days_observed,
                    "date": bars_so_far[-1].dt,
                    "close": bars_so_far[-1].close,
                    "vol_pct": day_vol_pct,
                    "avg_vol_pct": avg_vol_pct,
                    "time_score": time_score,
                    "vol_score": vol_score,
                    "day_vol_score": day_vol_score,
                    "steady_score": steady_score,
                    "total": total,
                }

            # 观察日(T)的初始评分（监测期间，不给时间分）
            score_history.append(calc_daily_score(breakout_idx, breakout_idx, is_breakout_day=False))

            # 逐日观测
            breakout_day_idx = -1
            fail_day_idx = -1
            for offset in range(1, len(monitor_bars) - breakout_idx):
                if breakout_idx + offset >= len(monitor_bars):
                    break
                test_bar = monitor_bars[breakout_idx + offset]
                # 每天先计算评分（监测期间，不给时间分）
                daily = calc_daily_score(breakout_idx + offset, breakout_idx, is_breakout_day=False)

                if breakout["direction"] == "up":
                    if test_bar.close > gg:
                        breakout_day_idx = offset
                        # 突破日重新计算评分，加上时间分
                        daily = calc_daily_score(breakout_idx + offset, breakout_idx,
                                                 is_breakout_day=True, breakout_day_offset=offset)
                        daily["note"] = "突破GG"
                        score_history[-1] = daily  # 替换掉刚才的监测评分
                        break
                    elif test_bar.close < p90:
                        fail_day_idx = offset
                        daily["note"] = "回到箱体内"
                        score_history.append(daily)
                        break
                    else:
                        daily["note"] = "临界区域"
                        score_history.append(daily)
                else:
                    if test_bar.close < dd:
                        breakout_day_idx = offset
                        # 突破日重新计算评分，加上时间分
                        daily = calc_daily_score(breakout_idx + offset, breakout_idx,
                                                 is_breakout_day=True, breakout_day_offset=offset)
                        daily["note"] = "跌破DD"
                        score_history[-1] = daily  # 替换掉刚才的监测评分
                        break
                    elif test_bar.close > p10:
                        fail_day_idx = offset
                        daily["note"] = "回到箱体内"
                        score_history.append(daily)
                        break
                    else:
                        daily["note"] = "临界区域"
                        score_history.append(daily)

            breakout["score_history"] = score_history

            if breakout_day_idx == -1:
                # 未突破GG/DD → 突破失败
                breakout["status"] = "突破失败"
                breakout["score"] = 0
                if fail_day_idx > 0:
                    fail_bar = monitor_bars[breakout_idx + fail_day_idx]
                    breakout["detail"] = (f"T日{bo_bar.close:.2f}触碰{'P90' if breakout['direction']=='up' else 'P10'}，"
                                          f"T+{fail_day_idx}日{fail_bar.close:.2f}回到箱体内（突破失败）")
                else:
                    breakout["detail"] = (f"T日{bo_bar.close:.2f}触碰{'P90' if breakout['direction']=='up' else 'P10'}，"
                                          f"监测窗口内未突破{'GG' if breakout['direction']=='up' else 'DD'}")
            else:
                # 找到突破日，计算最终评分（和逐日评分最后一天一致，但加上完整标注）
                cf_bar = monitor_bars[breakout_idx + breakout_day_idx]
                breakout["breakout_time"] = cf_bar.dt
                breakout["breakout_price"] = cf_bar.close
                breakout["breakout_volume"] = cf_bar.vol
                if box_vols:
                    breakout["breakout_vol_pct"] = sum(1 for v in box_vols if v < cf_bar.vol) / len(box_vols) * 100

                # 最终评分 = 突破日那天的逐日评分（收敛度只作参考，不加入评分）
                final_daily = score_history[-1]
                score = final_daily["total"]
                avg_vol_pct = final_daily["avg_vol_pct"]
                score_detail = [
                    f"T+{breakout_day_idx}突破时间分{final_daily['time_score']}",
                    f"均量{avg_vol_pct:.0f}%量能分{final_daily['vol_score']:+d}",
                    f"当日量{final_daily['vol_pct']:.0f}%>{80 if final_daily['day_vol_score'] else '不达标'}{final_daily['day_vol_score']:+d}",
                    f"稳步放量{final_daily['steady_score']:+d}",
                ]

                # 状态按平均量百分位细分
                if avg_vol_pct >= 80:
                    breakout["status"] = "放量突破"
                    vol_label = "放量突破"
                elif avg_vol_pct >= 60:
                    breakout["status"] = "无量突破"
                    vol_label = "无量突破"
                else:
                    breakout["status"] = "缩量突破"
                    vol_label = "缩量突破"

                breakout["score"] = score
                breakout["score_detail"] = "; ".join(score_detail)
                breakout["detail"] = (f"T日{bo_bar.close:.2f}触碰{'P90' if breakout['direction']=='up' else 'P10'}，"
                                      f"T+{breakout_day_idx}日{cf_bar.close:.2f}突破"
                                      f"{'GG' if breakout['direction']=='up' else 'DD'}({gg if breakout['direction']=='up' else dd:.2f})，"
                                      f"{vol_label}，得分{score}")

            # 计算突破后涨跌幅度（从突破日开始，找到包含突破日的线段，算到线段结束）
            if breakout.get("breakout_time") and segments:
                # 突破日 = 真正突破GG/DD的那天
                breakout_dt = breakout["breakout_time"]
                breakout_price = breakout["breakout_price"]
                breakout_idx_in_all = bisect.bisect_left(dts, breakout_dt)
                # 找到包含突破日的线段
                target_seg = None
                for seg in segments:
                    if seg.fx_a.dt <= breakout_dt <= seg.fx_b.dt:
                        target_seg = seg
                        break
                if target_seg:
                    breakout["breakout_end_time"] = target_seg.fx_b.dt
                    seg_end_idx = bisect.bisect_right(dts, target_seg.fx_b.dt) - 1
                    trend_bars = bars[breakout_idx_in_all:seg_end_idx + 1]
                    if trend_bars and breakout_price > 0:
                        if breakout["direction"] == "up":
                            max_high = max(b.high for b in trend_bars)
                            breakout["breakout_pct"] = (max_high / breakout_price - 1) * 100
                        elif breakout["direction"] == "down":
                            min_low = min(b.low for b in trend_bars)
                            breakout["breakout_pct"] = (min_low / breakout_price - 1) * 100

            labeled["breakout"] = breakout
            result.append(labeled)

        return result

    # ------------------------------------------------------------------
    # 箱体位置分类
    # ------------------------------------------------------------------
    def classify_boxes(self, boxes, bars):
        """
        对所有箱体进行位置分类（高位/中位/低位）。

        三指标综合判断（只用该箱体结束日之前的历史数据，不含未来）：
          1. 箱体中间值百分位排名（相对当前及之前的箱体）
          2. 历史价格区间绝对位置（只用之前的K线高低点）
          3. 距历史高低点距离（只用之前的高低点）

        Parameters
        ----------
        boxes : list[dict]
            BoxFinder 输出的箱体列表
        bars : list
            原始K线列表

        Returns
        -------
        list[dict]
            每个箱体含原字段 + position/position_detail
        """
        if not boxes or not bars:
            return []

        dts = [b.dt for b in bars]

        def _idx(dt):
            return bisect.bisect_right(dts, dt) - 1

        # 计算每个箱体的中间值
        mid_values = []
        for box in boxes:
            mid = (box["gg"] + box["dd"]) / 2
            mid_values.append(mid)

        result = []
        for i, box in enumerate(boxes):
            mid = mid_values[i]
            # 只用该箱体结束日之前的数据（不含未来）
            end_idx = _idx(box["end"])
            hist_bars = bars[:end_idx + 1]
            hist_high = max(b.high for b in hist_bars)
            hist_low = min(b.low for b in hist_bars)
            hist_range = hist_high - hist_low

            # 指标1：百分位排名（只用当前及之前的箱体）
            hist_mids = mid_values[:i + 1]
            sorted_hist = sorted(hist_mids)
            pct_rank = sum(1 for m in sorted_hist if m < mid) / len(sorted_hist) if sorted_hist else 0.5

            # 指标2：绝对位置（只用历史高低点）
            abs_pos = (mid - hist_low) / hist_range if hist_range != 0 else 0.5

            # 指标3：距历史高低点距离
            dist_h = (hist_high - mid) / hist_high if hist_high != 0 else 0
            dist_l = (mid - hist_low) / hist_low if hist_low != 0 else 0

            # 三指标投票
            votes_high = 0
            votes_low = 0
            if pct_rank >= self.high_pct_threshold:
                votes_high += 1
            if pct_rank <= self.low_pct_threshold:
                votes_low += 1
            if abs_pos >= self.high_abs_threshold:
                votes_high += 1
            if abs_pos <= self.low_abs_threshold:
                votes_low += 1
            if dist_h <= self.dist_threshold:
                votes_high += 1
            if dist_l <= self.dist_threshold:
                votes_low += 1

            if votes_high >= 2:
                position = "高位"
            elif votes_low >= 2:
                position = "低位"
            else:
                position = "中位"

            detail = (
                f"百分位{pct_rank:.0%}/绝对位置{abs_pos:.0%}/"
                f"距高点{dist_h:.0%}/距低点{dist_l:.0%}"
                f"（高{votes_high}票/低{votes_low}票）"
            )

            labeled = dict(box)
            labeled["position"] = position
            labeled["position_detail"] = detail
            result.append(labeled)

        return result

    # ------------------------------------------------------------------
    # 趋势分类
    # ------------------------------------------------------------------
    def classify_trends(self, trends, boxes, bars):
        """
        对所有趋势进行多维度分类。

        分类维度：
          1. 方向：上涨/下跌
          2. 结构：盘整后突破/无盘整直接走
          3. 强度：强势/普通/弱势
          4. 位置：高位/中位/低位（基于起点价格）
          5. 终结方式：遇箱体终结/极值反转/未完成

        Parameters
        ----------
        trends : list[dict]
            TrendFinder 输出的趋势列表
        boxes : list[dict]
            BoxFinder 输出的箱体列表（已分类或未分类均可）
        bars : list
            原始K线列表

        Returns
        -------
        list[dict]
            每个趋势含原字段 + direction_cn/structure/strength/position/end_type
        """
        if not trends or not bars:
            return []

        dts = [b.dt for b in bars]

        def _idx(dt):
            return bisect.bisect_right(dts, dt) - 1

        all_high = max(b.high for b in bars)
        all_low = min(b.low for b in bars)
        price_range = all_high - all_low

        # 箱体位置分类（用于判断趋势起点是否在箱体后）
        box_positions = self.classify_boxes(boxes, bars)

        result = []
        for t in trends:
            labeled = dict(t)

            # 1. 方向
            direction_cn = "上涨" if t["direction"] == "up" else "下跌"
            labeled["direction_cn"] = direction_cn

            # 2. 结构：判断起点前是否有箱体
            start_idx = _idx(t["start_time"])
            has_box_before = False
            box_before_pos = None
            for bp in box_positions:
                box_end_idx = _idx(bp["end"])
                if box_end_idx <= start_idx and (start_idx - box_end_idx) <= 30:
                    has_box_before = True
                    box_before_pos = bp["position"]
                    break
            if has_box_before:
                structure = f"盘整后突破（{box_before_pos}盘整）"
            else:
                structure = "无盘整直接走"
            labeled["structure"] = structure

            # 3. 强度
            abs_pct = abs(t["change_pct"])
            if abs_pct >= self.strong_pct:
                strength = "强势"
            elif abs_pct <= self.weak_pct:
                strength = "弱势"
            else:
                strength = "普通"
            labeled["strength"] = strength

            # 4. 位置：基于起点价格的绝对位置
            start_price = t["start_price"]
            if price_range == 0:
                start_pos = 0.5
            else:
                start_pos = (start_price - all_low) / price_range
            if start_pos >= 0.6:
                pos = "高位"
            elif start_pos <= 0.4:
                pos = "低位"
            else:
                pos = "中位"
            labeled["position"] = pos
            labeled["position_detail"] = f"起点价格{start_price:.2f}，绝对位置{start_pos:.0%}"

            # 5. 终结方式
            end_idx = _idx(t["end_time"])
            is_last = (end_idx >= len(bars) - 2)
            meets_box = False
            for bp in box_positions:
                box_start_idx = _idx(bp["start"])
                if abs(box_start_idx - end_idx) <= 5:
                    meets_box = True
                    break
            if is_last:
                end_type = "未完成"
            elif meets_box:
                end_type = "遇箱体终结"
            else:
                end_type = "极值反转"
            labeled["end_type"] = end_type

            # 综合标签
            labeled["label"] = f"{direction_cn}·{strength}·{structure}·起点{pos}·{end_type}"
            result.append(labeled)

        return result
