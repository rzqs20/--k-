# -*- coding: utf-8 -*-
"""缠论量化逻辑 - 主入口（模块1-8 全链路）

用法：
  python main.py                              # 交互模式
  python main.py 601088.SH 日线 2023-01-01 2026-08-24
  python main.py 601088.SH 日线 2023-01-01 2026-08-24 --level segment
  python main.py 601088.SH 日线 2023-01-01 2026-08-24 --html out.html
"""
import sys
import os

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

import data_loader
from chan.pipeline import run_pipeline
from chan import config
import render


def _print_report(symbol, freq, sdt, edt, raw, result, prewarm, level):
    line = "=" * 66
    sub = "-" * 66
    print()
    print(line)
    print("                  缠 论 量 化 分 析 报 告（模块1-8）")
    print(line)
    klines = result['klines_processed']
    print(f"标的：{symbol}  周期：{freq}  区间：{sdt.date()} ~ {edt.date()}")
    print(f"K线：{len(raw)} 根（处理后 {len(klines)}，含 {prewarm} 预热）  中枢级别：{level}")
    print(sub)

    bis = result['bis']
    up = sum(1 for b in bis if b.is_up)
    print("[结构]")
    print(f"  分型：{len(result['fxs'])} 个")
    print(f"  笔：{len(bis)} 笔（向上 {up} / 向下 {len(bis)-up}）")
    if result['segments']:
        print(f"  线段：{len(result['segments'])} 条")
    print(f"  中枢：{len(result['zhongshu'])} 个")
    for i, z in enumerate(result['zhongshu']):
        d = "上升" if z.is_up else "下降"
        print(f"    中枢{i+1}: {d} [{z.ZD:.3f}, {z.ZG:.3f}] {z.start_time:%Y-%m-%d}~{z.end_time:%Y-%m-%d} {z.unit_count}单元")
    print(sub)

    print("[走势类型]")
    for t in result['trends']:
        name = {"trend_up": "上涨趋势", "trend_down": "下跌趋势", "consolidation": "盘整"}[t.type]
        print(f"  {name}  {t.start_time:%Y-%m-%d}~{t.end_time:%Y-%m-%d}  {len(t.center_list)}中枢")
    print(sub)

    print("[背驰]")
    if result['beichis']:
        for b in result['beichis']:
            print(f"  {'顶' if b.type=='top' else '底'}背驰 {b.time:%Y-%m-%d} 价{b.price:.3f} ({b.method})")
    else:
        print("  无")
    print(sub)

    print("[买卖点]")
    if result['bs_points']:
        for p in result['bs_points']:
            cn = {"1B": "一买", "2B": "二买", "3B": "三买", "1S": "一卖", "2S": "二卖", "3S": "三卖"}[p.type]
            tag = "失效" if p.invalid else ("已确认" if p.status == "confirmed" else "待确认")
            print(f"  {cn}  {p.time:%Y-%m-%d}  价格 {p.price:.3f}  [{tag}]  {p.desc}")
    else:
        print("  无")
    print(line)


def main():
    args = sys.argv[1:]
    level = "stroke"
    html_path = None
    # 解析 --level / --html
    if "--level" in args:
        i = args.index("--level")
        level = args[i + 1]
        args = args[:i] + args[i + 2:]
    if "--html" in args:
        i = args.index("--html")
        html_path = args[i + 1]
        args = args[:i] + args[i + 2:]

    if len(args) >= 4:
        code_in, freq_in, sdt_in, edt_in = args[:4]
    else:
        print("=" * 66)
        print("             缠论量化分析程序（模块1-8 全链路）")
        print("=" * 66)
        print("数据源：D:\khData（DuckDB）")
        print("支持周期：1/5/15/30/60/120分钟、日线、周线、月线")
        print("示例：601088.SH 日线 2023-01-01 2026-08-24")
        print("输入 q 退出")
        print("-" * 66)
        code_in = input("股票代码：").strip()
        if code_in.lower() in ("q", "quit", "exit"):
            return
        freq_in = input("周期级别：").strip()
        sdt_in = input("起始日期（YYYY-MM-DD）：").strip()
        edt_in = input("终止日期：").strip()

    try:
        symbol, freq, klines, prewarm = data_loader.load_bars(code_in, freq_in, sdt_in, edt_in)
        result = run_pipeline(klines, level=level)
        sdt = data_loader._parse_date(sdt_in)
        edt = data_loader._parse_date(edt_in)
        _print_report(symbol, freq, sdt, edt, klines, result, prewarm, level)

        if html_path:
            render.render_html(html_path, symbol, freq, sdt, edt, klines, result, prewarm)
            print(f"[HTML] 已生成：{html_path}")
        else:
            out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
            os.makedirs(out_dir, exist_ok=True)
            fn = "%s_%s_%s_%s.html" % (symbol.replace(".", "_"), freq, level, edt.strftime("%Y%m%d"))
            out = os.path.join(out_dir, fn)
            render.render_html(out, symbol, freq, sdt, edt, klines, result, prewarm)
            print(f"[HTML] 报告已生成：{out}")
            try:
                import webbrowser
                webbrowser.open("file:///" + out.replace("\\", "/"))
            except Exception:
                pass
    except Exception as e:
        print(f"[错误] {e}")
        return


if __name__ == "__main__":
    main()
