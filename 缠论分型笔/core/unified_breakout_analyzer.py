# -*- coding: utf-8 -*-
"""
统一突破分析器（UnifiedBreakoutAnalyzer）

逻辑：
1. 箱体结束后开始监测
2. 循环：找触碰P90/P10的K线 → 观察日 → 逐日监测突破/失败
3. 失败则继续下一次尝试，成功则结束
4. 终止条件：突破成功 OR 遇到新的箱体 OR 数据结束
5. 每次尝试记录详细信息（观察日、方向、得分、失败原因等）
6. 成交量基准：第1次用箱体内，第2次及以后用上次失败日到本次观察日
"""
import bisect


class UnifiedBreakoutAnalyzer:
    """统一突破分析：支持多次突破尝试循环，直到成功或遇到新箱体"""

    def __init__(self, max_attempts=5, monitor_window=20):
        """
        Parameters
        ----------
        max_attempts : int
            最大尝试次数（防止无限循环）
        monitor_window : int
            每次尝试的监测窗口（从观察日开始算）
        """
        self.max_attempts = max_attempts
        self.monitor_window = monitor_window

    def analyze(self, boxes, bars, segments=None):
        """
        对所有箱体做统一突破分析。

        Parameters
        ----------
        boxes : list[dict]
            箱体列表（需含p90/p10/gg/dd字段）
        bars : list
            原始K线列表
        segments : list, optional
            线段列表（用于计算突破后涨幅的终点）

        Returns
        -------
        list[dict]
            每个箱体含 unified_breakout 字段
        """
        if not boxes or not bars:
            return boxes

        dts = [b.dt for b in bars]

        def _idx(dt):
            return bisect.bisect_right(dts, dt) - 1

        result = []
        for box_idx, box in enumerate(boxes):
            labeled = dict(box)

            unified = {
                "success": False,
                "attempt_count": 0,
                "attempts": [],
                "final_direction": "none",
                "final_observe_time": None,
                "final_breakout_time": None,
                "final_score": 0,
                "final_breakout_pct": 0,
                "final_status": "未突破",
                "final_detail": "",
            }

            end_idx = _idx(box["end"])
            p90 = box.get("p90", box["gg"])
            p10 = box.get("p10", box["dd"])
            gg = box.get("gg", 0)
            dd = box.get("dd", 0)

            # 箱体内成交量（第1次尝试用）
            box_start_idx = _idx(box["start"])
            box_vols = sorted([b.vol for b in bars[box_start_idx:end_idx + 1] if b.vol > 0])

            # 下一个箱体的开始时间（用于终止循环）
            next_box_start_idx = len(bars)
            if box_idx + 1 < len(boxes):
                next_box_start_idx = _idx(boxes[box_idx + 1]["start"])

            # 当前监测位置（从箱体结束后第1根开始）
            current_idx = end_idx + 1
            ref_vols = box_vols  # 第1次尝试用箱体内成交量

            for attempt in range(1, self.max_attempts + 1):
                if current_idx >= len(bars) or current_idx >= next_box_start_idx:
                    break

                # === 找观察日：下一根触碰P90/P10的K线 ===
                observe_idx = -1
                direction = "none"
                search_end = min(current_idx + self.monitor_window, next_box_start_idx, len(bars))
                for i in range(current_idx, search_end):
                    if bars[i].close > p90:
                        observe_idx = i
                        direction = "up"
                        break
                    elif bars[i].close < p10:
                        observe_idx = i
                        direction = "down"
                        break

                if observe_idx == -1:
                    # 没找到观察日，结束
                    break

                obs_bar = bars[observe_idx]
                attempt_data = {
                    "attempt": attempt,
                    "observe_time": obs_bar.dt,
                    "observe_price": obs_bar.close,
                    "observe_volume": obs_bar.vol,
                    "direction": direction,
                    "status": "监测中",
                    "score": 0,
                    "score_detail": "",
                    "breakout_time": None,
                    "breakout_price": 0,
                    "fail_time": None,
                    "fail_price": 0,
                    "vol_ref_avg": sum(ref_vols) / len(ref_vols) if ref_vols else 0,
                }

                # 观察日成交量百分位
                if ref_vols:
                    attempt_data["observe_vol_pct"] = sum(1 for v in ref_vols if v < obs_bar.vol) / len(ref_vols) * 100
                else:
                    attempt_data["observe_vol_pct"] = 50

                # === 逐日监测 ===
                breakout_idx = -1
                fail_idx = -1
                score_history = []

                def calc_daily_score(day_idx, obs_start_idx, is_breakout_day=False, breakout_day_offset=0):
                    bars_so_far = bars[obs_start_idx:day_idx + 1]
                    days_observed = day_idx - obs_start_idx
                    # 1. 时间分
                    if is_breakout_day:
                        time_score = max(0, 4 - breakout_day_offset)
                    else:
                        time_score = 0
                    # 2. 平均量能百分位
                    avg_vol = sum(b.vol for b in bars_so_far) / len(bars_so_far) if bars_so_far else 0
                    avg_vol_pct = sum(1 for v in ref_vols if v < avg_vol) / len(ref_vols) * 100 if ref_vols else 50
                    if avg_vol_pct >= 80:
                        vol_score = 2
                    elif avg_vol_pct >= 60:
                        vol_score = 0
                    else:
                        vol_score = -2
                    # 3. 当日量能
                    day_vol_pct = sum(1 for v in ref_vols if v < bars_so_far[-1].vol) / len(ref_vols) * 100 if ref_vols else 50
                    day_vol_score = 1 if day_vol_pct > 80 else 0
                    # 4. 稳步放量
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

                # 观察日初始评分
                score_history.append(calc_daily_score(observe_idx, observe_idx, is_breakout_day=False))

                # 逐日监测
                monitor_end = min(observe_idx + self.monitor_window, next_box_start_idx, len(bars))
                for offset in range(1, monitor_end - observe_idx):
                    test_idx = observe_idx + offset
                    if test_idx >= len(bars):
                        break
                    test_bar = bars[test_idx]
                    daily = calc_daily_score(test_idx, observe_idx, is_breakout_day=False)

                    if direction == "up":
                        if test_bar.close > gg:
                            breakout_idx = test_idx
                            daily = calc_daily_score(test_idx, observe_idx, is_breakout_day=True, breakout_day_offset=offset)
                            daily["note"] = "突破GG"
                            score_history[-1] = daily
                            break
                        elif test_bar.close < p90:
                            fail_idx = test_idx
                            daily["note"] = "回到箱体内"
                            score_history.append(daily)
                            break
                        else:
                            daily["note"] = "临界区域"
                            score_history.append(daily)
                    else:
                        if test_bar.close < dd:
                            breakout_idx = test_idx
                            daily = calc_daily_score(test_idx, observe_idx, is_breakout_day=True, breakout_day_offset=offset)
                            daily["note"] = "跌破DD"
                            score_history[-1] = daily
                            break
                        elif test_bar.close > p10:
                            fail_idx = test_idx
                            daily["note"] = "回到箱体内"
                            score_history.append(daily)
                            break
                        else:
                            daily["note"] = "临界区域"
                            score_history.append(daily)

                attempt_data["score_history"] = score_history

                if breakout_idx != -1:
                    # 突破成功
                    cf_bar = bars[breakout_idx]
                    attempt_data["status"] = "成功"
                    attempt_data["breakout_time"] = cf_bar.dt
                    attempt_data["breakout_price"] = cf_bar.close
                    attempt_data["breakout_volume"] = cf_bar.vol
                    if ref_vols:
                        attempt_data["breakout_vol_pct"] = sum(1 for v in ref_vols if v < cf_bar.vol) / len(ref_vols) * 100

                    final_daily = score_history[-1]
                    attempt_data["score"] = final_daily["total"]
                    avg_vol_pct = final_daily["avg_vol_pct"]
                    attempt_data["score_detail"] = (
                        f"T+{breakout_idx - observe_idx}时间分{final_daily['time_score']}, "
                        f"均量{avg_vol_pct:.0f}%量能分{final_daily['vol_score']:+d}, "
                        f"当日量{final_daily['vol_pct']:.0f}%分{final_daily['day_vol_score']:+d}, "
                        f"稳步{final_daily['steady_score']:+d}"
                    )
                    if avg_vol_pct >= 80:
                        attempt_data["vol_label"] = "放量突破"
                    elif avg_vol_pct >= 60:
                        attempt_data["vol_label"] = "无量突破"
                    else:
                        attempt_data["vol_label"] = "缩量突破"

                    # 突破后涨幅：从突破日到线段终点
                    attempt_data["breakout_pct"] = self._calc_breakout_pct(
                        bars, breakout_idx, direction, segments)

                    unified["attempts"].append(attempt_data)
                    unified["success"] = True
                    unified["attempt_count"] = attempt
                    unified["final_direction"] = direction
                    unified["final_observe_time"] = obs_bar.dt
                    unified["final_breakout_time"] = cf_bar.dt
                    unified["final_score"] = attempt_data["score"]
                    unified["final_breakout_pct"] = attempt_data["breakout_pct"]
                    unified["final_status"] = f"第{attempt}次尝试{attempt_data['vol_label']}"
                    unified["final_detail"] = (
                        f"共{attempt}次尝试，第{attempt}次{direction}方向突破成功，"
                        f"得分{attempt_data['score']}，突破后涨跌{attempt_data['breakout_pct']:.2f}%"
                    )
                    break  # 突破成功，结束循环

                elif fail_idx != -1:
                    # 突破失败
                    fail_bar = bars[fail_idx]
                    attempt_data["status"] = "失败"
                    attempt_data["fail_time"] = fail_bar.dt
                    attempt_data["fail_price"] = fail_bar.close
                    attempt_data["score"] = 0
                    attempt_data["score_detail"] = f"T+{fail_idx - observe_idx}日回到箱体内"
                    unified["attempts"].append(attempt_data)

                    # 更新成交量基准：失败日到下一次观察日（先记录失败日到当前的K线）
                    fail_bars = bars[observe_idx:fail_idx + 1]
                    ref_vols = sorted([b.vol for b in fail_bars if b.vol > 0])

                    # 继续下一次尝试，从失败日下一根开始
                    current_idx = fail_idx + 1
                    continue
                else:
                    # 监测窗口内既没突破也没失败，结束
                    attempt_data["status"] = "未决"
                    attempt_data["score_detail"] = "监测窗口内未突破也未回到箱体"
                    unified["attempts"].append(attempt_data)
                    break

            if not unified["success"] and unified["attempts"]:
                last_attempt = unified["attempts"][-1]
                unified["attempt_count"] = len(unified["attempts"])
                unified["final_status"] = f"共{len(unified['attempts'])}次尝试均未成功"
                unified["final_detail"] = f"最后一次尝试：{last_attempt.get('score_detail', '')}"

            labeled["unified_breakout"] = unified
            result.append(labeled)

        return result

    def _calc_breakout_pct(self, bars, breakout_idx, direction, segments=None):
        """计算突破后涨跌幅：从突破日到包含突破日的线段结束"""
        if breakout_idx >= len(bars):
            return 0.0
        breakout_dt = bars[breakout_idx].dt
        breakout_close = bars[breakout_idx].close

        # 找包含突破日的线段
        seg_end_idx = len(bars) - 1
        if segments:
            for seg in segments:
                # 线段对象可能有 start_time/end_time 或 fx_a/fx_b
                seg_start = getattr(seg, 'start_time', None) or getattr(seg, 'fx_a', None)
                seg_end = getattr(seg, 'end_time', None) or getattr(seg, 'fx_b', None)
                if seg_start and seg_end:
                    # fx_a/fx_b 是分型对象，有 dt 属性
                    if hasattr(seg_start, 'dt'):
                        seg_start = seg_start.dt
                    if hasattr(seg_end, 'dt'):
                        seg_end = seg_end.dt
                    if seg_start <= breakout_dt <= seg_end:
                        # 找到线段结束的K线索引
                        import bisect
                        dts = [b.dt for b in bars]
                        seg_end_idx = bisect.bisect_right(dts, seg_end) - 1
                        break

        # 从突破日到线段结束，计算极值涨跌幅
        segment_bars = bars[breakout_idx:seg_end_idx + 1]
        if not segment_bars:
            return 0.0
        if direction == "up":
            high = max(b.high for b in segment_bars)
            return (high - breakout_close) / breakout_close * 100
        else:
            low = min(b.low for b in segment_bars)
            return (low - breakout_close) / breakout_close * 100
