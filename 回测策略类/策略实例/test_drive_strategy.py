# -*- coding: utf-8 -*-
"""
独立驱动脚本：无 KhQuant 环境下逐日调用「缠论箱体突破策略_kh.py」，验证信号生成。

用法（用 Python310 运行）：
  python test_drive_strategy.py
  python test_drive_strategy.py --stocks 600519.SH,000001.SZ --start 20250101 --end 20260904 --mode with_today

--mode 说明（模拟 khHistory 是否包含当日K线）：
  with_today   : 回测引擎在当日K线可用时触发（收盘后/含当日数据）
  without_today: 09:30 开盘触发，当日K线尚未形成（最贴近 .kh 配置 trigger 09:30:00）
"""
import argparse
import importlib.util
import os
import shutil
import sys
import types
from datetime import datetime, timedelta

CHAN_PATH = r"D:\量化k线\缠论分型笔"
STRAT_PATH = r"D:\量化k线\回测策略类\策略实例\缠论箱体突破策略_kh.py"
LOG_FILE = r"D:\量化k线\回测策略类\回测实时日志.txt"
KHDATA = r"D:\khData"

sys.path.insert(0, CHAN_PATH)
from chan_report import load_bars  # noqa: E402

# ==================== mock khQuantImport ====================
mock = types.ModuleType("khQuantImport")
_state = {
    "mode": "with_today",
    "dfs": {},          # sc -> 全量 DataFrame（index=datetime）
    "bars": {},         # sc -> 全量 bars 列表
    "by_date": {},      # sc -> {date: bar}
    "positions": {},    # sc -> {price,date}
    "signals": [],      # 信号明细
    "log_lines": [],
}


def _dn_to_dt(dn):
    if isinstance(dn, (int, float)):
        s = str(int(dn))
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
    if isinstance(dn, datetime):
        return dn
    if isinstance(dn, str):
        return datetime.strptime(dn[:8], "%Y%m%d")
    raise TypeError(f"未知 date_num 类型: {type(dn)}")


def khGet(data, key):
    return data.get(key)


def khPrice(data, sc, field):
    """当前交易日（今日）开盘价：09:30 触发时今日开盘价已知；当日停牌/无K线返回 None"""
    day_bar = _state["by_date"][sc].get(_dn_to_dt(data["date_num"]).date())
    if day_bar is not None:
        return float(getattr(day_bar, field))
    return None


def khHistory(sc, fields, count, freq, dn, fq="pre"):
    """模拟 KhQuant 真实返回：{sc: DataFrame}，索引=int(RangeIndex)，日期在 time 列。
    截断到 dn（按 mode 决定含/不含当日），取最后 count 根。
    与 KhQuant khQTTools.khHistory 行为一致（time列 + int索引 + 不含 current_time）。"""
    import pandas as pd
    df_all = _state["dfs"][sc]
    cutoff = _dn_to_dt(dn).date()
    if _state["mode"] == "without_today":
        mask = df_all.index.date < cutoff
    else:
        mask = df_all.index.date <= cutoff
    df = df_all[mask].tail(count)
    out = pd.DataFrame({
        "time": df.index.to_series().dt.to_pydatetime(),
        "open": df["open"].values,
        "high": df["high"].values,
        "low": df["low"].values,
        "close": df["close"].values,
        "amount": df["amount"].values,
    })
    return {sc: out}


def khHas(data, sc):
    return sc in _state["positions"]


def generate_signal(data, sc, price, amount, direction, reason):
    rec = {
        "date": _dn_to_dt(data["date_num"]).date(),
        "sc": sc, "dir": direction, "price": float(price),
        "amount": amount, "reason": reason,
    }
    _state["signals"].append(rec)
    if direction == "buy":
        _state["positions"][sc] = {"price": rec["price"], "date": rec["date"]}
    elif direction == "sell":
        _state["positions"].pop(sc, None)
    return [rec]


mock.khGet = khGet
mock.khPrice = khPrice
mock.khHistory = khHistory
mock.khHas = khHas
mock.generate_signal = generate_signal
# 策略文件注解用了 Dict/List 但没有 from typing import，依赖 khQuantImport import * 提供
mock.Dict = dict
mock.List = list
sys.modules["khQuantImport"] = mock

# ==================== 加载策略模块 ====================
def load_strategy():
    spec = importlib.util.spec_from_file_location("chan_box_strategy", STRAT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["chan_box_strategy"] = mod
    spec.loader.exec_module(mod)
    # 静默 log：只进内存列表，不刷屏
    orig_log = mod.log

    def quiet_log(msg):
        _state["log_lines"].append(str(msg))
    mod.log = quiet_log
    return mod


# ==================== 数据准备 ====================
def prepare(stocks, start, end):
    sdt, edt = datetime.strptime(start, "%Y%m%d"), datetime.strptime(end, "%Y%m%d")
    for sc in stocks:
        code, ex = sc.split(".")
        try:
            label, bars, _ = load_bars(code, ex, "日线", datetime(2023, 1, 1), edt, prewarm_bars=0)
        except Exception as e:
            print(f"[跳过] {sc}: {e}")
            continue
        if not bars:
            print(f"[跳过] {sc}: 无数据")
            continue
        import pandas as pd
        df = pd.DataFrame({
            "open":  [b.open for b in bars],
            "high":  [b.high for b in bars],
            "low":   [b.low for b in bars],
            "close": [b.close for b in bars],
            "amount":[b.amount for b in bars],
        }, index=[b.dt for b in bars])
        _state["dfs"][sc] = df
        _state["bars"][sc] = bars
        _state["by_date"][sc] = {b.dt.date(): b for b in bars}
        print(f"[数据] {sc}: {len(bars)} 根日线, {bars[0].dt:%Y-%m-%d} ~ {bars[-1].dt:%Y-%m-%d}")
    return sorted(_state["dfs"])


# ==================== 逐日驱动 ====================
def drive(mod, stocks, start, end):
    sdt, edt = datetime.strptime(start, "%Y%m%d").date(), datetime.strptime(end, "%Y%m%d").date()
    # 交易日 = 所有股票日期的并集（区间内）
    days = set()
    for sc in stocks:
        for d in _state["by_date"][sc]:
            if sdt <= d <= edt:
                days.add(d)
    days = sorted(days)
    print(f"\n[回测] 区间 {start} ~ {end}，共 {len(days)} 个交易日，股票池 {stocks}，mode={_state['mode']}")
    print("=" * 100)

    mod.init()
    for d in days:
        dn = int(d.strftime("%Y%m%d"))
        data = {"date_num": dn, "stocks": stocks}
        sigs = mod.khHandlebar(data)
        # 更新持仓后打印当日信号
        for s in _state["signals"]:
            if s["date"] == d:
                tag = "买入" if s["dir"] == "buy" else "卖出"
                print(f"{s['date']} | {s['sc']} | {tag} | 价{s['price']:.2f} | 仓{s['amount']} | {s['reason']}")
    print("=" * 100)
    buys = [s for s in _state["signals"] if s["dir"] == "buy"]
    sells = [s for s in _state["signals"] if s["dir"] == "sell"]
    print(f"[结果] 总信号 {len(_state['signals'])}（买入 {len(buys)} / 卖出 {len(sells)}）")
    # 持仓天数统计（按股票配对，自然日）
    from collections import defaultdict
    trades = defaultdict(list)
    for s in buys:
        trades[s["sc"]].append(("B", s["date"]))
    for s in sells:
        trades[s["sc"]].append(("S", s["date"]))
    hold = []
    for sc, evts in trades.items():
        evts.sort(key=lambda x: x[1])
        buy_d = None
        for kind, d in evts:
            if kind == "B" and buy_d is None:
                buy_d = d
            elif kind == "S" and buy_d is not None:
                hold.append((d - buy_d).days)
                buy_d = None
    if hold:
        print(f"[持仓天数(自然日)] 平均 {sum(hold)/len(hold):.1f} 天, 分布 {sorted(hold)}")
    return buys, sells


# ==================== 诊断：某日全量突破信号（不要求==当天） ====================
def diagnose(mod, stocks, probe_dates):
    print("\n[诊断] 各探针日：箱体数 / 突破尝试状态分布 / 成功向上突破（score>=2 且放量）")
    for sc in stocks:
        print(f"-- {sc} --")
        for d in probe_dates:
            dn = int(d.strftime("%Y%m%d"))
            try:
                hist = mock.khHistory(sc, ["open", "high", "low", "close", "amount"],
                                      mod.params['lookback_days'], "1d", dn, fq="pre")
                df = hist[sc]
                bars = []
                for i, (idx, row) in enumerate(df.iterrows()):
                    dt = mod._row_datetime(row, idx)
                    amount = float(row['amount']) if 'amount' in row else 0
                    bars.append(mod.RawBar(symbol=sc, dt=dt, open=float(row['open']),
                                           close=float(row['close']), high=float(row['high']),
                                           low=float(row['low']), vol=amount, amount=amount,
                                           id=i, freq="1d"))
                ana = mod.ChanAnalyzer(bars, symbol=sc, freq="日线",
                                       box_finder=mod.IncrementalBoxFinder(window_size=20))
                boxes = ana.find_boxes()
                if not boxes:
                    print(f"  {d.date()}: 箱体 0 个")
                    continue
                boxes_pct = ana.trend_classifier.calc_box_percentiles(boxes, bars)
                boxes = ana.unified_breakout_analyzer.analyze(boxes_pct, bars, segments=ana.finished_segments)
                # 统计尝试状态
                from collections import Counter
                st_cnt = Counter()
                ok_up = 0
                for bx in boxes:
                    ub = bx.get("unified_breakout", {})
                    for att in ub.get("attempts", []):
                        st_cnt[att.get("status", "?")] += 1
                    if ub.get("success") and ub.get("final_direction") == "up":
                        ok_up += 1
                print(f"  {d.date()}: 箱体 {len(boxes)} | 尝试状态 {dict(st_cnt)} | 成功向上 {ok_up}")
                # 列出成功的向上突破（含被过滤的），看日期与得分
                shown = 0
                for bx in boxes:
                    ub = bx.get("unified_breakout", {})
                    if not ub.get("success") or ub.get("final_direction") != "up":
                        continue
                    for att in ub.get("attempts", []):
                        if att.get("status") != "成功":
                            continue
                        bo_t = att.get("breakout_time")
                        score = att.get("score", 0)
                        o_v = att.get("observe_vol_pct", 0)
                        b_v = att.get("breakout_vol_pct", 0)
                        vol_ok = o_v >= mod.params['vol_pct_threshold'] or b_v >= mod.params['vol_pct_threshold']
                        ok = score >= mod.params['min_score'] and vol_ok
                        print(f"      bo_time={bo_t.date() if bo_t else None} 得分{score} "
                              f"观察量{o_v:.0f}% 突破量{b_v:.0f}% 放量{vol_ok} "
                              f"{'[会买入]' if ok else '[被过滤]'}")
                        shown += 1
                        if shown >= 6:
                            break
                    if shown >= 6:
                        break
            except Exception as e:
                print(f"  {d.date()}: 异常 {type(e).__name__}: {e}")


# ==================== 追踪：从指定日起逐日打印某股的突破/卖出信号 ====================
def trace(mod, sc, start_date, end_date):
    print(f"\n[追踪] {sc} 自 {start_date} 起逐日重算的突破与卖出信号")
    d = start_date
    last_bo, last_sd = None, None
    while d <= end_date:
        dn = int(d.strftime("%Y%m%d"))
        try:
            breakouts, sells = mod._calc_breakouts(sc, dn)
        except Exception as e:
            print(f"  {d}: 异常 {type(e).__name__}: {e}")
            d += timedelta(days=1)
            continue
        bo_list = [b["breakout_time"].date() for b in breakouts]
        sell_days = [s["sell_time"].date() for s in sells if s.get("sell_time")]
        # 只在突破/卖出有变化或当天有动作时输出，控制篇幅
        if d == start_date or (bo_list != last_bo) or (sell_days != last_sd):
            print(f"  {d}: 突破 {len(breakouts)} 个 bo={bo_list[:6]} | 卖出 {len(sells)} 个 sell={sell_days[:6]}")
            last_bo, last_sd = bo_list, sell_days
        else:
            last_bo, last_sd = bo_list, sell_days
        d += timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stocks", default="600519.SH,000001.SZ,000858.SZ,002594.SZ")
    ap.add_argument("--start", default="20250101")
    ap.add_argument("--end", default="20260904")
    ap.add_argument("--mode", default="with_today", choices=["with_today", "without_today"])
    ap.add_argument("--trace", default="")  # 格式 sc:startdate:enddate，如 000001.SZ:20250315:20250630
    args = ap.parse_args()

    # 备份并接管日志文件（策略 import 时会覆写启动行）
    bak = None
    if os.path.exists(LOG_FILE):
        bak = LOG_FILE + ".bak"
        shutil.copy2(LOG_FILE, bak)

    try:
        _state["mode"] = args.mode
        mod = load_strategy()
        stocks = prepare(args.stocks.split(","), args.start, args.end)
        if not stocks:
            print("无可用数据，退出")
            return
        drive(mod, stocks, args.start, args.end)
        probe_dates = [datetime(2025, 3, 14), datetime(2025, 6, 30),
                       datetime(2025, 12, 31), datetime(2026, 6, 30)]
        diagnose(mod, stocks, probe_dates)
        if args.trace:
            tsc, ts, te = args.trace.split(":")
            trace(mod, tsc, datetime.strptime(ts, "%Y%m%d"), datetime.strptime(te, "%Y%m%d"))
    finally:
        if bak and os.path.exists(bak):
            shutil.copy2(bak, LOG_FILE)
            os.remove(bak)


if __name__ == "__main__":
    main()
