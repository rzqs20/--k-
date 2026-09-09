# -*- coding: utf-8 -*-
"""
筹码结构类 · 交互式报告（类封装版）—— K线时间轴 + 右侧筹码峰联动
（当前数据口径：不复权原始价）

类用法（Python 内）：
    from chip_report import ChipReport
    ChipReport("000001", "SZ", show_n=500).generate()          # 最近 500 日并打开
    ChipReport("600519", window=250, decay=0.98, n_bins=200).generate()
    ChipReport("000001", start="2024-01-01", end="2026-09-02",
               open_browser=False).generate()                  # 只生成不打开

命令行用法（PowerShell / 任意终端）：
    python chip_report.py 000001 SZ            # 最近 500 个交易日
    python chip_report.py 000001.SZ
    python chip_report.py 000001 SZ 800        # 最近 800 个交易日
    python chip_report.py 000001 SZ 500 2024-01-01 2026-09-02   # 指定区间

终端交互式（推荐）：python cli_chip.py

交互：
  - 底部时间轴滑块（dataZoom）：拉动/缩放 x 轴 → 显示可视区间【最后一天】的筹码峰
  - 鼠标悬停主图任意 K 线 → 实时显示【该日】筹码峰（跟随）
  - 主图（左）：K线 + 平均成本线；红色横线=当日收盘、灰色横线=平均成本、
    黄色虚线=筹码峰位、蓝色竖线=当前筹码对应日期
  - 中图：获利盘比例曲线（0~100%，50% 参考线）
  - 筹码图（右）：与 K 线 y 轴对齐；横轴筹码量，纵轴价格（上高下低）；
    红色=获利盘、绿色=套牢盘

输出：reports/<code>_<EX>_筹码结构_<date>.html（默认自动用浏览器打开）
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import webbrowser
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chip_distribution import ChipDistribution, load_front_daily

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
ECHARTS_SRC = r"D:\量化k线\缠论分型笔\assets\echarts.min.js"

# 算法默认参数（与核心模块一致）
WINDOW = 250
DECAY = 0.98
N_BINS = 200

# 深色金融配色
BG = "#0d1117"
PANEL = "#161b22"
GRID_LINE = "#1f2937"
TEXT = "#c9d1d9"
UP = "#ef4444"       # 红涨
DOWN = "#22c55e"     # 绿跌
PROFIT = "#f87171"   # 获利筹码（红）
TRAPPED = "#34d399"  # 套牢筹码（绿）
COST = "#a3a3a3"     # 平均成本线
PIVOT = "#facc15"    # 筹码峰位线
CURSOR = "#58a6ff"   # 当前日期竖线


# ---------------------------------------------------------------------------
# 报告类：ChipReport —— 加载数据 → 算筹码 → 渲染 HTML → 打开浏览器
# ---------------------------------------------------------------------------

def _infer_exchange(code: str) -> str:
    """按代码首位推断市场：6→SH，0/3→SZ，4/8→BJ，其余默认 SZ。"""
    c = str(code)[0]
    if c == "6":
        return "SH"
    if c in ("0", "3"):
        return "SZ"
    if c in ("4", "8"):
        return "BJ"
    return "SZ"


class ChipReport:
    """
    筹码结构交互式报告生成器（K线时间轴 + 右侧筹码峰联动）。

    用法
    ----
    report = ChipReport("000001", "SZ", show_n=500)   # 最近 500 个交易日
    report = ChipReport("600519")                      # 市场自动推断
    report = ChipReport("000001", window=250, decay=0.98, n_bins=200)  # 自定义算法参数
    out = report.generate()                            # 生成并打开浏览器，返回 HTML 路径

    交互：拖动底部时间轴缩放 → 筹码峰切换为可视区最后一天；
          悬停主图 K 线 → 筹码峰实时跟随该日。
    """

    def __init__(self, code: str, exchange: str = None, show_n: int = 500,
                 start: str = None, end: str = None,
                 window: int = WINDOW, decay: float = DECAY, n_bins: int = N_BINS,
                 open_browser: bool = True, out_dir: str = None):
        self.code = str(code).zfill(6)
        self.exchange = (exchange or _infer_exchange(self.code)).upper()
        self.show_n = int(show_n)
        self.start = start
        self.end = end
        self.window = int(window)
        self.decay = float(decay)
        self.n_bins = int(n_bins)
        self.open_browser = bool(open_browser)
        self.out_dir = out_dir or REPORTS_DIR
        self._data: dict = None

    # -- 数据准备 -----------------------------------------------------------
    def prepare(self) -> dict:
        """加载数据 → 全历史算筹码 → 截取展示窗口 → 组装前端 JSON 结构。"""
        rows = load_front_daily(self.code, self.exchange, self.start, self.end)
        if len(rows) < self.window + 30:
            print(f"警告: {self.code}.{self.exchange} 仅 {len(rows)} 根日线，"
                  f"少于窗口 {self.window}+30，结果可能不稳定")
        print(f"加载 {self.code}.{self.exchange} 日线 {len(rows)} 根"
              f"（{rows[0]['dt']} ~ {rows[-1]['dt']}）")

        cd = ChipDistribution(window=self.window, decay=self.decay, n_bins=self.n_bins)
        snaps = cd.compute(rows)
        bins = cd.bins.tolist()

        show_n = min(self.show_n, len(snaps))
        snaps = snaps[-show_n:]
        rows = rows[-show_n:]

        dates = [s.dt.strftime("%Y-%m-%d") for s in snaps]
        kline = [[round(r["open"], 3), round(r["close"], 3),
                  round(r["low"], 3), round(r["high"], 3)] for r in rows]

        dists = []
        for s in snaps:
            arr = (s.dist / s.total * 100.0).round(3).tolist() if s.total > 0 else [0.0] * len(bins)
            dists.append(arr)

        profit = [round(s.profit_ratio * 100.0, 2) for s in snaps]
        cost = [round(s.avg_cost, 3) for s in snaps]
        conc90 = [round(s.conc90, 4) for s in snaps]
        close_vals = [round(s.close, 3) for s in snaps]
        peaks_all = []
        for s in snaps:
            peaks_all.append([{"p": round(p["price"], 3),
                               "s": round(p["share"] * 100.0, 2)} for p in s.peaks])

        self._data = {
            "meta": {"code": self.code, "exchange": self.exchange, "show_n": show_n,
                     "window": self.window, "decay": self.decay, "bins": self.n_bins},
            "dates": dates, "kline": kline, "bins": bins,
            "dists": dists, "profit": profit, "cost": cost,
            "conc90": conc90, "close": close_vals, "peaks": peaks_all,
        }
        return self._data

    # -- 渲染 -----------------------------------------------------------------
    def render(self) -> str:
        """渲染 HTML 文件，返回路径。"""
        data = self._data or self.prepare()
        return _render_html(data, out_dir=self.out_dir)

    # -- 一步到位 -------------------------------------------------------------
    def generate(self) -> str:
        """prepare + render + （可选）打开浏览器，返回 HTML 路径。"""
        self.prepare()
        out = self.render()
        if self.open_browser:
            try:
                webbrowser.open("file:///" + out.replace("\\", "/"))
            except Exception:
                pass
        return out


# ---------------------------------------------------------------------------
# HTML 生成（单 ECharts 实例，三 grid：K线+成本 / 获利盘 / 筹码峰）
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>筹码结构 · {code}.{exchange}（不复权 · 滚动{WINDOW}日）</title>
<script src="assets/echarts.min.js"></script>
<style>
  html,body{{margin:0;padding:0;background:{BG};color:{TEXT};
        font-family:'Microsoft YaHei',sans-serif;height:100%;overflow:hidden}}
  #header{{padding:10px 18px 4px;font-size:15px;font-weight:600;color:#e6edf3}}
  #header span{{color:{TEXT};font-weight:400;font-size:12px;margin-left:10px}}
  #info{{padding:2px 18px 8px;font-size:12px;color:#8b949e;line-height:1.7}}
  #info b{{color:#e6edf3}}
  #chart{{width:100%;height:calc(100% - 92px)}}
</style>
</head>
<body>
<div id="header">筹码结构 · {code}.{exchange}
  <span>不复权 · 三角形分布 + 滚动{WINDOW}日衰减({DECAY}) · 拖动底部时间轴 / 悬停K线查看筹码峰</span>
</div>
<div id="info">截至 <b id="curDate">-</b> 收盘 <b id="curClose">-</b>
  ｜ 获利盘 <b id="curProfit" style="color:{PROFIT}">-</b> 套牢盘 <b id="curTrapped" style="color:{TRAPPED}">-</b>
  ｜ 平均成本 <b id="curCost">-</b> ｜ 90%集中度 <b id="curConc">-</b>
  ｜ 筹码峰 <b id="curPeaks">-</b></div>
<div id="chart"></div>
<script>
const DATA = __DATA__;
const bins = DATA.bins, dates = DATA.dates, n = dates.length;

function fmt(v, d) {{ return (v==null||isNaN(v)) ? '-' : Number(v).toFixed(d==null?2:d); }}

// ---------- 信息栏 ----------
function updateInfo(i) {{
  const profit = DATA.profit[i], peaks = DATA.peaks[i];
  document.getElementById('curDate').textContent = dates[i];
  document.getElementById('curClose').textContent = fmt(DATA.close[i], 3);
  document.getElementById('curProfit').textContent = fmt(profit) + '%';
  document.getElementById('curTrapped').textContent = fmt(100 - profit) + '%';
  document.getElementById('curCost').textContent = fmt(DATA.cost[i], 3);
  document.getElementById('curConc').textContent = fmt(DATA.conc90[i]);
  document.getElementById('curPeaks').textContent = peaks.length
      ? peaks.map(p => p.p + '(' + p.s + '%)').join('  ') : '无显著峰';
}}

// ---------- 核心更新：切换查看日期 → 更新筹码图 + 主图价位线 ----------
function updateChip(i) {{
  const s = DATA.dists[i], c = DATA.close[i];
  // 可视区间（dataZoom）
  const dz = chart.getOption().dataZoom[0];
  const i0 = Math.max(0, Math.round(dz.start / 100 * (n - 1)));
  const i1 = Math.min(n - 1, Math.round(dz.end / 100 * (n - 1)));
  // K线价格范围 → 主图与筹码图共享 y 轴刻度
  let lo = Infinity, hi = -Infinity;
  for (let k = i0; k <= i1; k++) {{
    const kl = DATA.kline[k];
    if (kl[2] < lo) lo = kl[2];
    if (kl[3] > hi) hi = kl[3];
  }}
  const pad = ((hi - lo) * 0.03) || 0.5;
  lo -= pad; hi += pad;
  // 筹码数据：只保留 y 轴范围内的价格档（横向柱：[筹码量, 价格, 上档价, 下档价, 颜色]）
  const pts = [];
  for (let k = 0; k < bins.length; k++) {{
    if (bins[k] < lo || bins[k] > hi) continue;
    const up = (k + 1 < bins.length) ? bins[k + 1] : bins[k];
    const dn = (k - 1 >= 0) ? bins[k - 1] : bins[k];
    pts.push([s[k], bins[k], up, dn, bins[k] <= c ? '{PROFIT}' : '{TRAPPED}']);
  }}
  const costLine = DATA.cost[i];
  // 主图 markLine：竖线=当前日期；横线=收盘/均本/峰位
  const hLines = [
    {{ yAxis: c, lineStyle:{{color:'{PROFIT}',width:1}}, label:{{formatter:'收盘 '+fmt(c,3), position:'insideEndTop', color:'{PROFIT}', fontSize:10}} }},
    {{ yAxis: costLine, lineStyle:{{color:'{COST}',width:1}}, label:{{formatter:'均本 '+fmt(costLine,3), position:'insideEndBottom', color:'{COST}', fontSize:10}} }}
  ];
  (DATA.peaks[i] || []).forEach(p => {{
    hLines.push({{ yAxis: p.p, lineStyle:{{color:'{PIVOT}',type:'dashed',width:1}},
                  label:{{formatter:p.p+' 峰', position:'insideStartTop', color:'{PIVOT}', fontSize:10}} }});
  }});
  chart.setOption({{
    yAxis: [{{ min:lo, max:hi }}, {{}}, {{ min:lo, max:hi }}],
    series: [
      {{ id:'k', markLine: {{ silent:true, symbol:'none',
         data: [{{ xAxis: dates[i], lineStyle:{{color:'{CURSOR}',width:1,type:'dotted'}},
                  label:{{formatter:dates[i], position:'insideEndTop', color:'{CURSOR}', fontSize:10}} }}].concat(hLines) }} }},
      {{ id:'chip', data: pts }}
    ]
  }}, {{ notMerge:false }});
  updateInfo(i);
}}

// ---------- 初始化单实例 ----------
const chartDom = document.getElementById('chart');
const chart = echarts.init(chartDom, null, {{renderer:'canvas'}});

const opt = {{
  backgroundColor:'{BG}',
  animation:false,
  axisPointer:{{ link:[{{xAxisIndex:[0,1]}}] }},
  tooltip:{{ trigger:'axis', axisPointer:{{type:'cross'}}, backgroundColor:'rgba(13,17,23,0.92)',
            borderColor:'#30363d', textStyle:{{color:'{TEXT}',fontSize:11}} }},
  legend:{{ data:['K线','平均成本','获利盘比例'], textStyle:{{color:'{TEXT}',fontSize:11}}, top:0, left:10 }},
  grid:[
    {{ left:60, right:'20%', top:24, height:'46%' }},          // K线（左，主）
    {{ left:60, right:'20%', top:'58%', height:'15%' }},       // 获利盘（左下）
    {{ left:'80%', right:14, top:24, height:'46%' }}           // 筹码峰（右侧，与K线同高同顶）
  ],
  xAxis:[
    {{ type:'category', data:dates, gridIndex:0, axisLine:{{lineStyle:{{color:'#30363d'}}}}, axisLabel:{{color:'#8b949e',fontSize:10}}, splitLine:{{show:false}} }},
    {{ type:'category', data:dates, gridIndex:1, axisLine:{{lineStyle:{{color:'#30363d'}}}}, axisLabel:{{show:false}}, splitLine:{{show:false}} }},
    {{ type:'value', gridIndex:2, min:0, axisLabel:{{show:false}}, axisLine:{{show:false}}, axisTick:{{show:false}}, splitLine:{{show:false}} }}
  ],
  yAxis:[
    {{ scale:true, gridIndex:0, splitLine:{{lineStyle:{{color:'{GRID_LINE}'}}}}, axisLabel:{{color:'#8b949e',fontSize:10}} }},
    {{ min:0, max:100, gridIndex:1, splitLine:{{lineStyle:{{color:'{GRID_LINE}'}}}}, axisLabel:{{color:'#8b949e',fontSize:10, formatter:'{{value}}%'}} }},
    {{ type:'value', gridIndex:2, min:0, max:100,
       axisLabel:{{show:false}}, axisLine:{{show:false}}, axisTick:{{show:false}}, splitLine:{{show:false}} }}
  ],
  dataZoom:[
    {{ type:'inside', xAxisIndex:[0,1], start:Math.max(0, 100 - 50000/n), end:100 }},
    {{ type:'slider', xAxisIndex:[0,1], bottom:6, height:18, start:Math.max(0, 100 - 50000/n), end:100,
       borderColor:'#30363d', backgroundColor:'{PANEL}', fillerColor:'rgba(88,166,255,0.12)',
       handleStyle:{{color:'#58a6ff'}}, textStyle:{{color:'#8b949e',fontSize:10}},
       dataBackground:{{lineStyle:{{color:'#30363d'}}, areaStyle:{{color:'#21262d'}}}} }}
  ],
  series:[
    {{ id:'k', name:'K线', type:'candlestick', xAxisIndex:0, yAxisIndex:0, data:DATA.kline,
       itemStyle:{{ color:'{UP}', color0:'{DOWN}', borderColor:'{UP}', borderColor0:'{DOWN}' }},
       markLine:{{ silent:true, symbol:'none', data:[] }} }},
    {{ id:'cost', name:'平均成本', type:'line', xAxisIndex:0, yAxisIndex:0, data:DATA.cost, symbol:'none',
       lineStyle:{{color:'{COST}', width:1}}, z:2 }},
    {{ id:'profit', name:'获利盘比例', type:'line', xAxisIndex:1, yAxisIndex:1, data:DATA.profit, symbol:'none',
       lineStyle:{{color:'#58a6ff', width:1}},
       markLine:{{ silent:true, symbol:'none',
         data:[{{yAxis:50, lineStyle:{{color:'#8b949e', type:'dashed'}},
                 label:{{formatter:'50%', position:'insideEndTop', color:'#8b949e', fontSize:10}}}}] }} }},
    {{ id:'chip', name:'筹码分布', type:'custom', xAxisIndex:2, yAxisIndex:2, data:[],
       renderItem: function (params, api) {{
         const val = api.value(0), price = api.value(1);
         const p0 = api.coord([0, price]);            // 左端（贴K线侧，0在左）
         const p1 = api.coord([val, price]);          // 右端（筹码量）
         const yUp = api.coord([0, api.value(2)]);    // 上档价（更高价）
         const yDn = api.coord([0, api.value(3)]);    // 下档价（更低价）
         const h = Math.max(0.6, (yUp[1] - yDn[1]) / 2);
         return {{
           type: 'rect',
           shape: {{ x: p0[0], y: p0[1] - h / 2, width: Math.max(0, p1[0] - p0[0]), height: h }},
           style: {{ fill: api.value(4) }}
         }};
       }} }}
  ]
}};
chart.setOption(opt);

// ---------- 交互1：拖动时间轴 → 可视区最后一天 ----------
chart.on('datazoom', function () {{
  const dz = chart.getOption().dataZoom[0];
  const idx = Math.min(n - 1, Math.max(0, Math.round(dz.end / 100 * (n - 1))));
  updateChip(idx);
}});

// ---------- 交互2：悬停K线 → 跟随该日 ----------
chart.on('updateAxisPointer', function (params) {{
  try {{
    if (params.axesInfo && params.axesInfo[0]) {{
      const i = dates.indexOf(params.axesInfo[0].value);
      if (i >= 0) updateChip(i);
    }}
  }} catch (e) {{}}
}});

// 初始：最后一根K线
updateChip(n - 1);
window.addEventListener('resize', function () {{ chart.resize(); }});
</script>
</body>
</html>
"""


def _render_html(data: dict, out_dir: str = None) -> str:
    """渲染 HTML 文件，返回路径。out_dir 缺省为 reports/。"""
    os.makedirs(ASSETS_DIR, exist_ok=True)
    out_dir = out_dir or REPORTS_DIR
    os.makedirs(out_dir, exist_ok=True)
    if os.path.exists(ECHARTS_SRC):
        shutil.copy2(ECHARTS_SRC, os.path.join(ASSETS_DIR, "echarts.min.js"))
        os.makedirs(os.path.join(out_dir, "assets"), exist_ok=True)
        shutil.copy2(ECHARTS_SRC, os.path.join(out_dir, "assets", "echarts.min.js"))
    else:
        print("警告: 未找到 echarts.min.js，图表无法渲染")

    json_str = json.dumps(data, ensure_ascii=False)
    html = HTML_TEMPLATE.format(
        code=data["meta"]["code"], exchange=data["meta"]["exchange"],
        WINDOW=data["meta"]["window"], DECAY=data["meta"]["decay"],
        BG=BG, PANEL=PANEL, GRID_LINE=GRID_LINE, TEXT=TEXT,
        UP=UP, DOWN=DOWN, PROFIT=PROFIT, TRAPPED=TRAPPED, COST=COST, PIVOT=PIVOT, CURSOR=CURSOR,
    ).replace("__DATA__", json_str)

    today = datetime.now().strftime("%Y%m%d")
    out = os.path.join(out_dir, f"{data['meta']['code']}_{data['meta']['exchange']}_筹码结构_{today}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"报告已生成: {out}  ({os.path.getsize(out)/1024:.0f} KB)")
    return out


def render(data: dict) -> str:
    """渲染 HTML（兼容旧调用，等价 ChipReport(...).render()）。"""
    return _render_html(data)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return
    arg0 = argv[0].upper()
    if "." in arg0:
        code, exchange = arg0.split(".")
    else:
        code = arg0
        exchange = argv[1].upper() if len(argv) > 1 else None
    show_n = int(argv[2]) if len(argv) > 2 else 500
    sdt = argv[3] if len(argv) > 3 else None
    edt = argv[4] if len(argv) > 4 else None

    ChipReport(code, exchange, show_n=show_n, start=sdt, end=edt).generate()


if __name__ == "__main__":
    main()
