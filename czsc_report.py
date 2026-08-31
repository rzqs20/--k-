# -*- coding: utf-8 -*-
"""
czsc 缠论分析报告生成器
========================
每次运行生成两份 HTML 报告：
  1. 原版：czsc 官方 lightweight-charts 渲染（无中枢/买卖点标注）
  2. 结构版：ECharts 渲染（去包含K线 + 中枢框 + 买卖点 + 合并日期标注）

数据源：D:\khData（DuckDB，每个标的一个 .db 文件）
用法：python czsc_report.py 002714.SZ 日线 2024-08-27 2026-08-27
"""
import sys, os, json, bisect, duckdb
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime

import pandas as pd
from czsc import CZSC, NewBar, format_standard_kline, generate_czsc_signals, remove_include
from dateutil.relativedelta import relativedelta

KHDATA = r"D:\khData"
_BS_NAME = {"一买": "买", "二买": "买", "三买": "买", "一卖": "卖", "二卖": "卖", "三卖": "卖"}

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

def load_khdata(symbol, exchange, freq, sdt, edt):
    """从 D:\khData 读 DuckDB K线 -> czsc RawBar 列表"""
    table = {"日线": "kline_1d", "5分钟": "kline_5m"}.get(freq, "kline_1m")
    db = os.path.join(KHDATA, exchange, symbol + ".db")
    if not os.path.exists(db):
        raise FileNotFoundError(f"未找到 {db}")
    con = duckdb.connect(db, read_only=True)
    df = con.execute(
        f"SELECT time AS dt, open, high, low, close, volume AS vol, amount "
        f"FROM {table} WHERE time::DATE >= ? AND time::DATE <= ? ORDER BY time",
        [sdt, edt]).fetchdf()
    con.close()
    df["symbol"] = f"{symbol}.{exchange}"
    df["amount"] = df["amount"].fillna(0.0).astype(float)
    df["vol"] = df["vol"].astype(float)
    return format_standard_kline(df, freq=freq)

def remove_include_all(bars):
    """全序列去包含（复用 czsc 官方 remove_include：k1/k2 为 NewBar，k3 为 RawBar）"""
    def to_nb(b):
        return NewBar(symbol=b.symbol, dt=b.dt, freq=b.freq, id=b.id, open=b.open,
                      close=b.close, high=b.high, low=b.low, vol=b.vol, amount=b.amount,
                      elements=[b])
    ubi = [to_nb(bars[0]), to_nb(bars[1])]
    for b in bars[2:]:
        has_inc, merged = remove_include(ubi[-2], ubi[-1], b)
        if has_inc:
            ubi[-1] = merged
        else:
            ubi.append(merged)
    return ubi

def parse_bs_events(df_sig, col, names):
    """从信号 DataFrame 提取买卖点首次触发事件"""
    events = []
    last_state = {}
    for _, row in df_sig.iterrows():
        v = row[col]
        if pd.isna(v) or "任意" in v.split("_")[0]:
            continue
        for nm in names:
            if v.startswith(nm):
                if last_state.get(nm) != v:
                    ev_dt = pd.to_datetime(row["dt"])
                    if ev_dt.tzinfo is not None:
                        ev_dt = ev_dt.tz_localize(None)  # 统一为 tz-naive
                    events.append({"name": nm, "dt": ev_dt,
                                   "price": float(row["close"]), "desc": v})
                last_state[nm] = v
                break
    return events


# ===================== 报告1：原版（czsc 官方 lightweight-charts） =====================
def render_original(label, freq, c, out_path):
    """原版：czsc 官方渲染，无中枢/买卖点标注。"""
    from czsc.utils.plotting.lightweight import plot_czsc
    return plot_czsc(c, output='html', path=out_path,
                     title=f'{label} {freq} 缠论结构（czsc 原版）')


# ===================== 报告2：ECharts 结构版（含中枢+买卖点+合并日期） =====================
def render_echarts(label, freq, sdt, edt, c, ubi, zs_list, events, out_path):
    n = len(ubi)
    dts = [b.dt for b in ubi]
    opens = [float(b.open) for b in ubi]
    closes = [float(b.close) for b in ubi]
    highs = [float(b.high) for b in ubi]
    lows = [float(b.low) for b in ubi]
    vols = [float(b.vol) for b in ubi]

    def _to_idx(dt):
        return bisect.bisect_right(dts, dt) - 1

    # x 轴标签：去包含K线 + 合并日期标注
    short_fmt = freq not in ('日线', '周线', '月线')
    def _fmt(dt):
        return dt.strftime('%m-%d %H:%M' if short_fmt else '%Y-%m-%d')
    cat_labels = []
    for nb in ubi:
        ds = [e.dt for e in nb.elements]
        if len(ds) == 1:
            cat_labels.append(_fmt(ds[0]))
        elif len(ds) <= 3:
            cat_labels.append('、'.join(_fmt(d) for d in ds))
        else:
            cat_labels.append('%s~%s(共%d根)' % (_fmt(ds[0]), _fmt(ds[-1]), len(ds)))
    label_interval = max(1, n // 14)

    kline = [[opens[i], closes[i], lows[i], highs[i]] for i in range(n)]
    vol_data = [[vols[i], 1 if closes[i] >= opens[i] else -1] for i in range(n)]

    def _ema(vals, k):
        e, out = None, []
        for v in vals:
            e = v if e is None else v * k + e * (1 - k)
            out.append(e)
        return out
    def _ma(vals, k):
        out, s = [], 0.0
        for i, v in enumerate(vals):
            s += v
            if i >= k:
                s -= vals[i - k]
            out.append(s / k if i >= k - 1 else None)
        return out

    ma5 = _ma(closes, 5)
    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)
    dif = [a - b for a, b in zip(_ema(closes, 2 / 13), _ema(closes, 2 / 27))]
    dea = _ema(dif, 2 / 10)
    hist = [(d - s) * 2 for d, s in zip(dif, dea)]
    macd = [[round(hist[i], 4), 1 if hist[i] >= 0 else -1] for i in range(n)]
    dif_d = [None if v is None else round(v, 4) for v in dif]
    dea_d = [None if v is None else round(v, 4) for v in dea]

    # 笔线（czsc bi_list）
    bi_line = []
    for b in c.bi_list:
        bi_line.append([_to_idx(b.fx_a.dt), round(float(b.fx_a.fx), 3)])
        bi_line.append([_to_idx(b.fx_b.dt), round(float(b.fx_b.fx), 3)])

    # 分型
    top_fx, bottom_fx, seen = [], [], set()
    for b in c.bi_list:
        for fx in (b.fx_a, b.fx_b):
            key = (_to_idx(fx.dt), fx.mark.name)
            if key in seen:
                continue
            seen.add(key)
            if fx.mark.name == 'G':
                top_fx.append([_to_idx(fx.dt), round(float(fx.high), 3)])
            else:
                bottom_fx.append([_to_idx(fx.dt), round(float(fx.low), 3)])

    # 中枢框（czsc zs_list）
    zs_areas = []
    for i, z in enumerate(zs_list):
        s_i = _to_idx(z.sdt)
        e_i = _to_idx(z.edt)
        zs_areas.append([
            {'xAxis': s_i, 'yAxis': round(float(z.zg), 3),
             'itemStyle': {'color': 'rgba(47,111,237,0.16)', 'borderColor': '#2f6fed',
                           'borderWidth': 1, 'borderType': 'dashed'},
             'label': {'show': True,
                       'formatter': '中枢%d %d笔 [%.2f,%.2f]' % (i + 1, len(z.bis), z.zd, z.zg),
                       'color': '#2f6fed', 'fontSize': 10, 'position': 'insideTop'}},
            {'xAxis': e_i, 'yAxis': round(float(z.zd), 3)},
        ])

    # 买卖点
    bs_points = []
    for ev in events:
        idx = bisect.bisect_right(dts, ev['dt']) - 1
        kind = _BS_NAME.get(ev['name'], '买')
        bs_points.append([idx, round(ev['price'], 3), ev['name'], kind])

    sdt_idx = bisect.bisect_left(dts, pd.to_datetime(sdt))

    # 统计
    bis_ = c.bi_list
    fx_all = c.fx_list
    g_cnt = sum(1 for x in fx_all if x.mark.name == 'G')
    d_cnt = sum(1 for x in fx_all if x.mark.name == 'D')
    up_cnt = sum(1 for b in bis_ if b.direction.name == 'Up')
    dn_cnt = sum(1 for b in bis_ if b.direction.name == 'Down')

    js_data = {
        'catLabels': cat_labels, 'labelInterval': label_interval,
        'kline': kline, 'ma5': [None if v is None else round(v, 3) for v in ma5],
        'ma20': [None if v is None else round(v, 3) for v in ma20],
        'ma60': [None if v is None else round(v, 3) for v in ma60],
        'biLine': bi_line, 'topFx': top_fx, 'bottomFx': bottom_fx,
        'bsPoints': bs_points, 'zsAreas': zs_areas, 'sdtIdx': sdt_idx,
        'vols': vol_data, 'macd': macd, 'dif': dif_d, 'dea': dea_d,
        'zoomStart': max(0, round((1 - 800.0 / max(n, 1)) * 100)),
        'symbol': label, 'freq': freq, 'sdt': str(sdt), 'edt': str(edt),
        'barsN': len(c.bars_raw), 'ubiN': n, 'fxN': len(fx_all),
        'biN': len(bis_), 'zsN': len(zs_list),
        'latestClose': round(closes[-1], 3), 'latestDt': str(dts[-1]),
    }

    bs_badges = ''.join('<span class="badge bs">%s</span>' % e['name'] for e in events)
    bs_table = ''
    if events:
        rows = ''.join(
            '<tr><td>%s</td><td>%s</td><td>%.3f</td><td>%s</td></tr>'
            % (e['name'], pd.to_datetime(e['dt']).strftime('%Y-%m-%d'), e['price'], e['desc'])
            for e in sorted(events, key=lambda x: x['dt']))
        bs_table = "<table class='bs'><tr><th>信号</th><th>时间</th><th>价格</th><th>说明</th></tr>%s</table>" % rows

    kv_rows = [
        ('标的', label), ('周期', freq),
        ('判断区间', '%s ~ %s' % (sdt, edt)),
        ('K线总数', '%d 根（图表显示去包含后 %d 根）' % (len(c.bars_raw), n)),
        ('分型', '%d 个（顶 %d / 底 %d）' % (len(fx_all), g_cnt, d_cnt)),
        ('完成笔', '%d 笔（向上 %d / 向下 %d）' % (len(bis_), up_cnt, dn_cnt)),
        ('有效中枢', '%d 个' % len(zs_list)),
        ('最新收盘', '%.3f（%s）' % (closes[-1], dts[-1])),
    ]
    kv = ''.join('<tr><td>%s</td><td>%s</td></tr>' % (k, v) for k, v in kv_rows)

    tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_template.html')
    template = open(tpl_path, encoding='utf-8').read()
    html = template
    html = html.replace('__TITLE__', 'czsc 缠论分析 %s %s（结构版）' % (label, freq))
    html = html.replace('__SYMBOL__', label)
    html = html.replace('__FREQ__', freq)
    html = html.replace('__BARS__', str(len(c.bars_raw)))
    html = html.replace('__UBI__', str(n))
    html = html.replace('__CLOSE__', '%.3f' % closes[-1])
    html = html.replace('__CLOSEDT__', str(dts[-1]))
    html = html.replace('__BIS__', str(len(bis_)))
    html = html.replace('__ZS__', str(len(zs_list)))
    html = html.replace('__FXS__', str(len(fx_all)))
    html = html.replace('__BS_BADGES__', bs_badges)
    html = html.replace('__BS_TABLE__', bs_table)
    html = html.replace('__KV__', kv)
    html = html.replace('__CHART_H__', '720' if n > 200 else '640')
    html = html.replace('__DATA__', json.dumps(js_data, ensure_ascii=False, default=str))
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return out_path


def main():
    args = sys.argv[1:]
    if len(args) >= 4:
        code_in, freq_in, sdt_in, edt_in = args[:4]
    else:
        print("用法: python czsc_report.py <代码> <周期> <起始> <终止>")
        print("示例: python czsc_report.py 002714.SZ 日线 2024-08-27 2026-08-27")
        return
    code, exchange = resolve_symbol(code_in)
    sdt, edt = sdt_in, edt_in
    label = f"{code}.{exchange}"

    print("=" * 62)
    print("           czsc 缠 论 分 析 报 告")
    print("=" * 62)
    print(f"标的：{label}   周期：{freq_in}   区间：{sdt} ~ {edt}")
    print()

    # ---- 1) 数据 + CZSC 结构 ----
    bars = load_khdata(code, exchange, freq_in, sdt, edt)
    c = CZSC(bars)
    bis = c.bi_list
    zs_list = c.zs_list
    print(f"[数据] {len(bars)} 根K线  最新收盘 {bars[-1].close:.3f}（{bars[-1].dt}）")
    print(f"[结构] 分型 {len(c.fx_list)}  完成笔 {len(bis)}（上{sum(1 for b in bis if b.direction.name=='Up')}/下{sum(1 for b in bis if b.direction.name=='Down')}）  中枢 {len(zs_list)}")
    print()

    print("[最近 3 笔]")
    for b in bis[-3:]:
        d = "向上" if b.direction.name == "Up" else "向下"
        print(f"  {d}  {b.sdt:%Y-%m-%d} -> {b.edt:%Y-%m-%d}  |  幅度 {b.power:.3f}  长度 {b.length}根  |  区间 [{b.low:.3f}, {b.high:.3f}]")
    print()

    print("[中枢序列]")
    for i, zs in enumerate(zs_list, 1):
        print(f"  中枢{i}: {zs.sdt:%Y-%m-%d} ~ {zs.edt:%Y-%m-%d}  [ {zs.zd:.3f}, {zs.zg:.3f} ]  中轴 {zs.zz:.3f}")
    print()

    # ---- 2) 买卖点信号（前推1年预热）----
    pre_sdt = (datetime.strptime(sdt, "%Y-%m-%d") - relativedelta(years=1)).strftime("%Y-%m-%d")
    bars_all = load_khdata(code, exchange, freq_in, pre_sdt, edt)
    SIGNALS_CONFIG = [
        {"name": "cxt_first_buy_V221126", "freq": freq_in},
        {"name": "cxt_first_sell_V221126", "freq": freq_in},
        {"name": "cxt_second_bs_V230320", "freq": freq_in},
        {"name": "cxt_third_bs_V230318", "freq": freq_in},
    ]
    df_sig = generate_czsc_signals(bars_all, signals_config=SIGNALS_CONFIG, df=True, sdt=sdt)
    bs_map = {
        "日线_D1B_BUY1": ["一买"], "日线_D1B_SELL1": ["一卖"],
        "日线_D1#SMA#21_BS2辅助V230320": ["二买", "二卖"],
        "日线_D1#SMA#34_BS3辅助V230318": ["三买", "三卖"],
    }
    events = []
    for col, names in bs_map.items():
        if col in df_sig.columns:
            events += parse_bs_events(df_sig, col, names)
    events.sort(key=lambda x: x["dt"])
    print(f"[缠论买卖点]（czsc 信号识别，共 {len(events)} 条）")
    for ev in events:
        print(f"  {ev['name']:<4} {ev['dt']:%Y-%m-%d}  收盘 {ev['price']:.3f}  {ev['desc']}")
    print()

    # ---- 3) 趋势结论 ----
    last_zs = zs_list[-1] if zs_list else None
    lc = bars[-1].close
    if last_zs:
        if lc > last_zs.zg:
            trend = "上涨（位于最近中枢上方）"
        elif lc < last_zs.zd:
            trend = "下跌（跌破最近中枢下沿）"
        else:
            trend = "震荡（位于最近中枢区间内）"
    else:
        trend = "数据不足"
    print(f"[趋势结论] {trend}")
    if last_zs:
        print(f"  最新收盘 {lc:.3f} vs 最近中枢 [{last_zs.zd:.3f}, {last_zs.zg:.3f}]")
    print()
    print("=" * 62)
    print("（以上为 czsc 缠论技术分析参考，不构成投资建议）")

    # ---- 4) HTML 报告 ×2 ----
    ubi = remove_include_all(bars)
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(out_dir, exist_ok=True)
    base = f"czsc_{label.replace('.','_')}_{freq_in}_{edt.replace('-','')}"

    # 报告1：原版
    try:
        out_orig = os.path.join(out_dir, base + "_原版.html")
        render_original(label, freq_in, c, out_orig)
        print(f"\n[HTML] 原版报告：{out_orig}")
    except Exception as e:
        print(f"[HTML] 原版生成失败：{e}")

    # 报告2：结构版
    try:
        out_ech = os.path.join(out_dir, base + "_结构版.html")
        render_echarts(label, freq_in, sdt, edt, c, ubi, zs_list, events, out_ech)
        print(f"[HTML] 结构版报告：{out_ech}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[HTML] 结构版生成失败：{e}")

if __name__ == "__main__":
    main()
