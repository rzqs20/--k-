# -*- coding: utf-8 -*-
"""调试 688036 卖出卡死：逐日打印 2b 卖出识别的判断细节"""
import sys, os, types, importlib.util
from datetime import datetime
import pandas as pd

CHAN_PATH = r"D:\量化k线\缠论分型笔"
STRAT_PATH = r"D:\量化k线\回测策略类\策略实例\缠论箱体突破策略_kh.py"
sys.path.insert(0, CHAN_PATH)
from chan_report import load_bars

mock = types.ModuleType("khQuantImport")
_state = {
    "mode": "without_today",
    "dfs": {}, "bars": {}, "by_date": {},
    "positions": {}, "signals": [], "log_lines": [],
}

def _dn_to_dt(dn):
    if isinstance(dn, (int, float)):
        s = str(int(dn)); return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
    if isinstance(dn, str): return datetime.strptime(dn[:8], "%Y%m%d")
    if hasattr(dn, 'date'): return dn.date() if not isinstance(dn, datetime) else dn
    return dn

def khGet(data, key): return data.get(key)
def khPrice(data, sc, field):
    day_bar = _state["by_date"][sc].get(_dn_to_dt(data["date_num"]).date())
    return float(getattr(day_bar, field)) if day_bar is not None else None

def khHistory(sc, fields, count, freq, dn, fq="pre"):
    df_all = _state["dfs"][sc]
    cutoff = _dn_to_dt(dn).date()
    mask = df_all.index.date < cutoff if _state["mode"] == "without_today" else df_all.index.date <= cutoff
    df = df_all[mask].tail(count)
    out = pd.DataFrame({
        "time": df.index.to_series().dt.to_pydatetime(),
        "open": df["open"].values, "high": df["high"].values,
        "low": df["low"].values, "close": df["close"].values,
        "amount": df["amount"].values,
    })
    return {sc: out}

def khHas(data, sc): return sc in _state["positions"]
def generate_signal(data, sc, price, amount, direction, reason):
    rec = {"date": _dn_to_dt(data["date_num"]).date(), "sc": sc, "dir": direction,
           "price": float(price), "amount": amount, "reason": reason}
    _state["signals"].append(rec)
    if direction == "buy": _state["positions"][sc] = {"price": rec["price"], "date": rec["date"]}
    elif direction == "sell": _state["positions"].pop(sc, None)
    return [rec]

mock.khGet, mock.khPrice, mock.khHistory, mock.khHas, mock.generate_signal = khGet, khPrice, khHistory, khHas, generate_signal
mock.Dict, mock.List = dict, list
sys.modules["khQuantImport"] = mock

spec = importlib.util.spec_from_file_location("chan_box", STRAT_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules["chan_box"] = mod
spec.loader.exec_module(mod)
# 静默 log
mod.log = lambda msg: None

# 数据
sc = "688036.SH"
code, ex = sc.split(".")
label, bars, _ = load_bars(code, ex, "日线", datetime(2023, 1, 1), datetime(2025, 10, 1), prewarm_bars=0)
df = pd.DataFrame({
    "open": [b.open for b in bars], "high": [b.high for b in bars],
    "low": [b.low for b in bars], "close": [b.close for b in bars],
    "amount": [b.amount for b in bars],
}, index=[b.dt for b in bars])
_state["dfs"][sc] = df
_state["bars"][sc] = bars
_state["by_date"][sc] = {b.dt.date(): b for b in bars}

mod.init()
g = mod.g
days = [d for d in sorted(_state["by_date"][sc]) if datetime(2025, 1, 1).date() <= d <= datetime(2025, 10, 1).date()]
print(f"总交易日 {len(days)}")
for d in days:
    dn = int(d.strftime("%Y%m%d"))
    mod.khHandlebar({"date_num": dn, "stocks": [sc]})
    if sc in g["positions"] and d in (datetime(2025,2,7).date(), datetime(2025,2,10).date(), datetime(2025,2,11).date(), datetime(2025,2,12).date(), datetime(2025,2,13).date(), datetime(2025,2,14).date()):
        bo = g["positions"][sc]["breakout_time"]
        bars_w = g["bars"][sc]
        fxs_w = g["fxs"][sc]
        last_day = bars_w[-1].dt.date() if bars_w else None
        fx, conf = mod._first_top_fx(bars_w, fxs_w, bo)
        g_marks = sorted([f"{fx.dt:%m-%d}{fx.mark}" for fx in fxs_w])
        print(f"T={d} W={last_day} last_w={g['last_w'].get(sc)} first_top_fx={fx.dt.date() if fx else None} confirm={conf} ==W? {conf==last_day} pending_sell={'有' if sc in g['pending_sell'] else '无'} fxs={g_marks}")
