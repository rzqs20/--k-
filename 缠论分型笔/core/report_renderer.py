# -*- coding: utf-8 -*-
"""
报告渲染器（ReportRenderer）
独立封装，负责终端文本和HTML图表报告的生成。
改前端展示只动这个文件，不碰分析逻辑。

用法：
    from core.report_renderer import ReportRenderer
    renderer = ReportRenderer(ana)
    renderer.print_terminal(sdt=..., edt=..., prewarm=0)
    renderer.render_html("report.html", sdt=..., edt=...)
"""
import os
import json
import bisect


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
    <h2>趋势识别（箱体突破型，共 __TRENDCNT__ 段）</h2>
    <table class="bi">
      <tr><th>#</th><th>方向</th><th>分类标签</th><th>起始时间</th><th>结束时间</th><th>起始价</th><th>结束价</th><th>涨跌幅</th><th>持续K线</th><th>判断依据</th></tr>
      __TREND_ROWS__
    </table>
    <h2>箱体识别（基于笔斜率，自适应周期，共 __BOXCNT__ 个）</h2>
    <table class="bi">
      <tr><th>#</th><th>起始时间</th><th>结束时间</th><th>GG最高</th><th>DD最低</th><th>P90压力</th><th>P10支撑</th><th>箱体高度</th><th>笔数</th><th>K线数</th><th>量能</th><th>判断依据</th></tr>
      __BOX_ROWS__
    </table>
    <h2>突破监测（箱体结束后放量突破验证，共 __BREAKOUTCNT__ 个有效突破）</h2>
    <table class="bi">
      <tr><th>#</th><th>箱体</th><th>盘整质量</th><th>方向</th><th>观察日(T)</th><th>观察量%</th><th>突破日</th><th>突破量%</th><th>突破价</th><th>得分</th><th>突破后涨跌</th><th>涨幅终点</th><th>状态</th><th>详情</th></tr>
      __BREAKOUT_ROWS__
    </table>
    <h3>评分变化明细（逐日动态评分）</h3>
    <table class="bi">
      <tr><th>箱体</th><th>日期</th><th>T+n</th><th>收盘价</th><th>当日量%</th><th>均量%</th><th>时间分</th><th>量能分</th><th>当日量分</th><th>稳步分</th><th>总分</th><th>状态</th></tr>
      __SCORE_HISTORY_ROWS__
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


class ReportRenderer:
    """
    报告渲染器：接收 ChanAnalyzer 实例，生成终端文本和HTML图表报告。

    Parameters
    ----------
    ana : ChanAnalyzer
        已完成分析的 ChanAnalyzer 实例
    """

    def __init__(self, ana):
        self.ana = ana

    # ------------------------------------------------------------------
    # 终端文本报告
    # ------------------------------------------------------------------
    def print_terminal(self, sdt=None, edt=None, prewarm=0,
                       trend_pct=3.0, trend_bars=20,
                       box_params=None):
        """打印终端文本报告。"""
        ana = self.ana
        bis_ = ana.bi_list
        fxs = ana.fxs
        segs = ana.segments
        fsegs = ana.finished_segments
        g_cnt = sum(1 for x in fxs if x.mark == "G")
        d_cnt = sum(1 for x in fxs if x.mark == "D")
        up_cnt = sum(1 for b in bis_ if b.direction == "Up")
        dn_cnt = sum(1 for b in bis_ if b.direction == "Down")
        useg_cnt = sum(1 for s in fsegs if s.direction == "Up")
        dseg_cnt = sum(1 for s in fsegs if s.direction == "Down")

        print("=" * 64)
        print("              缠论 · 分型/笔/线段 分析报告（纯缠论版）")
        print("=" * 64)
        print(f"标的：{ana.symbol}")
        print(f"周期：{ana.freq}   |   判断区间：{sdt.date() if sdt else '?'} ~ {edt.date() if edt else '?'}")
        print(f"K线：{len(ana.bars)} 根（含 {prewarm} 根历史预热）   |   "
              f"最新K线时间：{ana.bars[-1].dt:%Y-%m-%d %H:%M}")
        print("-" * 64)
        print("[结构统计]")
        print(f"  分型：{len(fxs)} 个（顶 {g_cnt} / 底 {d_cnt}，笔端点分型）")
        print(f"  笔：{len(bis_)} 笔（向上 {up_cnt} / 向下 {dn_cnt}）")
        print(f"  线段：{len(fsegs)} 段已确认（向上 {useg_cnt} / 向下 {dseg_cnt}）"
              + (f"，另有 {len(segs) - len(fsegs)} 段未完成" if len(segs) > len(fsegs) else ""))
        print(f"  最后一笔延伸中：{'是' if ana.last_bi_extend else '否'}")

        trends = ana.find_trends()
        trend_up = sum(1 for t in trends if t["direction"] == "up")
        trend_dn = sum(1 for t in trends if t["direction"] == "down")
        print("-" * 64)
        print(f"[趋势识别] 共 {len(trends)} 段趋势（上涨 {trend_up} / 下跌 {trend_dn}）")
        print(f"  逻辑：线段趋势（与箱体重叠的线段不标记）")
        for t in trends:
            mark = "★上涨趋势" if t["direction"] == "up" else "★下跌趋势"
            print(f"  {t['idx']:>2}. {mark}  {t['start_time']:%Y-%m-%d %H:%M} -> {t['end_time']:%Y-%m-%d %H:%M}"
                  f"  {t['change_pct']:+.2f}%  {t['bar_count']}根  线段{t['seg_idx']}  | {t['reason']}")

        bp = box_params or {}
        boxes = ana.find_boxes(**bp)
        print("-" * 64)
        print(f"[箱体识别] 共 {len(boxes)} 个箱体（基于笔斜率，自适应周期）")
        print("  条件：连续>=4分型双条件(顶-顶/底-底斜率+绝对涨跌幅均<=前60%分位)，整体高度>=0.5%（不设上限）（自适应周期）")
        for i, bx in enumerate(boxes, 1):
            core_zg = bx.get("zg_trimmed", bx["zg"])
            core_zd = bx.get("zd_trimmed", bx["zd"])
            trimmed_mark = "*" if bx.get("trimmed", False) else ""
            print(f"  {i:>2}. 箱体  {bx['start']:%Y-%m-%d %H:%M} -> {bx['end']:%Y-%m-%d %H:%M}"
                  f"  箱体[{bx['dd']:.1f},{bx['gg']:.1f}] 重叠[{core_zd:.1f},{core_zg:.1f}]{trimmed_mark}"
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
        ana = self.ana
        bars = ana.bars
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
            if ana.freq in ("日线", "周线", "月线"):
                return dt.strftime("%Y-%m-%d")
            return dt.strftime("%m-%d %H:%M")

        cat_labels = [_fmt_dt(b.dt) for b in bars]
        label_interval = max(1, n // 14)
        kline = [[opens[i], closes[i], lows[i], highs[i]] for i in range(n)]
        vol_data = [{"value": vols[i],
                     "itemStyle": {"color": "#e0503e" if closes[i] >= opens[i] else "#1a9a5a"}}
                    for i in range(n)]

        bis_ = ana.bi_list
        bi_line = []
        for b in bis_:
            bi_line.append([_to_idx(b.fx_a.dt), round(b.fx_a.fx, 3)])
            bi_line.append([_to_idx(b.fx_b.dt), round(b.fx_b.fx, 3)])

        segs = ana.segments
        fsegs = ana.finished_segments
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

        # 调用分类器，获取带标签的箱体和趋势
        classified = ana.classify()
        trends = classified["trends"]
        boxes_labeled = classified["boxes"]
        trend_areas = []
        trend_rows = []
        for t in trends:
            si = _to_idx(t["start_time"])
            ei = _to_idx(t["end_time"])
            if t["direction"] == "up":
                color = "rgba(224,80,62,0.10)"
                border = "#e0503e"
                cn = "★上涨"
                cls = "upseg"
            else:
                color = "rgba(26,154,90,0.10)"
                border = "#1a9a5a"
                cn = "★下跌"
                cls = "dnseg"
            trend_areas.append([
                {"xAxis": si, "itemStyle": {"color": color, "borderColor": border, "borderWidth": 1}},
                {"xAxis": ei, "name": cn},
            ])
            label = t.get("label", "-")
            trend_rows.append(
                f"<tr class='{cls}'><td>{t['idx']}</td><td class='dir'>{cn}</td>"
                f"<td style='font-size:11px;color:#555'>{label}</td>"
                f"<td>{t['start_time']:%Y-%m-%d %H:%M}</td><td>{t['end_time']:%Y-%m-%d %H:%M}</td>"
                f"<td>{t['start_price']:.3f}</td><td>{t['end_price']:.3f}</td>"
                f"<td>{t['change_pct']:+.2f}%</td><td>{t['bar_count']}</td>"
                f"<td>{t['reason']}</td></tr>")

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

        fxs = ana.fxs
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

        # 箱体使用 classify 结果，计算内部价格分位和突破监测
        boxes_pct = ana.trend_classifier.calc_box_percentiles(boxes_labeled, bars)
        boxes = ana.trend_classifier.analyze_breakouts(boxes_pct, bars, segments=segs)
        # 二次突破分析：第一次突破失败后，监测是否有二次突破（同向或反向）
        boxes = ana.secondary_breakout_analyzer.analyze(boxes, bars)
        box_rects = []
        box_cores = []
        box_bounds = []
        box_rows = []
        for i, bx in enumerate(boxes, 1):
            si = _to_idx(bx["start"])
            ei = _to_idx(bx["end"])
            box_rects.append([si, ei, round(bx["dd"], 3), round(bx["gg"], 3)])
            # 中枢线用去极值后的ZG/ZD（如果有的话）
            core_zg = bx.get("zg_trimmed", bx["zg"])
            core_zd = bx.get("zd_trimmed", bx["zd"])
            box_cores.append([si, ei, round(core_zd, 3), round(core_zg, 3)])
            for lv in (bx["gg"], bx["dd"]):
                box_bounds.append([si, round(lv, 3)])
                box_bounds.append([ei, round(lv, 3)])
                box_bounds.append(None)
            # 量能标签颜色
            vol_label = bx.get("vol_label", "数据不足")
            vol_ratio = bx.get("vol_ratio", 1.0)
            if "放量" in vol_label:
                vol_color = "#e0503e"
            elif "缩量" in vol_label:
                vol_color = "#1a9a5a"
            else:
                vol_color = "#666"
            box_rows.append(
                f"<tr class='boxrow'><td>{i}</td>"
                f"<td>{bx['start']:%Y-%m-%d %H:%M}</td><td>{bx['end']:%Y-%m-%d %H:%M}</td>"
                f"<td>{bx['gg']:.3f}</td><td>{bx['dd']:.3f}</td>"
                f"<td style='color:#e0503e'>{bx['p90']:.3f}</td>"
                f"<td style='color:#1a9a5a'>{bx['p10']:.3f}</td>"
                f"<td>{bx['full_h_pct']:.2f}%</td><td>{bx['n_bis']}</td><td>{bx['bars']}</td>"
                f"<td style='color:{vol_color};font-weight:bold'>{vol_label}({vol_ratio:.2f})</td>"
                f"<td>{bx['reason']}</td></tr>")

        # 突破监测表格（独立卡片）
        breakout_rows = []
        breakout_cnt = 0
        for i, bx in enumerate(boxes, 1):
            bo = bx.get("breakout", {})
            bo_dir = bo.get("direction", "none")
            bo_status = bo.get("status", "-")
            if bo_status in ("放量突破", "无量突破", "缩量突破"):
                breakout_cnt += 1
                if bo_status == "放量突破":
                    status_color = "#e0503e" if bo_dir == "up" else "#1a9a5a"
                    status_cls = "upseg" if bo_dir == "up" else "dnseg"
                elif bo_status == "无量突破":
                    status_color = "#faad14"
                    status_cls = ""
                else:  # 缩量突破
                    status_color = "#999"
                    status_cls = ""
            else:  # 突破失败/未突破
                status_color = "#999"
                status_cls = ""

            if bo_dir == "up":
                dir_text = "↑向上"
                dir_color = "#e0503e"
            elif bo_dir == "down":
                dir_text = "↓向下"
                dir_color = "#1a9a5a"
            else:
                dir_text = "无"
                dir_color = "#999"

            obs_time = bo['observe_time'].strftime("%Y-%m-%d") if bo.get('observe_time') else "-"
            obs_vol_pct = bo.get('observe_vol_pct', 0)
            obs_vol_text = f"{obs_vol_pct:.0f}%" if obs_vol_pct > 0 else "-"
            obs_vol_color = "#e0503e" if obs_vol_pct >= 70 else "#1a9a5a" if obs_vol_pct <= 30 else "#666"

            bo_time = bo['breakout_time'].strftime("%Y-%m-%d") if bo.get('breakout_time') else "-"
            bo_price = f"{bo['breakout_price']:.2f}" if bo.get('breakout_price') else "-"
            bo_vol_pct = bo.get('breakout_vol_pct', 0)
            bo_vol_text = f"{bo_vol_pct:.0f}%" if bo_vol_pct > 0 else "-"
            bo_vol_color = "#e0503e" if bo_vol_pct >= 70 else "#1a9a5a" if bo_vol_pct <= 30 else "#666"

            bo_pct = bo.get("breakout_pct", 0)
            if bo_pct > 0:
                pct_text = f"+{bo_pct:.2f}%"
                pct_color = "#e0503e"
            elif bo_pct < 0:
                pct_text = f"{bo_pct:.2f}%"
                pct_color = "#1a9a5a"
            else:
                pct_text = "-"
                pct_color = "#999"
            # 盘整标准度（仅标签，不参与评分）
            standard_label = bx.get("standard_label", "中性")
            standard_score = bx.get("standard_score", 0)
            standard_ratio = bx.get("standard_ratio", 0.0)
            if standard_score >= 2:
                standard_color = "#e0503e"
            elif standard_score >= 1:
                standard_color = "#faad14"
            elif standard_score == 0:
                standard_color = "#666"
            else:
                standard_color = "#1a9a5a"
            standard_text = f"{standard_label}"

            breakout_rows.append(
                f"<tr class='{status_cls}'><td>{i}</td>"
                f"<td>{bx['start']:%Y-%m-%d} ~ {bx['end']:%Y-%m-%d}</td>"
                f"<td style='color:{standard_color};font-weight:bold'>{standard_text}</td>"
                f"<td style='color:{dir_color};font-weight:bold'>{dir_text}</td>"
                f"<td>{obs_time}</td>"
                f"<td style='color:{obs_vol_color};font-weight:bold'>{obs_vol_text}</td>"
                f"<td>{bo_time}</td>"
                f"<td style='color:{bo_vol_color};font-weight:bold'>{bo_vol_text}</td>"
                f"<td>{bo_price}</td>"
                f"<td style='font-weight:bold;color:{'#e0503e' if bo.get('score', 0) >= 5 else '#faad14' if bo.get('score', 0) >= 3 else '#999'}'>{bo.get('score', 0)}</td>"
                f"<td style='color:{pct_color};font-weight:bold'>{pct_text}</td>"
                f"<td>{bo.get('breakout_end_time').strftime('%Y-%m-%d') if bo.get('breakout_end_time') else '-'}</td>"
                f"<td style='color:{status_color};font-weight:bold'>{bo_status}</td>"
                f"<td style='font-size:11px;color:#666'>{bo['detail']}</td></tr>")

        # 评分历史明细
        score_history_rows = []
        for i, bx in enumerate(boxes, 1):
            bo = bx.get("breakout", {})
            history = bo.get("score_history", [])
            for h in history:
                note = h.get("note", "")
                total = h["total"]
                if total >= 5:
                    total_color = "#e0503e"
                elif total >= 3:
                    total_color = "#faad14"
                elif total >= 0:
                    total_color = "#666"
                else:
                    total_color = "#1a9a5a"
                score_history_rows.append(
                    f"<tr><td>{i}</td>"
                    f"<td>{h['date'].strftime('%Y-%m-%d')}</td>"
                    f"<td>T+{h['day']}</td>"
                    f"<td>{h['close']:.2f}</td>"
                    f"<td>{h['vol_pct']:.0f}%</td>"
                    f"<td>{h['avg_vol_pct']:.0f}%</td>"
                    f"<td>{h['time_score']}</td>"
                    f"<td>{h['vol_score']:+d}</td>"
                    f"<td>{h['day_vol_score']}</td>"
                    f"<td>{h['steady_score']}</td>"
                    f"<td style='font-weight:bold;color:{total_color}'>{total}</td>"
                    f"<td style='font-size:11px;color:#666'>{note}</td></tr>")

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
                ana.symbol.replace(".", "_"), ana.freq,
                (edt or bars[-1].dt).strftime("%Y%m%d")))

        html = _HTML_TEMPLATE
        html = html.replace("__ECHARTS__", "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js")
        html = html.replace("__SYMBOL__", ana.symbol)
        html = html.replace("__FREQ__", ana.freq)
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
        html = html.replace("__TRENDCNT__", str(len(trends)))
        html = html.replace("__BOXCNT__", str(len(boxes)))
        html = html.replace("__BOX_ROWS__", "".join(box_rows))
        html = html.replace("__BREAKOUT_ROWS__", "".join(breakout_rows))
        html = html.replace("__SCORE_HISTORY_ROWS__", "".join(score_history_rows))
        html = html.replace("__BREAKOUTCNT__", str(breakout_cnt))
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
