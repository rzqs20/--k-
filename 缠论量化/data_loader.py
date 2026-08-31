# -*- coding: utf-8 -*-
"""数据加载：D:khData DuckDB → KLine 列表（含周期重采样）"""
import os
import bisect
from datetime import datetime
import duckdb

from chan.models import KLine
from chan import config

FREQ_ALIASES = {
    "1分钟": "1分钟", "1m": "1分钟", "1min": "1分钟",
    "5分钟": "5分钟", "5m": "5分钟",
    "15分钟": "15分钟", "15m": "15分钟",
    "30分钟": "30分钟", "30m": "30分钟",
    "60分钟": "60分钟", "60m": "60分钟", "1小时": "60分钟",
    "120分钟": "120分钟", "120m": "120分钟",
    "日线": "日线", "日": "日线", "d": "日线", "D": "日线",
    "周线": "周线", "周": "周线", "w": "周线", "W": "周线",
    "月线": "月线", "月": "月线", "m": "月线", "M": "月线",
}


def resolve_symbol(code):
    code = code.strip().upper()
    if "." in code:
        c, ex = code.split(".")
        return c, ex.upper()
    if code.startswith(("60", "68", "51", "58", "56", "9")):
        return code, "SH"
    if code.startswith(("00", "30", "12", "15", "16", "18", "2")):
        return code, "SZ"
    if code.startswith(("8", "4", "92")):
        return code, "BJ"
    return code, None


def _find_db(code, exchange):
    if exchange:
        p = os.path.join(config.KHDATA_ROOT, exchange, code + ".db")
        return p if os.path.exists(p) else None
    for ex in ("SH", "SZ", "BJ"):
        p = os.path.join(config.KHDATA_ROOT, ex, code + ".db")
        if os.path.exists(p):
            return p
    return None


def _parse_date(s):
    s = s.strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {s}")


def _to_kline(r):
    return KLine(time=r[0], open=float(r[1]), high=float(r[2]),
                 low=float(r[3]), close=float(r[4]),
                 volume=float(r[5] or 0), amount=float(r[6] or 0))


def resample_minutes(klines_1m, minutes):
    """1分钟 → N分钟（A股 09:30-11:30 / 13:00-15:00 分桶）"""
    buckets = {}
    for k in klines_1m:
        t = k.time
        hm = t.hour * 60 + t.minute
        if 9 * 60 + 30 <= hm <= 11 * 60 + 29:
            off, sess = hm - (9 * 60 + 30), 0
        elif 13 * 60 <= hm <= 15 * 60 - 1:
            off, sess = hm - 13 * 60, 1
        else:
            continue
        key = (t.date(), sess, off // minutes)
        buckets.setdefault(key, []).append(k)
    out = []
    for key in sorted(buckets):
        bs = buckets[key]
        out.append(KLine(time=bs[-1].time, open=bs[0].open, close=bs[-1].close,
                         high=max(b.high for b in bs), low=min(b.low for b in bs),
                         volume=sum(b.volume for b in bs),
                         amount=sum(b.amount for b in bs)))
    return out


def resample_daily(klines_1d, target):
    """日线 → 周线/月线"""
    buckets = {}
    for k in klines_1d:
        t = k.time
        key = t.isocalendar()[:2] if target == "W" else (t.year, t.month)
        buckets.setdefault(key, []).append(k)
    out = []
    for key in sorted(buckets):
        bs = buckets[key]
        out.append(KLine(time=bs[-1].time, open=bs[0].open, close=bs[-1].close,
                         high=max(b.high for b in bs), low=min(b.low for b in bs),
                         volume=sum(b.volume for b in bs),
                         amount=sum(b.amount for b in bs)))
    return out


def load_bars(code_in, freq_in, sdt_in, edt_in, prewarm_bars=None):
    """加载K线。返回 (标的label, KLine列表, 预热数)"""
    prewarm_bars = prewarm_bars or config.PREWARM_BARS
    freq = FREQ_ALIASES.get(freq_in.strip())
    if not freq:
        raise ValueError(f"不支持的周期: {freq_in}")
    sdt, edt = _parse_date(sdt_in), _parse_date(edt_in)
    if sdt > edt:
        raise ValueError("起始日期不能晚于终止日期")
    code, exchange = resolve_symbol(code_in)
    if not exchange:
        raise ValueError(f"无法判断 {code_in} 的市场")
    db = _find_db(code, exchange)
    if not db:
        raise FileNotFoundError(f"未找到 {code_in} 数据文件")

    con = duckdb.connect(db, read_only=True)
    try:
        tables = {r[0] for r in con.sql("SHOW TABLES").fetchall()}
        if freq in ("1分钟", "15分钟", "30分钟", "60分钟", "120分钟"):
            need = "kline_1m"
        elif freq == "5分钟":
            need = "kline_5m"
        else:
            need = "kline_1d"
        if need not in tables:
            raise RuntimeError(f"{code_in} 无 {need} 数据")
        rows = con.execute(
            f"SELECT time, open, high, low, close, volume, amount FROM {need} "
            f"WHERE time::DATE >= ? AND time::DATE <= ? ORDER BY time",
            [sdt.date(), edt.date()]).fetchall()
        klines = [_to_kline(r) for r in rows if r[1] is not None and r[4] is not None]
        if freq != "1分钟" and freq != "5分钟" and freq in ("15分钟", "30分钟", "60分钟", "120分钟"):
            klines = resample_minutes(klines, int(freq.replace("分钟", "")))
        elif freq == "周线":
            klines = resample_daily(klines, "W")
        elif freq == "月线":
            klines = resample_daily(klines, "M")
    finally:
        con.close()

    if not klines:
        raise RuntimeError(f"{code_in} 在 {sdt.date()}~{edt.date()} 无 {freq} 数据")

    # 预热
    prewarm = 0
    if prewarm_bars > 0 and len(klines) < prewarm_bars:
        pre = _load_prewarm(db, klines[0].time, freq, prewarm_bars - len(klines))
        klines = pre + klines
        prewarm = len(pre)
    return f"{code}.{exchange}", freq, klines, prewarm


def _load_prewarm(db, first_time, freq, n):
    try:
        con = duckdb.connect(db, read_only=True)
        try:
            if freq in ("1分钟", "15分钟", "30分钟", "60分钟", "120分钟"):
                table = "kline_1m"
            elif freq == "5分钟":
                table = "kline_5m"
            else:
                table = "kline_1d"
            mult = 4
            if freq in ("15分钟", "30分钟", "60分钟", "120分钟"):
                mult = max(mult, int(freq.replace("分钟", "")))
            rows = con.execute(
                f"SELECT time, open, high, low, close, volume, amount FROM {table} "
                f"WHERE time < ? ORDER BY time DESC LIMIT ?",
                [first_time, n * mult]).fetchall()
        finally:
            con.close()
    except Exception:
        return []
    rows = list(reversed(rows))
    kl = [_to_kline(r) for r in rows if r[1] is not None and r[4] is not None]
    if freq in ("15分钟", "30分钟", "60分钟", "120分钟"):
        kl = resample_minutes(kl, int(freq.replace("分钟", "")))
        kl = [k for k in kl if k.time < first_time]
    elif freq == "周线":
        kl = resample_daily(kl, "W")
        kl = [k for k in kl if k.time < first_time]
    elif freq == "月线":
        kl = resample_daily(kl, "M")
        kl = [k for k in kl if k.time < first_time]
    return kl[-n:]
