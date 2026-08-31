# -*- coding: utf-8 -*-
"""HTML 图表报告（ECharts）：K线 + 笔 + 分型 + 中枢 + 买卖点 + MACD"""
import json
import os
import bisect
from datetime import datetime

from chan import config

_HTML_TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script src="__ECHARTS__"></script>
<script>if(!window.echarts){document.write('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"><\/script>')}</script>
<style>
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;margin:0;background:#f5f6fa;color:#333}
.wrap{max-width:1280px;margin:0 auto;padding:16px}
.header{background:#fff;border-radius:10px;padding:16px 22px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.header h1{margin:0 0 8px;font-size:22px}
.header .meta{color:#666;font-size:13px;line-height:1.9}
.badges{margin-top:10px}
.badge{display:inline-block;padding:4px 16px;border-radius:20px;color:#fff;font-size:14px;font-weight:bold;margin-right:8px}
.badge.up{background:#e0503e}.badge.down{background:#1a9a5a}.badge.flat{background:#7f8c9b}
.badge.bs{background:#2f6fed}
#chart{background:#fff;border-radius:10px;padding:6px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.report{background:#fff;border-radius:10px;padding:18px 22px;margin-top:14px;box-shadow:0 1px 4px rgba(0,0,0,.08);font-size:14px;line-height:1.9}
.report h2{font-size:16px;border-left:4px solid #2f6fed;padding-left:10px;margin:16px 0 8px}
.report h2:first-child{margin-top:0}
table.kv{width:100%;border-collapse:collapse;margin-top:4px}
table.kv td{border:1px solid #eee;padding:6px 12px}
table.kv td:first-child{background:#fafbfc;color:#666;width:130px}
table.bs{width:100%;border-collapse:collapse;margin-top:4px}
table.bs th,table.bs td{border:1px solid #eee;padding:6px 12px;text-align:left}
table.bs th{background:#fafbfc;color:#666;font-weight:normal}
.footer{color:#999;font-size:12px;text-align:center;margin:16px 0 30px}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>缠论量化分析 · __SYMBOL__</h1>
    <div class="meta">
      周期：__FREQ__ ｜ 区间：__SDT__ ~ __EDT__ ｜ K线：__BARS__ 根（含 __PREWARM__ 预热）<br>
      分型：__FXS__ ｜ 笔：__BIS__（向上 __BIS_UP__ / 向下 __BIS_DN__）｜ 线段：__SEGS__ ｜ 中枢：__ZSS__<br>
      走势类型：__TRENDS__ ｜ 买卖点：__BS_CNT__
    </div>
    <div class="badges">
      __BS_BADGES__
    </div>
  </div>
  <div id="chart" style="width:100%;height:660px;"></div>
  <div class="report">
    <h2>买卖点明细</h2>
    __BS_TABLE__
    <h2>中枢明细</h2>
    __ZS_TABLE__
    <h2>走势类型</h2>
    __TREND_TABLE__
  </div>
  <div class="footer">由 缠论量化逻辑（模块1-8）生成 ｜ 技术分析仅供参考</div>
</div>
<script>
var DATA = __DATA__;
var chart = echarts.init(document.getElementById('chart'));
var fmt = function(v){var d=new Date(v);function p(x){return (x<10?'0':'')+x}return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())};
var option = {
  animation:false,
  tooltip:{trigger:'axis',axisPointer:{type:'cross'},backgroundColor:'rgba(255,255,255,.96)',borderColor:'#ddd',textStyle:{color:'#333',fontSize:12}},
  legend:{data:['K线','笔','顶分型','底分型','买卖点'],top:6,textStyle:{fontSize:12}},
  axisPointer:{link:[{xAxisIndex:'all'}]},
  grid:[
    {left:70,right:28,top:42,height:'50%'},
    {left:70,right:28,top:'60%',height:'11%'},
    {left:70,right:28,top:'76%',height:'12%'}
  ],
  xAxis:[
    {type:'category',gridIndex:0,data:DATA.catLabels,axisLabel:{interval:DATA.labelInterval,color:'#666'},axisLine:{lineStyle:{color:'#ccc'}}},
    {type:'category',gridIndex:1,data:DATA.catLabels,axisLabel:{show:false}},
    {type:'category',gridIndex:2,data:DATA.catLabels,axisLabel:{interval:DATA.labelInterval,color:'#666'},axisLine:{lineStyle:{color:'#ccc'}}}
  ],
  yAxis:[
    {gridIndex:0,scale:true,splitLine:{lineStyle:{color:'#f0f0f0'}},axisLabel:{color:'#666'}},
    {gridIndex:1,scale:true,splitLine:{show:false},axisLabel:{color:'#999',fontSize:10}},
    {gridIndex:2,scale:true,splitLine:{show:false},axisLabel:{color:'#999',fontSize:10}}
  ],
  dataZoom:[
    {type:'inside',xAxisIndex:[0,1,2],start:DATA.zoomStart,end:100},
    {type:'slider',xAxisIndex:[0,1,2],bottom:4,start:DATA.zoomStart,end:100,height:16}
  ],
  series:[
    {name:'K线',type:'candlestick',data:DATA.kline,itemStyle:{color:'#e0503e',color0:'#1a9a5a',borderColor:'#e0503e',borderColor0:'#1a9a5a'}},
    {name:'笔',type:'line',data:DATA.biLine,symbol:'none',lineStyle:{width:1.6,color:'#222'},z:6},
    {name:'中枢',type:'line',data:[],markArea:{silent:true,data:DATA.zsAreas},z:5},
    {name:'顶分型',type:'scatter',data:DATA.topFx,symbol:'triangle',symbolSize:11,itemStyle:{color:'#e0503e'},z:7},
    {name:'底分型',type:'scatter',data:DATA.bottomFx,symbol:'triangle',symbolRotate:180,symbolSize:11,itemStyle:{color:'#1a9a5a'},z:7},
    {name:'买卖点',type:'scatter',data:DATA.bsPoints,symbol:'pin',symbolSize:28,itemStyle:{color:function(p){return p.data[3]==='买'?'#e0503e':'#1a9a5a'}},label:{show:true,formatter:function(p){return p.data[2]},position:'inside',color:'#fff',fontSize:11},z:8},
    {name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:DATA.vols,itemStyle:{color:function(p){return p.data[1]>0?'#e0503e':'#1a9a5a'}}},
    {name:'MACD',type:'bar',xAxisIndex:2,yAxisIndex:2,data:DATA.macd,itemStyle:{color:function(p){return p.data[1]>=0?'#e0503e':'#1a9a5a'}}},
    {name:'DIF',type:'line',xAxisIndex:2,yAxisIndex:2,data:DATA.dif,symbol:'none',lineStyle:{width:1,color:'#f6a821'}},
    {name:'DEA',type:'line',xAxisIndex:2,yAxisIndex:2,data:DATA.dea,symbol:'none',lineStyle:{width:1,color:'#2f6fed'}}
  ]
};
chart.setOption(option);
window.addEventListener('resize',function(){chart.resize();});
</script>
</body>
</html>
"""


def _ts(dt):
    return int(dt.timestamp() * 1000)


def _idx_of(klines, dt, mode='right'):
    dts = [k.time for k in klines]
    if mode == 'left':
        return bisect.bisect_left(dts, dt)
    return bisect.bisect_right(dts, dt) - 1


def _echarts_src(html_path):
    base = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(base, "assets", "echarts.min.js")
    if os.path.exists(local):
        rel = os.path.relpath(local, os.path.dirname(os.path.abspath(html_path)))
        return rel.replace("\\", "/")
    return "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"


def render_html(out_path, symbol, freq, sdt, edt, raw_klines, result, prewarm=0):
    """生成自包含 HTML 报告"""
    klines = result['klines_processed']
    n = len(klines)
    dts = [k.time for k in klines]
    opens = [k.open for k in klines]
    closes = [k.close for k in klines]
    highs = [k.high for k in klines]
    lows = [k.low for k in klines]

    if freq in ("日线", "周线", "月线"):
        cat_labels = [k.time.strftime("%Y-%m-%d") for k in klines]
    else:
        cat_labels = [k.time.strftime("%m-%d %H:%M") for k in klines]
    label_interval = max(1, n // 14)

    kline_data = [[opens[i], closes[i], lows[i], highs[i]] for i in range(n)]
    vol_data = [[klines[i].volume, 1 if closes[i] >= opens[i] else -1] for i in range(n)]

    # 笔线
    bi_line = []
    for b in result['bis']:
        bi_line.append([_idx_of(klines, b.start_time), round(b.start_price, 3)])
        bi_line.append([_idx_of(klines, b.end_time), round(b.end_price, 3)])

    # 分型（笔端点）
    top_fx, bottom_fx, seen = [], [], set()
    for b in result['bis']:
        for fx, price in ((b.fx_start, b.start_price), (b.fx_end, b.end_price)):
            if fx is None:
                continue
            key = (_idx_of(klines, fx.time), fx.type)
            if key in seen:
                continue
            seen.add(key)
            if fx.type == 'top':
                top_fx.append([key[0], round(price, 3)])
            else:
                bottom_fx.append([key[0], round(price, 3)])

    # 中枢
    zs_areas = []
    for i, z in enumerate(result['zhongshu']):
        s_i, e_i = _idx_of(klines, z.start_time), _idx_of(klines, z.end_time)
        if len(z.units) >= 2:
            s_i = _idx_of(klines, z.units[1].start_time)
            e_i = _idx_of(klines, z.units[-2].end_time)
        d = "上升" if z.is_up else "下降"
        zs_areas.append([
            {"xAxis": s_i, "yAxis": round(z.ZG, 3),
             "itemStyle": {"color": "rgba(47,111,237,0.15)",
                           "borderColor": "#2f6fed", "borderWidth": 1, "borderType": "dashed"},
             "label": {"show": True,
                       "formatter": "中枢%d %d单元 %s [%.2f,%.2f]" % (i + 1, z.unit_count, d, z.ZD, z.ZG),
                       "color": "#2f6fed", "fontSize": 10, "position": "insideTop"}},
            {"xAxis": e_i, "yAxis": round(z.ZD, 3)},
        ])

    # 买卖点
    bs_points = []
    for p in result['bs_points']:
        kind = "买" if p.is_buy else "卖"
        bs_points.append([_idx_of(klines, p.time), round(p.price, 3),
                          "一买" if p.type == "1B" else "二买" if p.type == "2B" else "三买"
                          if p.type == "3B" else "一卖" if p.type == "1S" else "二卖" if p.type == "2S" else "三卖",
                          kind])

    # MACD（基于原始K线）
    dif, dea, hist = result['macd']
    def _line_vals(vals, rnd=3):
        return [None if vals[i] is None else round(vals[i], rnd) for i in range(n)]
    # MACD 序列与处理后K线索引不对齐：用处理后K线对应原始位置近似（简化为原始K线索引）
    raw_n = len(raw_klines)
    if raw_n == n:
        macd = [[round(hist[i], 4), 1 if hist[i] >= 0 else -1] for i in range(n)]
        dif_d = _line_vals(dif)
        dea_d = _line_vals(dea)
    else:
        # 处理后K线 time 映射到原始索引
        raw_dts = [k.time for k in raw_klines]
        macd = []
        for k in klines:
            idx = bisect.bisect_right(raw_dts, k.time) - 1
            idx = max(0, min(idx, raw_n - 1))
            macd.append([round(hist[idx], 4), 1 if hist[idx] >= 0 else -1])
        dif_d = [round(dif[max(0, bisect.bisect_right(raw_dts, k.time) - 1)], 3) for k in klines]
        dea_d = [round(dea[max(0, bisect.bisect_right(raw_dts, k.time) - 1)], 3) for k in klines]

    js_data = {
        "catLabels": cat_labels, "labelInterval": label_interval,
        "kline": kline_data, "biLine": bi_line,
        "topFx": top_fx, "bottomFx": bottom_fx,
        "bsPoints": bs_points, "zsAreas": zs_areas,
        "vols": vol_data, "macd": macd, "dif": dif_d, "dea": dea_d,
        "zoomStart": max(0, round((1 - 800.0 / max(n, 1)) * 100)),
    }

    # ---- 表格 ----
    bs_badges = "".join('<span class="badge bs">%s</span>' % _bs_cn(p.type) for p in result['bs_points'][:8])
    if result['bs_points']:
        bs_rows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%.3f</td><td>%s</td><td>%s</td></tr>"
            % (_bs_cn(p.type), p.time.strftime("%Y-%m-%d %H:%M"), p.price,
               ("已失效" if p.invalid else ("已确认" if p.status == "confirmed" else "待确认")),
               p.desc)
            for p in result['bs_points'])
        bs_table = ("<table class='bs'><tr><th>信号</th><th>时间</th><th>价格</th><th>状态</th><th>说明</th></tr>%s</table>" % bs_rows)
    else:
        bs_table = "<p style='color:#999'>无买卖点</p>"
    zs_rows = "".join(
        "<tr><td>中枢%d</td><td>%s</td><td>%s</td><td>%s</td><td>%.3f</td><td>%.3f</td><td>%d</td><td>%s</td></tr>"
        % (i + 1, "上升" if z.is_up else "下降", z.start_time.strftime("%Y-%m-%d"),
           z.end_time.strftime("%Y-%m-%d"), z.ZD, z.ZG, z.unit_count, z.status)
        for i, z in enumerate(result['zhongshu']))
    zs_table = ("<table class='bs'><tr><th>中枢</th><th>方向</th><th>开始</th><th>结束</th><th>ZD</th><th>ZG</th><th>单元</th><th>状态</th></tr>%s</table>" % zs_rows) if zs_rows else "<p style='color:#999'>无中枢</p>"
    trend_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%d</td></tr>"
        % ({"trend_up": "上涨趋势", "trend_down": "下跌趋势", "consolidation": "盘整"}[t.type],
           t.start_time.strftime("%Y-%m-%d"), t.end_time.strftime("%Y-%m-%d"),
           "%.2f→%.2f" % (t.start_price, t.end_price), len(t.center_list))
        for t in result['trends'])
    trend_table = ("<table class='bs'><tr><th>类型</th><th>开始</th><th>结束</th><th>价格</th><th>中枢数</th></tr>%s</table>" % trend_rows) if trend_rows else "<p style='color:#999'>无走势类型</p>"

    # ---- 头部 ----
    bis_up = sum(1 for b in result['bis'] if b.is_up)
    bis_dn = len(result['bis']) - bis_up

    html = _HTML_TPL
    html = html.replace("__TITLE__", "缠论量化分析 %s %s" % (symbol, freq))
    html = html.replace("__ECHARTS__", _echarts_src(out_path))
    html = html.replace("__SYMBOL__", symbol)
    html = html.replace("__FREQ__", freq)
    html = html.replace("__SDT__", str(sdt.date()))
    html = html.replace("__EDT__", str(edt.date()))
    html = html.replace("__BARS__", str(n))
    html = html.replace("__PREWARM__", str(prewarm))
    html = html.replace("__FXS__", str(len(result['fxs'])))
    html = html.replace("__BIS__", str(len(result['bis'])))
    html = html.replace("__BIS_UP__", str(bis_up))
    html = html.replace("__BIS_DN__", str(bis_dn))
    html = html.replace("__SEGS__", str(len(result['segments'])))
    html = html.replace("__ZSS__", str(len(result['zhongshu'])))
    html = html.replace("__TRENDS__", " / ".join({"trend_up": "上涨", "trend_down": "下跌", "consolidation": "盘整"}[t.type] for t in result['trends']) or "无")
    html = html.replace("__BS_CNT__", str(len(result['bs_points'])))
    html = html.replace("__BS_BADGES__", bs_badges)
    html = html.replace("__BS_TABLE__", bs_table)
    html = html.replace("__ZS_TABLE__", zs_table)
    html = html.replace("__TREND_TABLE__", trend_table)
    html = html.replace("__DATA__", json.dumps(js_data, ensure_ascii=False))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def _bs_cn(t):
    return {"1B": "一买", "2B": "二买", "3B": "三买",
            "1S": "一卖", "2S": "二卖", "3S": "三卖"}.get(t, t)
