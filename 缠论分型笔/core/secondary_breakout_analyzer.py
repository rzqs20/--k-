# -*- coding: utf-8 -*-
"""
二次突破分析器（SecondaryBreakoutAnalyzer）

逻辑：
1. 第一次突破失败后，从失败日开始监测（不标注观察日）
2. 监测期间不预设方向，哪边先触碰P90/P10就标注为二次观察日
3. 二次突破的成交量对比基准 = 第一次突破失败日到二次观察日这段时间的平均成交量
4. 剩下的逻辑和第一次突破一样：动态观察窗口、突破GG/DD成功、回到P90/P10失败、四维打分
"""
import bisect


class SecondaryBreakoutAnalyzer:
    """二次突破分析：第一次突破失败后，监测是否有二次突破（同向或反向）"""

    def __init__(self, monitor_window=15, vol_multiplier=1.0):
        """
        Parameters
        ----------
        monitor_window : int
            二次突破的监测窗口（从第一次突破失败日开始算）
        vol_multiplier : float
            成交量倍数（预留，当前用百分位判断）
        """
        self.monitor_window = monitor_window
        self.vol_multiplier = vol_multiplier

    def analyze(self, boxes, bars, first_breakouts=None):
        """
        对所有箱体做二次突破分析。

        Parameters
        ----------
        boxes : list[dict]
            箱体列表（需含p90/p10/gg/dd/breakout字段）
        bars : list
            原始K线列表
        first_breakouts : list[dict], optional
            第一次突破结果列表（如果boxes里已有breakout字段则不用传）

        Returns
        -------
        list[dict]
            每个箱体含 secondary_breakout 字段
        """
        if not boxes or not bars:
            return boxes

        dts = [b.dt for b in bars]

        def _idx(dt):
            return bisect.bisect_right(dts, dt) - 1

        result = []
        for box in boxes:
            labeled = dict(box)
            first_bo = box.get("breakout", {})

            secondary = {
                "has_secondary": False,
                "direction": "none",
                "first_fail_time": None,
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
                "status": "无二次突破",
                "detail": "",
                "ref_vol_avg": 0,
            }

            # 只有第一次突破失败的箱体才做二次突破分析
            if first_bo.get("status") != "突破失败":
                labeled["secondary_breakout"] = secondary
                result.append(labeled)
                continue

            # 第一次突破失败的时间
            fail_time = None
            score_hist = first_bo.get("score_history", [])
            for h in reversed(score_hist):
                if "回到箱体内" in h.get("note", ""):
                    fail_time = h.get("date")
                    break
            if fail_time is None:
                # 如果score_history里没有，用观察日+1
                fail_time = first_bo.get("observe_time")

            if fail_time is None:
                labeled["secondary_breakout"] = secondary
                result.append(labeled)
                continue

            secondary["first_fail_time"] = fail_time
            fail_idx = _idx(fail_time)

            # 二次监测窗口：从失败日下一根开始
            monitor_bars = bars[fail_idx + 1:fail_idx + 1 + self.monitor_window]
            if not monitor_bars:
                secondary["detail"] = "失败日后无足够K线"
                labeled["secondary_breakout"] = secondary
                result.append(labeled)
                continue

            p90 = box.get("p90", box["gg"])
            p10 = box.get("p10", box["dd"])
            gg = box.get("gg", 0)
            dd = box.get("dd", 0)

            # === 找到二次观察日：哪边先触碰P90/P10 ===
            observe_idx = -1
            for i, bar in enumerate(monitor_bars):
                if bar.close > p90:
                    secondary["direction"] = "up"
                    observe_idx = i
                    break
                elif bar.close < p10:
                    secondary["direction"] = "down"
                    observe_idx = i
                    break

            if observe_idx == -1:
                secondary["status"] = "无二次突破"
                secondary["detail"] = f"失败日后{len(monitor_bars)}根K线未触碰P90/P10"
                labeled["secondary_breakout"] = secondary
                result.append(labeled)
                continue

            secondary["has_secondary"] = True
            obs_bar = monitor_bars[observe_idx]
            secondary["observe_time"] = obs_bar.dt
            secondary["observe_price"] = obs_bar.close
            secondary["observe_volume"] = obs_bar.vol

            # === 成交量基准：失败日到二次观察日这段时间的平均成交量 ===
            ref_bars = monitor_bars[:observe_idx + 1]
            ref_vols = sorted([b.vol for b in ref_bars if b.vol > 0])
            secondary["ref_vol_avg"] = sum(b.vol for b in ref_bars) / len(ref_bars) if ref_bars else 0

            # 观察日成交量在参考成交量中的百分位
            if ref_vols:
                secondary["observe_vol_pct"] = sum(1 for v in ref_vols if v < obs_bar.vol) / len(ref_vols) * 100

            # === 逐日动态评分（和第一次突破逻辑一致，只是成交量基准不同）===
            score_history = []

            def calc_daily_score(day_idx, obs_start_idx, is_breakout_day=False, breakout_day_offset=0):
                bars_so_far = monitor_bars[obs_start_idx:day_idx + 1]
                days_observed = day_idx - obs_start_idx
                # 1. 时间分：只有突破当日才给
                if is_breakout_day:
                    time_score = max(0, 4 - breakout_day_offset)
                else:
                    time_score = 0
                # 2. 平均量能百分位（用参考成交量基准）
                avg_vol = sum(b.vol for b in bars_so_far) / len(bars_so_far) if bars_so_far else 0
                avg_vol_pct = sum(1 for v in ref_vols if v < avg_vol) / len(ref_vols) * 100 if ref_vols else 50
                if avg_vol_pct >= 80:
                    vol_score = 2
                elif avg_vol_pct >= 60:
                    vol_score = 0
                else:
                    vol_score = -2
                # 3. 当日量能>80%
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

            # 逐日观测
            breakout_day_idx = -1
            fail_day_idx = -1
            for offset in range(1, len(monitor_bars) - observe_idx):
                if observe_idx + offset >= len(monitor_bars):
                    break
                test_bar = monitor_bars[observe_idx + offset]
                daily = calc_daily_score(observe_idx + offset, observe_idx, is_breakout_day=False)

                if secondary["direction"] == "up":
                    if test_bar.close > gg:
                        breakout_day_idx = offset
                        daily = calc_daily_score(observe_idx + offset, observe_idx,
                                                 is_breakout_day=True, breakout_day_offset=offset)
                        daily["note"] = "突破GG"
                        score_history[-1] = daily
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
                        daily = calc_daily_score(observe_idx + offset, observe_idx,
                                                 is_breakout_day=True, breakout_day_offset=offset)
                        daily["note"] = "跌破DD"
                        score_history[-1] = daily
                        break
                    elif test_bar.close > p10:
                        fail_day_idx = offset
                        daily["note"] = "回到箱体内"
                        score_history.append(daily)
                        break
                    else:
                        daily["note"] = "临界区域"
                        score_history.append(daily)

            secondary["score_history"] = score_history

            if breakout_day_idx == -1:
                secondary["status"] = "二次突破失败"
                secondary["score"] = 0
                if fail_day_idx > 0:
                    fail_bar = monitor_bars[observe_idx + fail_day_idx]
                    secondary["detail"] = (f"一次失败后，二次观察日{obs_bar.close:.2f}触碰"
                                           f"{'P90' if secondary['direction']=='up' else 'P10'}，"
                                           f"T+{fail_day_idx}日{fail_bar.close:.2f}回到箱体内")
                else:
                    secondary["detail"] = (f"一次失败后，二次观察日{obs_bar.close:.2f}触碰"
                                           f"{'P90' if secondary['direction']=='up' else 'P10'}，"
                                           f"监测窗口内未突破{'GG' if secondary['direction']=='up' else 'DD'}")
            else:
                cf_bar = monitor_bars[observe_idx + breakout_day_idx]
                secondary["breakout_time"] = cf_bar.dt
                secondary["breakout_price"] = cf_bar.close
                secondary["breakout_volume"] = cf_bar.vol
                if ref_vols:
                    secondary["breakout_vol_pct"] = sum(1 for v in ref_vols if v < cf_bar.vol) / len(ref_vols) * 100

                final_daily = score_history[-1]
                score = final_daily["total"]
                avg_vol_pct = final_daily["avg_vol_pct"]
                secondary["score"] = score
                secondary["score_detail"] = (
                    f"T+{breakout_day_idx}时间分{final_daily['time_score']}, "
                    f"均量{avg_vol_pct:.0f}%量能分{final_daily['vol_score']:+d}, "
                    f"当日量{final_daily['vol_pct']:.0f}%分{final_daily['day_vol_score']:+d}, "
                    f"稳步{final_daily['steady_score']:+d}"
                )

                # 状态描述
                if avg_vol_pct >= 80:
                    secondary["status"] = "二次放量突破"
                elif avg_vol_pct >= 60:
                    secondary["status"] = "二次无量突破"
                else:
                    secondary["status"] = "二次缩量突破"

                # 突破后涨幅：从突破日到包含突破日的线段结束
                breakout_idx_global = fail_idx + 1 + observe_idx + breakout_day_idx
                secondary["breakout_pct"] = self._calc_breakout_pct(
                    box, bars, breakout_idx_global, secondary["direction"])

            labeled["secondary_breakout"] = secondary
            result.append(labeled)

        return result

    def _calc_breakout_pct(self, box, bars, breakout_idx, direction):
        """计算突破后涨跌幅：从突破日到包含突破日的线段结束"""
        # 简化版：从突破日到监测窗口结束的极值涨跌幅
        if breakout_idx >= len(bars):
            return 0.0
        end_idx = min(breakout_idx + 20, len(bars) - 1)
        segment_bars = bars[breakout_idx:end_idx + 1]
        if not segment_bars:
            return 0.0
        if direction == "up":
            high = max(b.high for b in segment_bars)
            return (high - segment_bars[0].close) / segment_bars[0].close * 100
        else:
            low = min(b.low for b in segment_bars)
            return (low - segment_bars[0].close) / segment_bars[0].close * 100
