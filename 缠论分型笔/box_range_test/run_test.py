# -*- coding: utf-8 -*-
"""
真实数据测试 + HTML 报告生成（RangeBoxFinder 独立测试）
====================================================
只调用已有类/函数（chan_report.load_bars / core.chan_analyzer.ChanAnalyzer），
不修改任何源码；所有产物都在本 box_range_test 目录内，测试完可直接删整个目录。

用法：
  python run_test.py                          # 跑默认三个标的
  python run_test.py --symbols 600519.SH --freq 日线 --start 20250101 --end 20260904
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CHAN_PATH = r"D:\量化k线\缠论分型笔"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CHAN_PATH)
sys.path.insert(0, HERE)

from datetime import datetime  # noqa: E402

from chan_report import load_bars, resolve_symbol  # noqa: E402  已有数据层（只调用）
from range_box_finder import RangeBoxFinder  # noqa: E402

# 可选：调用已有缠论分析器拿笔端点分型作参照（只读，不修改）
def _chan_fxs(bars, symbol, freq):
    try:
        from core.chan_analyzer import ChanAnalyzer
        ana = ChanAnalyzer(bars, symbol=symbol, freq=freq)
        return ana.fxs
    except Exception as e:
        print(f"  [提示] 调用 ChanAnalyzer 拿分型参照失败（不影响主结果）: {e}")
        return []


DEFAULT_SYMBOLS = [
    ("000001.SH", "日线", "20250101", "20260904"),
    ("600887.SH", "日线", "20250601", "20260904"),
    ("000300.SH", "30分钟", "20260801", "20260904"),
]

# 演示参数：类默认值=用户示例（峰谷容差 0.15W，日线上极严格，常识别 0 个）；
# 这里放宽到 0.25W 以便在日线/30分钟真实数据上展示效果。可自行调整或改回严格值。
DEMO_PARAMS = dict(peak_tol=0.25, trough_tol=0.25)


def _parse_dt(s):
    return datetime.strptime(s, "%Y%m%d")


def _fmt_dt(dt, freq):
    return dt.strftime("%m-%d %H:%M") if "分钟" in freq else dt.strftime("%Y-%m-%d")


def analyze_one(symbol, freq, sdt, edt, params=None, with_chan=True):
    code, ex = resolve_symbol(symbol)
    label, bars, prewarm = load_bars(code, ex, freq, _parse_dt(sdt), _parse_dt(edt),
                                     prewarm_bars=600)
    finder = RangeBoxFinder(**(params or DEMO_PARAMS))
    boxes = finder.find(bars)
    fxs = _chan_fxs(bars, label, freq) if with_chan else []
    return label, bars, prewarm, finder, boxes, fxs


# =====================================================================
# 文本摘要
# =====================================================================
def print_text(label, freq, bars, prewarm, finder, boxes):
    print("=" * 76)
    print(f"标的 {label}  {freq}   K线 {len(bars)} 根（含 {prewarm} 根预热）  "
          f"最新 {bars[-1].dt:%Y-%m-%d %H:%M}")
    print(f"识别出盘整箱体 {len(boxes)} 个（转折点 {len(finder.turns)} 个）  "
          f"参数: 峰谷容差={finder.peak_tol}W/{finder.trough_tol}W, 最小{finder.min_bars}根, "
          f"显著度={finder.prominence_atr}xATR, 突破确认={finder.breakout_confirm}根")
    print("-" * 76)
    if not boxes:
        print("  （无满足条件的箱体）")
        return
    print(f"{'#':>2} {'开始(回填)':<16} {'结束(回填)':<16} {'上沿':>9} {'下沿':>9} "
          f"{'宽%':>6} {'峰':>3} {'谷':>3} {'覆盖':>5} {'状态':<14} {'确认时间':<16}")
    for i, b in enumerate(boxes, 1):
        d = b.to_dict()
        print(f"{i:>2} {d['start_time']:<16} {d['end_time']:<16} {d['upper']:>9.2f} "
              f"{d['lower']:>9.2f} {d['width_pct']:>6.2f} {d['n_peaks']:>3} "
              f"{d['n_troughs']:>3} {d['cover_ratio']:>5.2f} {d['status']:<14} "
              f"{str(d['confirm_time']):<16}")
    print("-" * 76)
    print("说明：start/end/上下沿为事后回填；confirm_time 之前的信息才是当时可知的。")
    print()


# =====================================================================
# HTML 报告（ECharts 深色金融风格，离线可打开）
# =====================================================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="{echarts_src}"></script>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0e1218; color:#c9d2de; font-family:"Microsoft YaHei","PingFang SC",sans-serif; padding:24px 28px 60px; }}
  h1 {{ font-size:22px; font-weight:600; color:#e8edf4; margin-bottom:4px; }}
  h2 {{ font-size:16px; color:#8fa3bd; font-weight:400; margin-bottom:18px; }}
  .cards {{ display:flex; gap:14px; flex-wrap:wrap; margin-bottom:20px; }}
  .card {{ background:#151b26; border:1px solid #232c3b; border-radius:10px; padding:12px 18px; min-width:150px; }}
  .card .k {{ color:#8fa3bd; font-size:12px; margin-bottom:6px; }}
  .card .v {{ color:#e8edf4; font-size:18px; font-weight:600; }}
  .chart {{ width:100%; height:620px; background:#12161f; border:1px solid #232c3b; border-radius:10px; margin-bottom:20px; }}
  table {{ width:100%; border-collapse:collapse; background:#12161f; border:1px solid #232c3b; border-radius:10px; overflow:hidden; font-size:13px; }}
  th {{ background:#1a2230; color:#8fa3bd; text-align:left; padding:10px 12px; font-weight:500; white-space:nowrap; }}
  td {{ padding:9px 12px; border-top:1px solid #1d2533; }}
  tr:hover td {{ background:#171e2b; }}
  .up {{ color:#ef5350; }} .dn {{ color:#26a69a; }} .open {{ color:#f2b84b; }}
  .note {{ margin-top:14px; font-size:12px; color:#6b7a90; line-height:1.8; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:12px; }}
  .b-up {{ background:#3a1d1d; color:#ef8a80; }}
  .b-dn {{ background:#14352f; color:#5fd6c4; }}
  .b-open {{ background:#3a2f14; color:#f2c14b; }}
</style>
</head>
<body>
<h1>{title}</h1>
<h2>{subtitle}</h2>
<div class="cards">
  <div class="card"><div class="k">K线</div><div class="v">{n_bars}</div></div>
  <div class="card"><div class="k">预热</div><div class="v">{n_prewarm}</div></div>
  <div class="card"><div class="k">转折点</div><div class="v">{n_turns}</div></div>
  <div class="card"><div class="k">盘整箱体</div><div class="v">{n_boxes}</div></div>
  <div class="card"><div class="k">已确认结束</div><div class="v">{n_confirmed}</div></div>
</div>
<div id="main" class="chart"></div>
<h2 style="margin-bottom:10px;">盘整箱体明细</h2>
{table_html}
<div class="note">
  <b>未来函数警告：</b>本识别器使用「未来K线」确认波峰/波谷与突破，起点/终点/上下沿均为<b>事后回填</b>，
  仅用于历史标注与回测研究，<b>不可</b>当作当时已知的信号。<br>
  实际确认时间(confirm_time) = 连续第 {confirm_n} 根收盘价突破边界的那根K线 —— 该时刻之前的信息才是回测时可用的。
  数据末尾仍未确认突破的箱体标记为「尚未结束」。<br>
  调用链：<code>chan_report.load_bars</code>（已有数据层，只读调用）→ <code>RangeBoxFinder</code>（本测试目录新类）→ HTML 报告。
  本目录可整体删除，不影响任何现有源码。
</div>
<script>
{chart_js}
</script>
</body>
</html>
"""


def _ts(dt):
    return int(dt.timestamp() * 1000)


def build_chart_js(label, freq, bars, finder, boxes, fxs):
    fmt = "%m-%d %H:%M" if "分钟" in freq else "%Y-%m-%d"
    cats = [b.dt.strftime(fmt) for b in bars]
    kdata = [[b.open, b.close, b.low, b.high] for b in bars]
    vols = [[i, b.vol, b.close >= b.open] for i, b in enumerate(bars)]

    peak_pts = [[cats[t.idx], round(t.price, 4)] for t in finder.turns if t.kind == "P"]
    tr_pts = [[cats[t.idx], round(t.price, 4)] for t in finder.turns if t.kind == "T"]

    # 箱体 markArea + 上下沿 markLine
    areas = []
    hlines = []
    bo_markers = []
    for b in boxes:
        s, e = b.start_time.strftime(fmt), b.end_time.strftime(fmt)
        areas.append([{"xAxis": s, "yAxis": round(b.upper, 4),
                       "itemStyle": {"color": "rgba(242,184,75,0.10)",
                                     "borderColor": "rgba(242,184,75,0.35)",
                                     "borderWidth": 1}},
                      {"xAxis": e, "yAxis": round(b.lower, 4)}])
        hlines.append({"yAxis": round(b.upper, 4),
                       "lineStyle": {"color": "rgba(242,184,75,0.5)", "type": "dashed", "width": 1},
                       "label": {"formatter": "上沿 {c}", "color": "#f2b84b", "fontSize": 10}})
        hlines.append({"yAxis": round(b.lower, 4),
                       "lineStyle": {"color": "rgba(38,166,154,0.5)", "type": "dashed", "width": 1},
                       "label": {"formatter": "下沿 {c}", "color": "#26a69a", "fontSize": 10}})
        if b.confirmed:
            t = bars[b.confirm_idx]
            if b.direction == "up":
                y = max(x.high for x in bars[b.core_start_idx:b.confirm_idx + 1]) * 1.002
                sym, color = "triangle", "#ef5350"
            else:
                y = min(x.low for x in bars[b.core_start_idx:b.confirm_idx + 1]) * 0.998
                sym, color = "triangle", "#26a69a"
            bo_markers.append({"name": "确认",
                               "coord": [t.dt.strftime(fmt), round(y, 4)],
                               "value": "确认", "symbol": sym,
                               "symbolSize": 12,
                               "itemStyle": {"color": color, "borderColor": "#fff",
                                             "borderWidth": 1}})

    # 分型参照（已有 ChanAnalyzer 输出，白色小三角）
    fx_pts = []
    if fxs:
        for fx in fxs:
            fx_pts.append([fx.dt.strftime(fmt), fx.fx,
                           "顶" if fx.mark == "G" else "底"])

    option = {
        "backgroundColor": "transparent",
        "animation": False,
        "legend": {"data": ["K线", "波峰", "波谷", "突破确认", "缠论分型"],
                   "textStyle": {"color": "#8fa3bd"}, "top": 6},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"},
                    "backgroundColor": "#151b26", "borderColor": "#2a3547",
                    "textStyle": {"color": "#d6deea", "fontSize": 12}},
        "axisPointer": {"link": [{"xAxisIndex": "all"}]},
        "grid": [{"left": 64, "right": 24, "top": 46, "height": "58%"},
                 {"left": 64, "right": 24, "top": "74%", "height": "16%"}],
        "xAxis": [
            {"type": "category", "data": cats, "gridIndex": 0,
             "axisLine": {"lineStyle": {"color": "#2a3547"}},
             "axisLabel": {"color": "#7d8ca3", "fontSize": 10},
             "splitLine": {"show": False}},
            {"type": "category", "data": cats, "gridIndex": 1,
             "axisLine": {"lineStyle": {"color": "#2a3547"}},
             "axisLabel": {"show": False}, "splitLine": {"show": False}},
        ],
        "yAxis": [
            {"scale": True, "gridIndex": 0, "position": "right",
             "axisLabel": {"color": "#7d8ca3", "fontSize": 10},
             "splitLine": {"lineStyle": {"color": "#1b232f"}}},
            {"scale": True, "gridIndex": 1, "position": "right",
             "axisLabel": {"color": "#7d8ca3", "fontSize": 9},
             "splitLine": {"show": False}},
        ],
        "dataZoom": [
            {"type": "inside", "xAxisIndex": [0, 1], "start": 0, "end": 100},
            {"type": "slider", "xAxisIndex": [0, 1], "start": 0, "end": 100,
             "height": 16, "bottom": 8,
             "textStyle": {"color": "#7d8ca3"},
             "borderColor": "#232c3b", "fillerColor": "rgba(120,140,170,0.15)"},
        ],
        "series": [
            {"name": "K线", "type": "candlestick", "data": kdata,
             "itemStyle": {"color": "#ef5350", "color0": "#26a69a",
                           "borderColor": "#ef5350", "borderColor0": "#26a69a"},
             "markArea": {"silent": True, "data": areas},
             "markLine": {"symbol": "none", "silent": True, "data": hlines}},
            {"name": "波峰", "type": "scatter", "data": peak_pts,
             "symbol": "triangle", "symbolSize": 9,
             "itemStyle": {"color": "#f2b84b", "borderColor": "#0e1218", "borderWidth": 1},
             "z": 5},
            {"name": "波谷", "type": "scatter", "data": tr_pts,
             "symbol": "triangle", "symbolRotate": 180, "symbolSize": 9,
             "itemStyle": {"color": "#4fc3f7", "borderColor": "#0e1218", "borderWidth": 1},
             "z": 5},
            {"name": "突破确认", "type": "scatter", "data": bo_markers, "z": 6},
            {"name": "缠论分型", "type": "scatter", "data": fx_pts,
             "symbol": "diamond", "symbolSize": 7,
             "itemStyle": {"color": "rgba(255,255,255,0.35)"}, "z": 2},
            {"name": "成交量", "type": "bar", "xAxisIndex": 1, "yAxisIndex": 1,
             "data": vols,
             "itemStyle": {"color": "rgba(239,83,80,0.55)"}},
        ],
    }
    # 成交量按涨跌分色
    option["series"][5]["data"] = [[i, b.vol, 1] for i, b in enumerate(bars)]
    return "var option = " + json.dumps(option, ensure_ascii=False) + ";" + """
option.series[5].itemStyle.color = function(p){ return p.data[2] ? 'rgba(239,83,80,0.55)' : 'rgba(38,166,154,0.55)'; };
var chart = echarts.init(document.getElementById('main'));
chart.setOption(option);
window.addEventListener('resize', function(){ chart.resize(); });
"""


def build_table(boxes):
    rows = []
    for i, b in enumerate(boxes, 1):
        d = b.to_dict()
        if d["confirmed"]:
            if d["direction"] == "up":
                badge = '<span class="badge b-up">向上突破</span>'
            else:
                badge = '<span class="badge b-dn">向下突破</span>'
        else:
            badge = '<span class="badge b-open">尚未结束</span>'
        rows.append(
            f"<tr><td>{i}</td><td>{d['start_time']}</td><td>{d['end_time']}</td>"
            f"<td>{d['core_start']}</td><td>{d['core_end']}</td>"
            f"<td>{d['upper']:.3f}</td><td>{d['lower']:.3f}</td>"
            f"<td>{d['width_pct']:.2f}%</td><td>{d['n_peaks']}</td><td>{d['n_troughs']}</td>"
            f"<td>{d['cover_ratio']:.1%}</td><td>{d['median_spread_w']:.2f}</td>"
            f"<td>{d['bars_count']}</td><td>{badge}</td>"
            f"<td>{d['confirm_time'] or '--'}</td></tr>")
    head = ("<thead><tr><th>#</th><th>开始(回填)</th><th>结束(回填)</th><th>核心起点</th>"
            "<th>核心终点</th><th>上沿</th><th>下沿</th><th>宽度%</th><th>峰</th><th>谷</th>"
            "<th>覆盖</th><th>重心差/W</th><th>K线</th><th>状态</th><th>确认时间</th></tr></thead>")
    return f"<table>{head}<tbody>{''.join(rows)}</tbody></table>"


def render_html(path, label, freq, sdt, edt, bars, prewarm, finder, boxes, fxs):
    title = f"{label} · {freq} · 盘整箱体事后识别（RangeBoxFinder）"
    subtitle = (f"判断区间 {_parse_dt(sdt):%Y-%m-%d} ~ {_parse_dt(edt):%Y-%m-%d}　|　"
                f"最新K线 {bars[-1].dt:%Y-%m-%d %H:%M}　|　算法：未来K线确认峰谷 → 中位箱体 → "
                f"回填起止 + 突破确认")
    html = HTML_TEMPLATE.format(
        title=title, subtitle=subtitle,
        echarts_src=os.path.relpath(os.path.join(CHAN_PATH, "assets", "echarts.min.js"),
                                    os.path.dirname(os.path.abspath(path))).replace("\\", "/"),
        n_bars=len(bars), n_prewarm=prewarm,
        n_turns=len(finder.turns), n_boxes=len(boxes),
        n_confirmed=sum(1 for b in boxes if b.confirmed),
        table_html=build_table(boxes),
        confirm_n=finder.breakout_confirm,
        chart_js=build_chart_js(label, freq, bars, finder, boxes, fxs))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(s[0] for s in DEFAULT_SYMBOLS))
    ap.add_argument("--freq", default=None)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--no-chan", action="store_true", help="不调用 ChanAnalyzer 分型参照")
    args = ap.parse_args()

    syms = []
    for s in args.symbols.split(","):
        s = s.strip()
        if not s:
            continue
        match = [x for x in DEFAULT_SYMBOLS if x[0] == s]
        if match:
            syms.append(match[0])
        else:
            syms.append((s, args.freq or "日线", args.start or "20250101", args.end or "20260904"))

    all_boxes = 0
    for symbol, freq, sdt, edt in syms:
        try:
            label, bars, prewarm, finder, boxes, fxs = analyze_one(
                symbol, freq, sdt, edt, with_chan=not args.no_chan)
        except Exception as e:
            print(f"[失败] {symbol} {freq}: {e}")
            continue
        print_text(label, freq, bars, prewarm, finder, boxes)
        safe = label.replace(".", "_")
        path = os.path.join(HERE, f"report_{safe}_{freq}.html")
        render_html(path, label, freq, sdt, edt, bars, prewarm, finder, boxes, fxs)
        all_boxes += len(boxes)
        print(f"已生成报告: {path}\n")

    print(f"共 {len(syms)} 个标的，识别 {all_boxes} 个箱体。删除整个 box_range_test 目录即可清理本测试。")


if __name__ == "__main__":
    main()
