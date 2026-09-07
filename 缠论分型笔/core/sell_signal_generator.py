# -*- coding: utf-8 -*-
"""
卖出逻辑类（SellSignalGenerator）

逻辑：
- 买入信号：突破日（T日确认突破GG/DD）
- 卖出信号：突破后出现的第一个顶分型
- T日才知道T-1日有无形成顶分型，若出现则T日卖出

无未来函数：所有判断都基于当日及之前的数据
"""
import bisect


class SellSignalGenerator:
    """卖出信号生成器：突破后第一个顶分型卖出"""

    def __init__(self):
        pass

    def generate_signals(self, bars, breakouts, fxs):
        """
        为每个突破信号生成卖出信号。

        Parameters
        ----------
        bars : list
            原始K线列表
        breakouts : list[dict]
            突破信号列表，每个含 breakout_time, direction, observe_time 等
        fxs : list
            分型列表（笔端点分型），每个含 dt, mark("G"顶/"D"底)

        Returns
        -------
        list[dict]
            每个突破信号对应一个卖出信号：
            {
                "breakout_time": 突破日,
                "buy_time": 买入日（突破日）,
                "buy_price": 买入价（突破日收盘价）,
                "sell_time": 卖出日（顶分型确认日=T+1）,
                "sell_price": 卖出价（卖出日收盘价）,
                "top_fx_time": 顶分型日,
                "top_fx_price": 顶分型价格,
                "hold_days": 持有天数,
                "return_pct": 收益率,
                "reason": 卖出原因
            }
        """
        if not bars or not breakouts or not fxs:
            return []

        dts = [b.dt for b in bars]
        top_fxs = [fx for fx in fxs if fx.mark == "G"]  # 只看顶分型
        top_fx_dts = [fx.dt for fx in top_fxs]

        results = []
        for bo in breakouts:
            breakout_time = bo.get("breakout_time")
            if not breakout_time:
                continue

            # 买入日 = 突破日，买入价 = 突破日收盘价
            breakout_idx = bisect.bisect_right(dts, breakout_time) - 1
            if breakout_idx < 0 or breakout_idx >= len(bars):
                continue
            buy_price = bars[breakout_idx].close

            # 找突破日之后的第一个顶分型
            # 顶分型形成需要3根K线，所以顶分型日T的确认日是T+1
            # 卖出日 = 顶分型日的下一根K线
            sell_signal = None
            for fx in top_fxs:
                if fx.dt > breakout_time:
                    # 找到突破后的第一个顶分型
                    fx_idx = bisect.bisect_right(dts, fx.dt) - 1
                    if fx_idx + 1 < len(bars):
                        sell_idx = fx_idx + 1  # T+1卖出
                        sell_time = bars[sell_idx].dt
                        sell_price = bars[sell_idx].close
                        hold_days = sell_idx - breakout_idx
                        return_pct = (sell_price - buy_price) / buy_price * 100

                        sell_signal = {
                            "breakout_time": breakout_time,
                            "buy_time": breakout_time,
                            "buy_price": buy_price,
                            "sell_time": sell_time,
                            "sell_price": sell_price,
                            "top_fx_time": fx.dt,
                            "top_fx_price": fx.high,
                            "hold_days": hold_days,
                            "return_pct": return_pct,
                            "reason": f"突破后第{hold_days}天出现顶分型({fx.dt.strftime('%Y-%m-%d')})，T+1卖出",
                        }
                    break

            if not sell_signal:
                # 没找到顶分型，持有到最后
                last_idx = len(bars) - 1
                sell_signal = {
                    "breakout_time": breakout_time,
                    "buy_time": breakout_time,
                    "buy_price": buy_price,
                    "sell_time": bars[last_idx].dt,
                    "sell_price": bars[last_idx].close,
                    "top_fx_time": None,
                    "top_fx_price": None,
                    "hold_days": last_idx - breakout_idx,
                    "return_pct": (bars[last_idx].close - buy_price) / buy_price * 100,
                    "reason": "未出现顶分型，持有到最后",
                }

            results.append(sell_signal)

        return results

    def backtest(self, bars, boxes, fxs, min_score=0, vol_pct_threshold=0):
        """
        简易回测：对所有箱体的向上突破做买入，第一个顶分型卖出。

        Parameters
        ----------
        bars : list
            原始K线列表
        boxes : list[dict]
            箱体列表（含 unified_breakout）
        fxs : list
            分型列表
        min_score : int
            最低得分过滤
        vol_pct_threshold : float
            最低放量百分位过滤

        Returns
        -------
        dict
            回测统计：总交易数、胜率、平均收益、盈亏比等
        """
        # 提取所有向上突破信号
        breakouts = []
        for bx in boxes:
            ub = bx.get("unified_breakout", {})
            if not ub.get("success") or ub.get("final_direction") != "up":
                continue
            for att in ub.get("attempts", []):
                if att.get("status") != "成功":
                    continue
                score = att.get("score", 0)
                obs_vol = att.get("observe_vol_pct", 0)
                bo_vol = att.get("breakout_vol_pct", 0)
                is_vol = obs_vol >= vol_pct_threshold or bo_vol >= vol_pct_threshold
                if score < min_score or not is_vol:
                    continue
                breakouts.append(att)

        # 生成卖出信号
        trades = self.generate_signals(bars, breakouts, fxs)

        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "avg_return": 0,
                "max_return": 0,
                "min_return": 0,
                "avg_hold_days": 0,
                "trades": [],
            }

        wins = [t for t in trades if t["return_pct"] > 0]
        losses = [t for t in trades if t["return_pct"] <= 0]
        avg_win = sum(t["return_pct"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["return_pct"] for t in losses) / len(losses) if losses else 0

        return {
            "total_trades": len(trades),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": len(wins) / len(trades) * 100,
            "avg_return": sum(t["return_pct"] for t in trades) / len(trades),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_loss_ratio": abs(avg_win / avg_loss) if avg_loss != 0 else 0,
            "max_return": max(t["return_pct"] for t in trades),
            "min_return": min(t["return_pct"] for t in trades),
            "avg_hold_days": sum(t["hold_days"] for t in trades) / len(trades),
            "trades": trades,
        }
