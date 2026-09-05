# -*- coding: utf-8 -*-
"""
缠论分析器（ChanAnalyzer）
整合：分型/笔/线段（CZSC）+ 线段大趋势 + 箱体识别 + 终端/HTML报告

用法：
    from chan_analyzer import ChanAnalyzer
    ana = ChanAnalyzer(bars, symbol="000300.SH", freq="30分钟")
    boxes = ana.find_boxes(slope_quantile=0.5)   # 不同股票可调不同参数
    trends = ana.analyze_segments_trend(trend_pct=5.0)
    ana.print_terminal()
    ana.render_html("report.html")

注意：
- 缠论核心（K线合并/分型/笔/线段）由 CZSC 类完成，内部自动去包含
- 分型为笔端点分型（从 bi_list 提取 fx_a/fx_b 去重），与 chan_only.py 完全一致
- 箱体识别基于同类型分型斜率+绝对涨跌幅双条件
"""
import os
import sys
import json
import bisect

# 确保能 import 到父目录的 chan_report
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from chan_report import cb
from .box_finder import BoxFinder


# =====================================================================
# HTML 模板
# =====================================================================
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>缠论 · 分型/笔/线段 · __SYMBOL__</title>
<script src="__ECHARTS__"></script>
<style>
body{margin:0;background:#f4f5f7;font-family:'PingFang SC','Microsoft YaHei',sans-serif;color:#222}
.wrap{max-width:1200px;margin:0 auto;padding:16px}
.header{background:#fff;border-radius:10px;padding:16px 20px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.header h1{margin:0 0 8px;font-size:20px}
.header .meta{font-size:13px;color:#555;line-height:1.8}
.header .meta b{color:#e0503e}
.report{background:#fff;border-radius:10px;padding:16px 20px;margin-top:12px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.report h2{font-size:15px;margin:18px 0 6px;color:#333;border-left:3px solid #2f6fed;padding-left:8px}
table.bi{width:100%;border-collapse:collapse;margin-top:4px}
table.bi th,table.bi td{border:1px solid #eee;padding:6px 10px;text-align:left;font-size:13px}
table.bi th{background:#fafbfc;color:#666;font-weight:normal}
table.bi tr.up td.dir{color:#e0503e;font-weight:bold}
table.bi tr.down td.dir{color:#1a9a5a;font-weight:bold}
table.bi tr.boxrow td{color:#a07010;}
.upseg td.dir{color:#2f6fed;font-weight:bold}
table.bi tr.dnseg td.dir{color:#7b1fa2;font-weight:bold}
.footer{color:#999;font-size:12px;text-align:center;margin:16px 0 30px}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>缠论 · 分型/笔/线段 · __SYMBOL__</h1>
    <div class="meta">
      周期：__FREQ__ ｜ 判断区间：__SDT__ ~ __EDT__ ｜ 数据：__BARS__ 根原始K线（含 __PREWARM__ 根历史预热）<br>
      最新K线：__CLOSEDT__ ｜ 分型：__FXS__ 个（顶 __GFX__ / 底 __DFX__）｜ 笔：__BIS__ 笔（向上 __UPBIS__ / 向下 __DNBIS__）<br>
      线段：__SEGS__ 段已确认（向上 __UPSEGS__ / 向下 __DNSEGS__）__UNFINSEGS__
    </div>
  </div>
  <div id="chart" style="width:100%;height:__CHART_H__px;"></div>
  <div class="report">
    <h2>单根线段大趋势分析</h2>
    <table class="bi">
      <tr><th>#</th><th>分类</th><th>起始时间</th><th>结束时间</th><th>起始价</th><th>结束价</th><th>涨跌幅</th><th>持续K线</th><th>斜率%/根</th><th>判断依据</th></tr>
      __TREND_ROWS__
    </table>
    <h2>箱体识别（基于笔斜率，自适应周期，共 __BOXCNT__ 个）</h2>
    <table class="bi">
      <tr><th>#</th><th>起始时间</th><th>结束时间</th><th>GG最高</th><th>DD最低</th><th>ZG重叠上</th><th>ZD重叠下</th><th>箱体高度</th><th>笔数</th><th>K线数</th><th>判断依据</th></tr>
      __BOX_ROWS__
    </table>
    <h2>线段清单</h2>
    <table class="bi">
      <tr><th>#</th><th>方向</th><th>起点分型</th><th>终点分型</th><th>起始时间</th><th>结束时间</th><th>区间 [低, 高]</th><th>笔数</th><th>价差</th><th>状态</th></tr>
      __SEG_ROWS__
    </table>
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
  <div class="footer">本报告由 ChanAnalyzer 自动生成（纯缠论：分型/笔/线段，不含布林/RSI/中枢/买卖点）｜ 技术分析仅供参考，不构成投资建议</div>
</div>
<script>
var DATA=__DATA__;
var chart=echarts.init(document.getElementById('chart'));
var option={
  backgroundColor:'#fff',
  animation:false,
  tooltip:{trigger:'axis',axisPointer:{type:'cross'},confine:true},
  legend:{top:4,textStyle:{fontSize:11}},
  axisPointer:{link:[{xAxisIndex:'all'}]},
  grid:[
    {left:55,right:20,top:34,height:'62%'},
    {left:55,right:20,top:'74%',height:'18%'}
  ],
  xAxis:[
    {type:'category',data:DATA.catLabels,scale:true,boundaryGap:false,axisLine:{onZero:false},splitLine:{show:false},min:'dataMin',max:'dataMax',axisLabel:{fontSize:10,interval:DATA.labelInterval}},
    {type:'category',gridIndex:1,data:DATA.catLabels,scale:true,boundaryGap:false,axisLine:{onZero:false},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false}}
  ],
  yAxis:[
    {scale:true,splitArea:{show:false},splitLine:{lineStyle:{color:'#eee'}},axisLabel:{fontSize:10}},
    {scale:true,gridIndex:1,splitNumber:2,axisLabel:{show:false},axisLine:{show:false},axisTick:{show:false},splitLine:{show:false}}
  ],
  dataZoom:[
    {type:'inside',xAxisIndex:[0,1],start:DATA.zoomStart,end:100},
    {type:'slider',xAxisIndex:[0,1],bottom:4,start:DATA.zoomStart,end:100,height:16}
  ],
  series:[
    {name:'K线',type:'candlestick',xAxisIndex:0,yAxisIndex:0,data:DATA.kline,itemStyle:{color:'#e0503e',color0:'#1a9a5a',borderColor:'#e0503e',borderColor0:'#1a9a5a'},markArea:{silent:true,data:DATA.trendAreas,label:{show:true,position:'insideTop',fontSize:10,color:'#fff',formatter:function(p){return p.name;}}}},
    {name:'笔',type:'line',xAxisIndex:0,yAxisIndex:0,data:DATA.biLine,symbol:'none',lineStyle:{width:1.2,color:'#999'},z:5},
    {name:'线段',type:'line',xAxisIndex:0,yAxisIndex:0,data:DATA.segLine,symbol:'none',lineStyle:{width:2.6,color:'#2f6fed'},z:8},
    {name:'顶分型',type:'scatter',xAxisIndex:0,yAxisIndex:0,data:DATA.topFx,symbol:'triangle',symbolSize:12,itemStyle:{color:'#e0503e',borderColor:'#a02010',borderWidth:0.5},z:7},
    {name:'底分型',type:'scatter',xAxisIndex:0,yAxisIndex:0,data:DATA.bottomFx,symbol:'triangle',symbolRotate:180,symbolSize:12,itemStyle:{color:'#1a9a5a',borderColor:'#0a6a3a',borderWidth:0.5},z:7},
    {name:'箱体',type:'custom',xAxisIndex:0,yAxisIndex:0,data:DATA.boxRects,z:3,
      encode:{x:[0,1],y:[2,3]},clip:true,
      renderItem:function(params,api){
        var p0=api.coord([api.value(0),api.value(2)]);
        var p1=api.coord([api.value(1),api.value(3)]);
        return {type:'rect',shape:{x:p0[0],y:p1[1],width:Math.max(1,p1[0]-p0[0]),height:Math.max(1,p0[1]-p1[1])},
          style:{fill:'rgba(250,173,20,0.10)',stroke:'#e8a020',lineWidth:1.6}};
      }},
    {name:'重叠核心',type:'custom',xAxisIndex:0,yAxisIndex:0,data:DATA.boxCores,z:3,
      encode:{x:[0,1],y:[2,3]},clip:true,silent:true,
      renderItem:function(params,api){
        var p0=api.coord([api.value(0),api.value(2)]);
        var p1=api.coord([api.value(1),api.value(3)]);
        return {type:'rect',shape:{x:p0[0],y:p1[1],width:Math.max(1,p1[0]-p0[0]),height:Math.max(1,p0[1]-p1[1])},
          style:{fill:'rgba(232,160,32,0.30)',stroke:'transparent'}};
      }},
    {name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:DATA.vols}
  ]
};
chart.setOption(option);
window.addEventListener('resize',function(){chart.resize();});
</script>
</body>
</html>
"""


class ChanAnalyzer:
    """
    缠论分析器：整合分型/笔/线段 + 线段大趋势 + 箱体识别 + 报告输出。

     Parameters
    ----------
    bars : list[RawBar]
        原始K线（未去包含）。内部 CZSC 会自动做K线合并、分型、笔、线段。
    symbol : str
        标的代码，如 "000300.SH"
    freq : str
        周期，如 "30分钟" / "日线"
    max_bi_num : int
        CZSC 最大笔数
    min_bi_len : int
        最小笔长度（去包含K线根数）
    """

    def __init__(self, bars, symbol="", freq="", max_bi_num=None, min_bi_len=6):
        self.bars = bars
        self.symbol = symbol
        self.freq = freq
        if max_bi_num is None:
            max_bi_num = max(200, len(bars))
        # 缠论核心：内部自动做 K线合并 → 分型 → 笔 → 线段
        self.czsc = cb.CZSC(bars, max_bi_num=max_bi_num, min_bi_len=min_bi_len)
        # 笔端点分型（与 chan_only.py 完全一致的提取逻辑）
        self.fxs = self._extract_bi_fxs()
        # 箱体识别器（独立封装，改盘整算法只动 box_finder.py）
        self.box_finder = BoxFinder()

    # ------------------------------------------------------------------
    # 基础属性
    # ------------------------------------------------------------------
    @property
    def bi_list(self):
        return self.czsc.bi_list

    @property
    def segments(self):
        return self.czsc.segments

    @property
    def finished_segments(self):
        return [s for s in self.czsc.segments if s.finished]

    @property
    def last_bi_extend(self):
        return self.czsc.last_bi_extend

    def _extract_bi_fxs(self):
        """从 bi_list 提取笔端点分型，按 (dt, mark) 去重，保持时间顺序。"""
        seen = set()
        fxs = []
        for b in self.bi_list:
            for fx in (b.fx_a, b.fx_b):
                k = (fx.dt, fx.mark)
                if k not in seen:
                    seen.add(k)
                    fxs.append(fx)
        return fxs

    # ------------------------------------------------------------------
    # 线段大趋势分析
    # ------------------------------------------------------------------
    def analyze_segments_trend(self, trend_pct=3.0, trend_bars=20):
        """
        对每根已完成线段单独分析，根据涨幅和持续时间判断是否为大趋势线段。

        Parameters
        ----------
        trend_pct : float
            大趋势涨跌幅阈值（%）
        trend_bars : int
            大趋势持续K线阈值

        Returns
        -------
        list[dict]
            每根线段一个 dict，含 idx/direction/change_pct/bar_count/
            slope/is_trend/trend_dir/reason/start_time/end_time/start_price/end_price
        """
        results = []
        for i, seg in enumerate(self.finished_segments, 1):
            base = seg.fx_a.fx
            change_pct = (seg.fx_b.fx - base) / base * 100 if base != 0 else 0
            bar_count = sum(len(b.bars) for b in seg.bis)
            slope = change_pct / bar_count if bar_count > 0 else 0

            is_trend = False
            trend_dir = "none"
            if seg.direction == "Up" and change_pct >= trend_pct and bar_count >= trend_bars:
                is_trend = True
                trend_dir = "up"
            elif seg.direction == "Down" and change_pct <= -trend_pct and bar_count >= trend_bars:
                is_trend = True
                trend_dir = "down"

            if is_trend:
                if trend_dir == "up":
                    reason = f"大趋势上涨：涨幅{change_pct:.2f}%>={trend_pct}%，持续{bar_count}根>={trend_bars}根"
                else:
                    reason = f"大趋势下跌：跌幅{abs(change_pct):.2f}%>={trend_pct}%，持续{bar_count}根>={trend_bars}根"
            else:
                if seg.direction == "Up":
                    reason = f"普通反弹：涨幅{change_pct:.2f}%，持续{bar_count}根"
                else:
                    reason = f"普通回调：跌幅{abs(change_pct):.2f}%，持续{bar_count}根"

            results.append({
                "idx": i, "seg": seg, "direction": seg.direction,
                "change_pct": change_pct, "bar_count": bar_count, "slope": slope,
                "is_trend": is_trend, "trend_dir": trend_dir, "reason": reason,
                "start_time": seg.fx_a.dt, "end_time": seg.fx_b.dt,
                "start_price": seg.fx_a.fx, "end_price": seg.fx_b.fx,
            })
        return results

    # ------------------------------------------------------------------
    # 箱体识别
    # ------------------------------------------------------------------
    def find_boxes(self, slope_quantile=None, chg_quantile=None, min_fx=None,
                   min_h_pct=None, max_h_pct=None):
        """
        箱体识别（代理方法，实际逻辑在 BoxFinder 类中）。
        传参则临时覆盖 BoxFinder 的参数，不传则用 BoxFinder 默认参数。
        改盘整算法请编辑 core/box_finder.py。
        """
        bf = self.box_finder
        if slope_quantile is not None:
            bf.slope_quantile = slope_quantile
        if chg_quantile is not None:
            bf.chg_quantile = chg_quantile
        if min_fx is not None:
            bf.min_fx = min_fx
        if min_h_pct is not None:
            bf.min_h_pct = min_h_pct
        if max_h_pct is not None:
            bf.max_h_pct = max_h_pct
        return bf.find(self.fxs, self.bars)

    # ------------------------------------------------------------------
    # 终端文本报告
    # ------------------------------------------------------------------
    def print_terminal(self, sdt=None, edt=None, prewarm=0,
                       trend_pct=3.0, trend_bars=20,
                       box_params=None):
        """打印终端文本报告。"""
        bis_ = self.bi_list
        fxs = self.fxs
        segs = self.segments
        fsegs = self.finished_segments
        g_cnt = sum(1 for x in fxs if x.mark == "G")
        d_cnt = sum(1 for x in fxs if x.mark == "D")
        up_cnt = sum(1 for b in bis_ if b.direction == "Up")
        dn_cnt = sum(1 for b in bis_ if b.direction == "Down")
        useg_cnt = sum(1 for s in fsegs if s.direction == "Up")
        dseg_cnt = sum(1 for s in fsegs if s.direction == "Down")

        print("=" * 64)
        print("              缠论 · 分型/笔/线段 分析报告（纯缠论版）")
        print("=" * 64)
        print(f"标的：{self.symbol}")
        print(f"周期：{self.freq}   |   判断区间：{sdt.date() if sdt else '?'} ~ {edt.date() if edt else '?'}")
        print(f"K线：{len(self.bars)} 根（含 {prewarm} 根历史预热）   |   "
              f"最新K线时间：{self.bars[-1].dt:%Y-%m-%d %H:%M}")
        print("-" * 64)
        print("[结构统计]")
        print(f"  分型：{len(fxs)} 个（顶 {g_cnt} / 底 {d_cnt}，笔端点分型）")
        print(f"  笔：{len(bis_)} 笔（向上 {up_cnt} / 向下 {dn_cnt}）")
        print(f"  线段：{len(fsegs)} 段已确认（向上 {useg_cnt} / 向下 {dseg_cnt}）"
              + (f"，另有 {len(segs) - len(fsegs)} 段未完成" if len(segs) > len(fsegs) else ""))
        print(f"  最后一笔延伸中：{'是' if self.last_bi_extend else '否'}")

        trends = self.analyze_segments_trend(trend_pct, trend_bars)
        trend_up = sum(1 for t in trends if t["trend_dir"] == "up")
        trend_dn = sum(1 for t in trends if t["trend_dir"] == "down")
        print("-" * 64)
        print(f"[单根线段大趋势分析] 共 {len(trends)} 根已完成线段"
              f"（大趋势上涨 {trend_up} / 大趋势下跌 {trend_dn} / 普通波动 {len(trends)-trend_up-trend_dn}）")
        print(f"  阈值：涨幅>={trend_pct}% 且 持续>={trend_bars}根K线 → 大趋势线段")
        for t in trends:
            if t["is_trend"]:
                mark = "★大趋势上涨" if t["trend_dir"] == "up" else "★大趋势下跌"
            else:
                mark = "  普通波动  "
            print(f"  {t['idx']:>2}. {mark}  {t['start_time']:%Y-%m-%d %H:%M} -> {t['end_time']:%Y-%m-%d %H:%M}"
                  f"  {t['change_pct']:+.2f}%  {t['bar_count']}根  斜率{t['slope']:+.3f}%/根  | {t['reason']}")

        bp = box_params or {}
        boxes = self.find_boxes(**bp)
        print("-" * 64)
        print(f"[箱体识别] 共 {len(boxes)} 个箱体（基于笔斜率，自适应周期）")
        print("  条件：连续>=4分型双条件(顶-顶/底-底斜率+绝对涨跌幅均<=前60%分位)，整体高度>=0.5%（不设上限）（自适应周期）")
        for i, bx in enumerate(boxes, 1):
            print(f"  {i:>2}. 箱体  {bx['start']:%Y-%m-%d %H:%M} -> {bx['end']:%Y-%m-%d %H:%M}"
                  f"  箱体[{bx['dd']:.1f},{bx['gg']:.1f}] 重叠[{bx['zd']:.1f},{bx['zg']:.1f}]"
                  f"  {bx['n_bis']}笔/{bx['bars']}根 全高{bx['full_h_pct']:.2f}%")

        print("-" * 64)
        print("[线段清单]（共 %d 段，已完成 %d 段）" % (len(segs), len(fsegs)))
        for i, seg in enumerate(segs, 1):
            cn = "向上线段" if seg.direction == "Up" else "向下线段"
            status = "完成" if seg.finished else "未完成"
            lo = min(seg.fx_a.fx, seg.fx_b.fx)
            hi = max(seg.fx_a.fx, seg.fx_b.fx)
            diff = abs(seg.fx_b.fx - seg.fx_a.fx)
            print(f"  {i:>2}. {cn}  {seg.fx_a.dt:%Y-%m-%d %H:%M} -> {seg.fx_b.dt:%Y-%m-%d %H:%M}"
                  f"  区间[{lo:.3f}, {hi:.3f}]  笔数{len(seg.bis)}  价差{diff:.3f}  [{status}]")

        print("-" * 64)
        print("[笔清单]（共 %d 笔）" % len(bis_))
        for i, b in enumerate(bis_, 1):
            cn = "向上" if b.direction == "Up" else "向下"
            lo = min(b.fx_a.fx, b.fx_b.fx)
            hi = max(b.fx_a.fx, b.fx_b.fx)
            diff = abs(b.fx_b.fx - b.fx_a.fx)
            print(f"  {i:>2}. {cn}  {b.fx_a.dt:%Y-%m-%d %H:%M} -> {b.fx_b.dt:%Y-%m-%d %H:%M}"
                  f"  区间[{lo:.3f}, {hi:.3f}]  长度{len(b.bars)}根  价差{diff:.3f}")

    # ------------------------------------------------------------------
    # HTML 图表报告
    # ------------------------------------------------------------------
    def render_html(self, out_path=None, sdt=None, edt=None, prewarm=0,
                    trend_pct=3.0, trend_bars=20, box_params=None):
        """生成 HTML 图表报告，返回输出路径。"""
        bars = self.bars
        n = len(bars)
        dts = [b.dt for b in bars]
        opens = [b.open for b in bars]
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        vols = [b.vol for b in bars]

        def _to_idx(dt, mode="right"):
            if mode == "left":
                return bisect.bisect_left(dts, dt)
            return bisect.bisect_right(dts, dt) - 1

        def _fmt_dt(dt):
            if self.freq in ("日线", "周线", "月线"):
                return dt.strftime("%Y-%m-%d")
            return dt.strftime("%m-%d %H:%M")

        cat_labels = [_fmt_dt(b.dt) for b in bars]
        label_interval = max(1, n // 14)
        kline = [[opens[i], closes[i], lows[i], highs[i]] for i in range(n)]
        vol_data = [{"value": vols[i],
                     "itemStyle": {"color": "#e0503e" if closes[i] >= opens[i] else "#1a9a5a"}}
                    for i in range(n)]

        bis_ = self.bi_list
        bi_line = []
        for b in bis_:
            bi_line.append([_to_idx(b.fx_a.dt), round(b.fx_a.fx, 3)])
            bi_line.append([_to_idx(b.fx_b.dt), round(b.fx_b.fx, 3)])

        segs = self.segments
        fsegs = self.finished_segments
        seg_line = []
        for s in segs:
            if seg_line:
                seg_line.append(None)
            seg_line.append([_to_idx(s.fx_a.dt), round(s.fx_a.fx, 3)])
            seg_line.append([_to_idx(s.fx_b.dt), round(s.fx_b.fx, 3)])

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

        trends = self.analyze_segments_trend(trend_pct, trend_bars)
        trend_areas = []
        trend_rows = []
        for t in trends:
            si = _to_idx(t["start_time"])
            ei = _to_idx(t["end_time"])
            if t["trend_dir"] == "up":
                color = "rgba(224,80,62,0.10)"
                border = "#e0503e"
                cn = "★大趋势上涨"
                cls = "upseg"
            elif t["trend_dir"] == "down":
                color = "rgba(26,154,90,0.10)"
                border = "#1a9a5a"
                cn = "★大趋势下跌"
                cls = "dnseg"
            else:
                color = None
                cn = "普通波动"
                cls = ""
            if color is not None:
                trend_areas.append([
                    {"xAxis": si, "itemStyle": {"color": color, "borderColor": border, "borderWidth": 1}},
                    {"xAxis": ei, "name": cn},
                ])
            trend_rows.append(
                f"<tr class='{cls}'><td>{t['idx']}</td><td class='dir'>{cn}</td>"
                f"<td>{t['start_time']:%Y-%m-%d %H:%M}</td><td>{t['end_time']:%Y-%m-%d %H:%M}</td>"
                f"<td>{t['start_price']:.3f}</td><td>{t['end_price']:.3f}</td>"
                f"<td>{t['change_pct']:+.2f}%</td><td>{t['bar_count']}</td>"
                f"<td>{t['slope']:+.3f}</td><td>{t['reason']}</td></tr>")

        seg_rows = []
        for i, seg in enumerate(segs, 1):
            cn = "向上线段" if seg.direction == "Up" else "向下线段"
            cls = "upseg" if seg.direction == "Up" else "dnseg"
            status = "完成" if seg.finished else "未完成"
            lo = min(seg.fx_a.fx, seg.fx_b.fx)
            hi = max(seg.fx_a.fx, seg.fx_b.fx)
            diff = abs(seg.fx_b.fx - seg.fx_a.fx)
            seg_rows.append(
                f"<tr class='{cls}'><td>{i}</td><td class='dir'>{cn}</td>"
                f"<td>{seg.fx_a.mark}</td><td>{seg.fx_b.mark}</td>"
                f"<td>{seg.fx_a.dt:%Y-%m-%d %H:%M}</td><td>{seg.fx_b.dt:%Y-%m-%d %H:%M}</td>"
                f"<td>[{lo:.3f}, {hi:.3f}]</td><td>{len(seg.bis)}</td>"
                f"<td>{diff:.3f}</td><td>{status}</td></tr>")

        bi_rows = []
        for i, b in enumerate(bis_, 1):
            cn = "向上" if b.direction == "Up" else "向下"
            cls = "up" if b.direction == "Up" else "down"
            lo = min(b.fx_a.fx, b.fx_b.fx)
            hi = max(b.fx_a.fx, b.fx_b.fx)
            diff = abs(b.fx_b.fx - b.fx_a.fx)
            bi_rows.append(
                f"<tr class='{cls}'><td>{i}</td><td class='dir'>{cn}</td>"
                f"<td>{b.fx_a.mark}</td><td>{b.fx_b.mark}</td>"
                f"<td>{b.fx_a.dt:%Y-%m-%d %H:%M}</td><td>{b.fx_b.dt:%Y-%m-%d %H:%M}</td>"
                f"<td>[{lo:.3f}, {hi:.3f}]</td><td>{len(b.bars)}</td><td>{diff:.3f}</td></tr>")

        fxs = self.fxs
        fx_rows = []
        for i, fx in enumerate(fxs, 1):
            t = "顶分型" if fx.mark == "G" else "底分型"
            fx_rows.append(
                f"<tr><td>{i}</td><td>{t}</td><td>{fx.dt:%Y-%m-%d %H:%M}</td>"
                f"<td>{fx.fx:.3f}</td><td>{fx.power_str()}</td>"
                f"<td>{fx.power_volume():.0f}</td></tr>")

        g_cnt = sum(1 for x in fxs if x.mark == "G")
        d_cnt = sum(1 for x in fxs if x.mark == "D")
        up_cnt = sum(1 for b in bis_ if b.direction == "Up")
        dn_cnt = sum(1 for b in bis_ if b.direction == "Down")
        useg_cnt = sum(1 for s in fsegs if s.direction == "Up")
        dseg_cnt = sum(1 for s in fsegs if s.direction == "Down")

        bp = box_params or {}
        boxes = self.find_boxes(**bp)
        box_rects = []
        box_cores = []
        box_bounds = []
        box_rows = []
        for i, bx in enumerate(boxes, 1):
            si = _to_idx(bx["start"])
            ei = _to_idx(bx["end"])
            box_rects.append([si, ei, round(bx["dd"], 3), round(bx["gg"], 3)])
            box_cores.append([si, ei, round(bx["zd"], 3), round(bx["zg"], 3)])
            for lv in (bx["gg"], bx["dd"]):
                box_bounds.append([si, round(lv, 3)])
                box_bounds.append([ei, round(lv, 3)])
                box_bounds.append(None)
            box_rows.append(
                f"<tr class='boxrow'><td>{i}</td>"
                f"<td>{bx['start']:%Y-%m-%d %H:%M}</td><td>{bx['end']:%Y-%m-%d %H:%M}</td>"
                f"<td>{bx['gg']:.3f}</td><td>{bx['dd']:.3f}</td>"
                f"<td>{bx['zg']:.3f}</td><td>{bx['zd']:.3f}</td>"
                f"<td>{bx['full_h_pct']:.2f}%</td><td>{bx['n_bis']}</td><td>{bx['bars']}</td>"
                f"<td>{bx['reason']}</td></tr>")

        chart_h = 560 if n > 200 else 500

        js_data = {
            "catLabels": cat_labels, "labelInterval": label_interval,
            "kline": kline, "biLine": bi_line, "segLine": seg_line,
            "topFx": top_fx, "bottomFx": bottom_fx,
            "vols": vol_data, "trendAreas": trend_areas,
            "boxRects": box_rects, "boxCores": box_cores, "boxBounds": box_bounds,
            "zoomStart": max(0, round((1 - 800.0 / max(n, 1)) * 100)),
        }

        if out_path:
            out_path = os.path.abspath(out_path)
        else:
            out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, "%s_%s_%s_chan.html" % (
                self.symbol.replace(".", "_"), self.freq,
                (edt or bars[-1].dt).strftime("%Y%m%d")))

        html = _HTML_TEMPLATE
        html = html.replace("__ECHARTS__", "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js")
        html = html.replace("__SYMBOL__", self.symbol)
        html = html.replace("__FREQ__", self.freq)
        html = html.replace("__SDT__", str(sdt.date()) if sdt else "?")
        html = html.replace("__EDT__", str(edt.date()) if edt else "?")
        html = html.replace("__BARS__", str(len(bars)))
        html = html.replace("__PREWARM__", str(prewarm))
        html = html.replace("__CLOSEDT__", bars[-1].dt.strftime("%Y-%m-%d %H:%M"))
        html = html.replace("__FXS__", str(len(fxs)))
        html = html.replace("__GFX__", str(g_cnt))
        html = html.replace("__DFX__", str(d_cnt))
        html = html.replace("__BIS__", str(len(bis_)))
        html = html.replace("__UPBIS__", str(up_cnt))
        html = html.replace("__DNBIS__", str(dn_cnt))
        html = html.replace("__SEGS__", str(len(fsegs)))
        html = html.replace("__UPSEGS__", str(useg_cnt))
        html = html.replace("__DNSEGS__", str(dseg_cnt))
        html = html.replace("__UNFINSEGS__",
                            "｜ 另有 1 段未完成" if len(segs) > len(fsegs) else "")
        html = html.replace("__BOXCNT__", str(len(boxes)))
        html = html.replace("__BOX_ROWS__", "".join(box_rows))
        html = html.replace("__TREND_ROWS__", "".join(trend_rows))
        html = html.replace("__SEG_ROWS__", "".join(seg_rows))
        html = html.replace("__BI_ROWS__", "".join(bi_rows))
        html = html.replace("__FX_ROWS__", "".join(fx_rows))
        html = html.replace("__CHART_H__", str(chart_h))
        html = html.replace("__DATA__", json.dumps(js_data, ensure_ascii=False))

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        return out_path
