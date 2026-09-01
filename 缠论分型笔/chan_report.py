#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论 · 分型与笔 报告程序
========================
从 D:\\khData（DuckDB，每个标的一个 .db）读取K线，
用 chan_fx_bi 做「去包含 → 分型 → 笔」分析，输出：
    1) 终端文本报告（分型清单 + 笔清单 + 结构统计）
    2) HTML 图表报告（K线 + 笔 + 顶/底分型 + 成交量，自包含可离线打开）

按需求，本报告【不含】中枢、买卖点、背驰、趋势判断。

用法（命令行）：
    python chan_report.py 600000.SH 日线 2024-01-01 2024-12-31
    python chan_report.py 000001.SZ 30分钟 2024-01-01 2024-12-31

用法（交互）：
    python chan_report.py        # 按提示输入代码/周期/起止日期

支持周期：1分钟 / 5分钟 / 15分钟 / 30分钟 / 60分钟 / 120分钟 / 日线 / 周线 / 月线
依赖：D:\\khData 数据目录 + chan_fx_bi.py（同目录）
"""

import sys
import os
import bisect
import json
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb

# 兼容加载分型/笔模块：优先 chan_fx_bi.py，找不到则加载 分型+笔.py（用户可能重命名）
import importlib.util as _ilu

def _load_fx_bi_module():
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("chan_fx_bi.py", "分型+笔.py"):
        path = os.path.join(here, name)
        if os.path.exists(path):
            spec = _ilu.spec_from_file_location("chan_fx_bi", path)
            mod = _ilu.module_from_spec(spec)
            sys.modules["chan_fx_bi"] = mod  # 先注册，供 dataclass 解析
            spec.loader.exec_module(mod)
            return mod
    raise ImportError("未找到 chan_fx_bi.py 或 分型+笔.py（请与本脚本放在同一目录）")

cb = _load_fx_bi_module()

KHDATA = r"D:\khData"

# =====================================================================
# 一、数据层：从 D:\khData 读取K线（复刻 chan_trend.py 读取逻辑）
# =====================================================================

FREQ_ALIASES = {
    "1分钟": "1分钟", "1m": "1分钟", "1min": "1分钟", "1分": "1分钟",
    "5分钟": "5分钟", "5m": "5分钟", "5min": "5分钟", "5分": "5分钟",
    "15分钟": "15分钟", "15m": "15分钟",
    "30分钟": "30分钟", "30m": "30分钟",
    "60分钟": "60分钟", "60m": "60分钟", "1小时": "60分钟",
    "120分钟": "120分钟", "120m": "120分钟",
    "日线": "日线", "日": "日线", "d": "日线", "D": "日线", "day": "日线",
    "周线": "周线", "周": "周线", "w": "周线", "W": "周线", "week": "周线",
    "月线": "月线", "月": "月线", "m": "月线", "M": "月线", "month": "月线",
}


def _mk_bar(symbol, freq, dt, o, c, h, l, v, a, id_=0):
    return cb.RawBar(symbol, dt, o, c, h, l, v, a, id_, freq)


def resolve_symbol(code):
    """解析股票代码 → (代码, 市场)。支持 000001.SH / 600000 / 300750"""
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


def find_db(code, exchange):
    """定位数据库文件路径"""
    if exchange:
        p = os.path.join(KHDATA, exchange, code + ".db")
        if os.path.exists(p):
            return p
        return None
    for ex in ("SH", "SZ", "BJ"):
        p = os.path.join(KHDATA, ex, code + ".db")
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
    raise ValueError(f"无法解析日期: {s}（支持 YYYY-MM-DD 或 YYYYMMDD）")


def resample_minutes(bars_1m, minutes):
    """1分钟 → N分钟（A股 09:30-11:30 / 13:00-15:00 分桶）"""
    buckets = {}
    for b in bars_1m:
        t = b.dt
        hm = t.hour * 60 + t.minute
        if 9 * 60 + 30 <= hm <= 11 * 60 + 29:
            off = hm - (9 * 60 + 30)
            sess = 0
        elif 13 * 60 <= hm <= 15 * 60 - 1:
            off = hm - 13 * 60
            sess = 1
        else:
            continue
        key = (t.date(), sess, off // minutes)
        buckets.setdefault(key, []).append(b)
    out = []
    for key in sorted(buckets):
        bs = buckets[key]
        out.append(_mk_bar(bs[0].symbol, bs[0].freq, bs[-1].dt,
                           bs[0].open, bs[-1].close,
                           max(b.high for b in bs), min(b.low for b in bs),
                           sum(b.vol for b in bs), sum(b.amount for b in bs)))
    return out


def resample_daily(bars_1d, target):
    """日线 → 周线/月线"""
    buckets = {}
    for b in bars_1d:
        t = b.dt
        key = t.isocalendar()[:2] if target == "W" else (t.year, t.month)
        buckets.setdefault(key, []).append(b)
    out = []
    for key in sorted(buckets):
        bs = buckets[key]
        out.append(_mk_bar(bs[0].symbol, bs[0].freq, bs[-1].dt,
                           bs[0].open, bs[-1].close,
                           max(b.high for b in bs), min(b.low for b in bs),
                           sum(b.vol for b in bs), sum(b.amount for b in bs)))
    return out


def _load_prewarm(db_path, first_bar, freq, n):
    """向前补 n 根K线（freq 与主数据一致）"""
    try:
        con = duckdb.connect(db_path, read_only=True)
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
                [first_bar.dt, n * mult]).fetchall()
        finally:
            con.close()
    except Exception:
        return []
    rows = list(reversed(rows))
    bars = [_mk_bar(first_bar.symbol, first_bar.freq, r[0], float(r[1]), float(r[4]),
                    float(r[2]), float(r[3]), float(r[5]), float(r[6] or 0))
            for r in rows if r[1] is not None and r[4] is not None]
    if freq in ("15分钟", "30分钟", "60分钟", "120分钟"):
        bars = resample_minutes(bars, int(freq.replace("分钟", "")))
        bars = [b for b in bars if b.dt < first_bar.dt]
    elif freq == "周线":
        bars = resample_daily(bars, "W")
        bars = [b for b in bars if b.dt < first_bar.dt]
    elif freq == "月线":
        bars = resample_daily(bars, "M")
        bars = [b for b in bars if b.dt < first_bar.dt]
    return bars[-n:]


def load_bars(code, exchange, freq, sdt, edt, prewarm_bars=600):
    """从 DuckDB 读取K线并按需重采样。
    返回 (symbol_label, bars, prewarm_count)"""
    db_path = find_db(code, exchange)
    if not db_path:
        raise FileNotFoundError(f"未找到 {code} 的数据文件（{KHDATA} 下无 {code}.db）")

    con = duckdb.connect(db_path, read_only=True)
    try:
        tables = {r[0] for r in con.sql("SHOW TABLES").fetchall()}

        if freq in ("1分钟", "15分钟", "30分钟", "60分钟", "120分钟"):
            need = "kline_1m"
            if need not in tables:
                raise RuntimeError(f"{code} 没有 {need} 数据")
            rows = con.execute(
                f"SELECT time, open, high, low, close, volume, amount FROM {need} "
                f"WHERE time::DATE >= ? AND time::DATE <= ? ORDER BY time",
                [sdt.date(), edt.date()]).fetchall()
            bars = [_mk_bar(f"{code}.{exchange}", freq, r[0], float(r[1]), float(r[4]),
                            float(r[2]), float(r[3]), float(r[5]), float(r[6] or 0), i)
                    for i, r in enumerate(rows) if r[1] is not None and r[4] is not None]
            if freq != "1分钟":
                bars = resample_minutes(bars, int(freq.replace("分钟", "")))
        elif freq == "5分钟":
            need = "kline_5m"
            if need not in tables:
                raise RuntimeError(f"{code} 没有 {need} 数据")
            rows = con.execute(
                f"SELECT time, open, high, low, close, volume, amount FROM {need} "
                f"WHERE time::DATE >= ? AND time::DATE <= ? ORDER BY time",
                [sdt.date(), edt.date()]).fetchall()
            bars = [_mk_bar(f"{code}.{exchange}", freq, r[0], float(r[1]), float(r[4]),
                            float(r[2]), float(r[3]), float(r[5]), float(r[6] or 0), i)
                    for i, r in enumerate(rows) if r[1] is not None and r[4] is not None]
        elif freq in ("日线", "周线", "月线"):
            need = "kline_1d"
            if need not in tables:
                raise RuntimeError(f"{code} 没有 {need} 数据")
            rows = con.execute(
                f"SELECT time, open, high, low, close, volume, amount FROM {need} "
                f"WHERE time::DATE >= ? AND time::DATE <= ? ORDER BY time",
                [sdt.date(), edt.date()]).fetchall()
            bars = [_mk_bar(f"{code}.{exchange}", freq, r[0], float(r[1]), float(r[4]),
                            float(r[2]), float(r[3]), float(r[5]), float(r[6] or 0), i)
                    for i, r in enumerate(rows) if r[1] is not None and r[4] is not None]
            if freq == "周线":
                bars = resample_daily(bars, "W")
            elif freq == "月线":
                bars = resample_daily(bars, "M")
        else:
            raise ValueError(f"不支持的周期: {freq}")
    finally:
        con.close()

    if not bars:
        raise RuntimeError(f"{code} 在 {sdt.date()}~{edt.date()} 区间内无 {freq} 数据")

    # 预热：向前补足K线，保证缠论结构充分构建
    if prewarm_bars > 0 and len(bars) < prewarm_bars:
        pre = _load_prewarm(db_path, bars[0], freq, prewarm_bars - len(bars))
        bars = pre + bars
        prewarm = len(pre)
    else:
        prewarm = 0
    return f"{code}.{exchange}", bars, prewarm


# =====================================================================
# 二、终端文本报告
# =====================================================================

def print_report(label, freq, sdt, edt, bars, prewarm, c: cb.CZSC):
    line = "=" * 64
    sub = "-" * 64
    print()
    print(line)
    print("                   缠论 · 分型与笔 分析报告")
    print(line)
    print(f"标的：{label}")
    print(f"周期：{freq}   |   判断区间：{sdt.date()} ~ {edt.date()}")
    print(f"K线：{len(bars)} 根（含 {prewarm} 根历史预热）"
          f"   |   最新K线时间：{c.bars_raw[-1].dt:%Y-%m-%d %H:%M}")
    print(sub)

    # ---- 结构统计 ----
    fxs = c.fx_list
    g_cnt = sum(1 for x in fxs if x.mark == "G")
    d_cnt = sum(1 for x in fxs if x.mark == "D")
    bis = c.bi_list
    up_cnt = sum(1 for b in bis if b.direction == "Up")
    dn_cnt = sum(1 for b in bis if b.direction == "Down")
    print("[结构统计]")
    print(f"  去包含K线（未完成笔）：{len(c.bars_ubi)} 根")
    print(f"  分型：{len(fxs)} 个（顶 {g_cnt} / 底 {d_cnt}，含笔内部分型）")
    print(f"  笔：{len(bis)} 笔（向上 {up_cnt} / 向下 {dn_cnt}）")
    print(f"  最后一笔延伸中：{'是' if c.last_bi_extend else '否'}")
    print(sub)

    # ---- 笔清单 ----
    print(f"[笔清单]（共 {len(bis)} 笔）")
    if not bis:
        print("  暂无已完成笔（数据过短）")
    for i, b in enumerate(bis, 1):
        d = "向上" if b.direction == "Up" else "向下"
        print(f"  {i:>2}. {d}  {b.start_dt:%Y-%m-%d %H:%M} -> {b.end_dt:%Y-%m-%d %H:%M}"
              f"  区间[{b.get_low():.3f}, {b.get_high():.3f}]"
              f"  长度{b.get_length()}根  价差{b.get_power():.3f}")
    print(sub)

    # ---- 分型清单 ----
    print(f"[分型清单]（共 {len(fxs)} 个，按时间顺序，顶/底交替）")
    if not fxs:
        print("  暂无分型")
    for i, fx in enumerate(fxs, 1):
        t = "顶" if fx.mark == "G" else "底"
        print(f"  {i:>2}. {t}  {fx.dt:%Y-%m-%d %H:%M}  值={fx.fx:.3f}"
              f"  强度={fx.power_str()}  量能={fx.power_volume():.0f}")
    print(line)
    print("（以上为缠论技术分析参考，不构成投资建议）")
    print()


# =====================================================================
# 三、HTML 图表报告（ECharts：K线 + 笔 + 顶/底分型 + 成交量）
# =====================================================================

def _ts(dt):
    return int(dt.timestamp() * 1000)


def _echarts_src(html_path):
    """优先本地 assets/echarts.min.js，否则 CDN"""
    base = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(base, "assets", "echarts.min.js")
    if os.path.exists(local):
        rel = os.path.relpath(local, os.path.dirname(os.path.abspath(html_path)))
        return rel.replace("\\", "/")
    return "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script src="__ECHARTS__"></script>
<script>if(!window.echarts){document.write('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"><\\/script>')}</script>
<style>
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;margin:0;background:#f5f6fa;color:#333}
.wrap{max-width:1280px;margin:0 auto;padding:16px}
.header{background:#fff;border-radius:10px;padding:16px 22px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.header h1{margin:0 0 8px;font-size:22px;color:#1a1a1a}
.header .meta{color:#666;font-size:13px;line-height:1.9}
#chart{background:#fff;border-radius:10px;padding:6px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.report{background:#fff;border-radius:10px;padding:18px 22px;margin-top:14px;box-shadow:0 1px 4px rgba(0,0,0,.08);font-size:14px;line-height:1.95}
.report h2{font-size:16px;border-left:4px solid #2f6fed;padding-left:10px;margin:16px 0 8px}
.report h2:first-child{margin-top:0}
table.kv{width:100%;border-collapse:collapse;margin-top:4px}
table.kv td{border:1px solid #eee;padding:6px 12px}
table.kv td:first-child{background:#fafbfc;color:#666;width:130px}
table.bi{width:100%;border-collapse:collapse;margin-top:4px}
table.bi th,table.bi td{border:1px solid #eee;padding:6px 10px;text-align:left;font-size:13px}
table.bi th{background:#fafbfc;color:#666;font-weight:normal}
table.bi tr.up td.dir{color:#e0503e;font-weight:bold}
table.bi tr.down td.dir{color:#1a9a5a;font-weight:bold}
.footer{color:#999;font-size:12px;text-align:center;margin:16px 0 30px}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>缠论 · 分型与笔 · __SYMBOL__</h1>
    <div class="meta">
      周期：__FREQ__ ｜ 判断区间：__SDT__ ~ __EDT__ ｜ 数据：__BARS__ 根原始K线（含 __PREWARM__ 根历史预热）<br>
      最新K线：__CLOSEDT__ ｜ 分型：__FXS__ 个（顶 __GFX__ / 底 __DFX__）｜ 笔：__BIS__ 笔（向上 __UPBIS__ / 向下 __DNBIS__）
    </div>
  </div>
  <div id="chart" style="width:100%;height:__CHART_H__px;"></div>
  <div class="report">
    <h2>笔清单</h2>
    <table class="bi">
      <tr><th>#</th><th>方向</th><th>起点分型</th><th>终点分型</th><th>起始时间</th><th>结束时间</th><th>区间 [低, 高]</th><th>长度</th><th>价差</th></tr>
      __BI_ROWS__
    </table>
    <h2>分型清单</h2>
    <table class="bi">
      <tr><th>#</th><th>类型</th><th>时间</th><th>分型值</th><th>强度</th><th>量能</th></tr>
      __FX_ROWS__
    </table>
  </div>
  <div class="footer">本报告由 chan_report.py 自动生成（仅分型与笔，不含中枢/买卖点）｜ 缠论技术分析仅供参考，不构成投资建议</div>
</div>
<script>
var DATA = __DATA__;
var chart = echarts.init(document.getElementById('chart'));
var option = {
  animation:false,
  tooltip:{trigger:'axis',axisPointer:{type:'cross'},backgroundColor:'rgba(255,255,255,.96)',borderColor:'#ddd',textStyle:{color:'#333',fontSize:12}},
  legend:{data:['K线','笔','顶分型','底分型'],top:6,textStyle:{fontSize:12}},
  axisPointer:{link:[{xAxisIndex:'all'}]},
  grid:[
    {left:70,right:28,top:42,height:'62%'},
    {left:70,right:28,top:'72%',height:'15%'}
  ],
  xAxis:[
    {type:'category',gridIndex:0,data:DATA.catLabels,axisLabel:{interval:DATA.labelInterval,color:'#666'},axisLine:{lineStyle:{color:'#ccc'}}},
    {type:'category',gridIndex:1,data:DATA.catLabels,axisLabel:{show:false}}
  ],
  yAxis:[
    {gridIndex:0,scale:true,splitLine:{lineStyle:{color:'#f0f0f0'}},axisLabel:{color:'#666'}},
    {gridIndex:1,scale:true,splitLine:{show:false},axisLabel:{color:'#999',fontSize:10}}
  ],
  dataZoom:[
    {type:'inside',xAxisIndex:[0,1],start:DATA.zoomStart,end:100},
    {type:'slider',xAxisIndex:[0,1],bottom:4,start:DATA.zoomStart,end:100,height:16}
  ],
  series:[
    {name:'K线',type:'candlestick',data:DATA.kline,itemStyle:{color:'#e0503e',color0:'#1a9a5a',borderColor:'#e0503e',borderColor0:'#1a9a5a'}},
    {name:'笔',type:'line',data:DATA.biLine,symbol:'none',lineStyle:{width:1.6,color:'#222'},z:6},
    {name:'顶分型',type:'scatter',data:DATA.topFx,symbol:'triangle',symbolSize:12,itemStyle:{color:'#e0503e',borderColor:'#a02010',borderWidth:0.5},z:7},
    {name:'底分型',type:'scatter',data:DATA.bottomFx,symbol:'triangle',symbolRotate:180,symbolSize:12,itemStyle:{color:'#1a9a5a',borderColor:'#0a6a3a',borderWidth:0.5},z:7},
    {name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:DATA.vols,itemStyle:{color:function(p){return p.data[1]>0?'#e0503e':'#1a9a5a'}}}
  ]
};
chart.setOption(option);
window.addEventListener('resize',function(){chart.resize();});
</script>
</body>
</html>
"""


def render_html(label, freq, sdt, edt, bars, prewarm, c: cb.CZSC, out_path=None):
    """生成自包含 HTML 图表报告，返回文件路径"""
    # 前端K线 = 全序列去包含K线（独立重算，CZSC.bars_ubi 只留尾部）
    ubi = _remove_include_all(bars)
    n = len(ubi)
    dts = [b.dt for b in ubi]
    opens = [b.open for b in ubi]
    closes = [b.close for b in ubi]
    highs = [b.high for b in ubi]
    lows = [b.low for b in ubi]
    vols = [b.vol for b in ubi]

    def _to_idx(dt, mode="right"):
        if mode == "left":
            return bisect.bisect_left(dts, dt)
        return bisect.bisect_right(dts, dt) - 1

    def _fmt_dt(dt):
        if freq in ("日线", "周线", "月线"):
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%m-%d %H:%M")

    cat_labels = []
    for nb in ubi:
        ds = [e.dt for e in nb.elements]
        if len(ds) == 1:
            cat_labels.append(_fmt_dt(ds[0]))
        else:
            cat_labels.append("、".join(_fmt_dt(d) for d in ds))
    label_interval = max(1, n // 14)

    kline = [[opens[i], closes[i], lows[i], highs[i]] for i in range(n)]
    vol_data = [[vols[i], 1 if closes[i] >= opens[i] else -1] for i in range(n)]

    # 笔线（端点连线，索引坐标）
    bis_ = c.bi_list
    bi_line = []
    for b in bis_:
        bi_line.append([_to_idx(b.fx_a.dt), round(b.fx_a.fx, 3)])
        bi_line.append([_to_idx(b.fx_b.dt), round(b.fx_b.fx, 3)])

    # 分型（笔端点分型，避免笔内部分型堆叠）
    top_fx, bottom_fx, seen = [], [], set()
    for b in bis_:
        for fx in (b.fx_a, b.fx_b):
            key = (_to_idx(fx.dt), fx.mark)
            if key in seen:
                continue
            seen.add(key)
            if fx.mark == "G":
                top_fx.append([_to_idx(fx.dt), round(fx.high, 3)])
            else:
                bottom_fx.append([_to_idx(fx.dt), round(fx.low, 3)])

    # ---- 统计 ----
    fxs = c.fx_list
    g_cnt = sum(1 for x in fxs if x.mark == "G")
    d_cnt = sum(1 for x in fxs if x.mark == "D")
    up_cnt = sum(1 for b in bis_ if b.direction == "Up")
    dn_cnt = sum(1 for b in bis_ if b.direction == "Down")

    bi_rows = []
    for i, b in enumerate(bis_, 1):
        cls = "up" if b.direction == "Up" else "down"
        d = "向上" if b.direction == "Up" else "向下"
        bi_rows.append(
            f"<tr class='{cls}'><td>{i}</td><td class='dir'>{d}</td>"
            f"<td>{'顶' if b.fx_a.mark == 'G' else '底'} {b.fx_a.fx:.3f}</td>"
            f"<td>{'顶' if b.fx_b.mark == 'G' else '底'} {b.fx_b.fx:.3f}</td>"
            f"<td>{b.start_dt:%Y-%m-%d %H:%M}</td><td>{b.end_dt:%Y-%m-%d %H:%M}</td>"
            f"<td>[{b.get_low():.3f}, {b.get_high():.3f}]</td>"
            f"<td>{b.get_length()}</td><td>{b.get_power():.3f}</td></tr>")
    fx_rows = []
    for i, fx in enumerate(fxs, 1):
        t = "顶" if fx.mark == "G" else "底"
        fx_rows.append(
            f"<tr><td>{i}</td><td>{t}</td><td>{fx.dt:%Y-%m-%d %H:%M}</td>"
            f"<td>{fx.fx:.3f}</td><td>{fx.power_str()}</td>"
            f"<td>{fx.power_volume():.0f}</td></tr>")

    chart_h = 620 if n > 200 else 560

    js_data = {
        "catLabels": cat_labels, "labelInterval": label_interval,
        "kline": kline, "biLine": bi_line,
        "topFx": top_fx, "bottomFx": bottom_fx,
        "vols": vol_data,
        "zoomStart": max(0, round((1 - 800.0 / max(n, 1)) * 100)),
    }

    if out_path:
        out_path = os.path.abspath(out_path)
    else:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "%s_%s_%s.html" % (
            label.replace(".", "_"), freq, edt.strftime("%Y%m%d")))

    html = _HTML_TEMPLATE
    html = html.replace("__TITLE__", "缠论·分型与笔 %s %s" % (label, freq))
    html = html.replace("__ECHARTS__", _echarts_src(out_path))
    html = html.replace("__SYMBOL__", label)
    html = html.replace("__FREQ__", freq)
    html = html.replace("__SDT__", str(sdt.date()))
    html = html.replace("__EDT__", str(edt.date()))
    html = html.replace("__BARS__", str(len(bars)))
    html = html.replace("__PREWARM__", str(prewarm))
    html = html.replace("__CLOSEDT__", c.bars_raw[-1].dt.strftime("%Y-%m-%d %H:%M"))
    html = html.replace("__FXS__", str(len(fxs)))
    html = html.replace("__GFX__", str(g_cnt))
    html = html.replace("__DFX__", str(d_cnt))
    html = html.replace("__BIS__", str(len(bis_)))
    html = html.replace("__UPBIS__", str(up_cnt))
    html = html.replace("__DNBIS__", str(dn_cnt))
    html = html.replace("__BI_ROWS__", "".join(bi_rows))
    html = html.replace("__FX_ROWS__", "".join(fx_rows))
    html = html.replace("__CHART_H__", str(chart_h))
    html = html.replace("__DATA__", json.dumps(js_data, ensure_ascii=False))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def _remove_include_all(bars_raw):
    """对整个K线序列做去包含处理，返回完整的去包含K线列表（用于图表展示）。"""
    ubi = []
    for b in bars_raw:
        if len(ubi) < 2:
            ubi.append(cb.NewBar.from_raw(b))
        else:
            has_inc, merged = cb.remove_include(ubi[-2], ubi[-1], b)
            if has_inc:
                ubi[-1] = merged
            else:
                ubi.append(merged)
    return ubi


# =====================================================================
# 四、主程序
# =====================================================================

def main():
    args = sys.argv[1:]
    if len(args) >= 4:
        code_in, freq_in, sdt_in, edt_in = args[:4]
        auto_mode = True
    else:
        auto_mode = False
        print("=" * 64)
        print("              缠论 · 分型与笔 报告程序")
        print("=" * 64)
        print("数据源：D:\\khData（DuckDB）")
        print("支持周期：1分钟 / 5分钟 / 15分钟 / 30分钟 / 60分钟 / 120分钟 / 日线 / 周线 / 月线")
        print("示例：600000.SH  或  000001.SZ  或  300750")
        print("输入 q 退出")
        print("-" * 64)
        code_in = input("请输入股票代码：").strip()
        if code_in.lower() in ("q", "quit", "exit"):
            return
        freq_in = input("请输入周期级别（如 日线 / 30分钟 / 5分钟）：").strip()
        if freq_in.lower() in ("q", "quit", "exit"):
            return
        sdt_in = input("请输入起始日期（YYYY-MM-DD）：").strip()
        if sdt_in.lower() in ("q", "quit", "exit"):
            return
        edt_in = input("请输入终止日期（YYYY-MM-DD）：").strip()
        if edt_in.lower() in ("q", "quit", "exit"):
            return

    code_in = code_in.strip()
    freq = FREQ_ALIASES.get(freq_in.strip())
    if not freq:
        print(f"[错误] 不支持的周期：{freq_in}")
        return

    try:
        sdt = _parse_date(sdt_in)
        edt = _parse_date(edt_in)
    except ValueError as e:
        print(f"[错误] {e}")
        return
    if sdt > edt:
        print("[错误] 起始日期不能晚于终止日期")
        return

    code, exchange = resolve_symbol(code_in)
    if not exchange:
        print(f"[错误] 无法判断 {code_in} 的市场（沪市60/68开头，深市00/30开头）")
        return

    try:
        label, bars, prewarm = load_bars(code, exchange, freq, sdt, edt)
        c = cb.CZSC(bars, max_bi_num=50, min_bi_len=6)
        print_report(label, freq, sdt, edt, bars, prewarm, c)

        want_html = True
        if not auto_mode:
            ans = input("是否生成 HTML 图表报告（K线+笔+分型）？(y/n，默认 y)：").strip().lower()
            want_html = ans not in ("n", "no")
        if want_html:
            out_html = render_html(label, freq, sdt, edt, bars, prewarm, c)
            print(f"[HTML] 报告已生成：{out_html}")
            open_browser = True
            if not auto_mode:
                ans = input("是否用浏览器打开？(y/n，默认 y)：").strip().lower()
                open_browser = ans not in ("n", "no")
            if open_browser:
                try:
                    import webbrowser
                    webbrowser.open("file:///" + out_html.replace("\\", "/"))
                except Exception:
                    pass
    except Exception as e:
        print(f"[错误] {e}")
        return


if __name__ == "__main__":
    main()
