# -*- coding: utf-8 -*-
"""
缠论 · 增量箱体识别 报告生成（命令行入口）
使用 IncrementalBoxFinder 增量算法，箱体确认后锁定，不随后续数据变化。
用法: python chan_incremental.py 000301.SZ 日线 2024-01-01 2026-09-02
"""
import sys
import os

from chan_report import load_bars, resolve_symbol, _parse_date, FREQ_ALIASES
from core.chan_analyzer import ChanAnalyzer
from core.box_finder import IncrementalBoxFinder
from core.report_renderer import ReportRenderer


def main():
    args = sys.argv[1:]
    if len(args) >= 4:
        code_in, freq_in, sdt_in, edt_in = args[:4]
        auto_mode = True
    else:
        auto_mode = False
        print("=" * 64)
        print("      缠论 · 增量箱体识别 报告程序（IncrementalBoxFinder）")
        print("=" * 64)
        print("数据源：D:\\khData（DuckDB）")
        print("算法：滚动窗口阈值 + 确认锁定，箱体一旦确认不随后续数据变化")
        print("支持周期：1分钟 / 5分钟 / 15分钟 / 30分钟 / 60分钟 / 120分钟 / 日线 / 周线 / 月线")
        print("示例：python chan_incremental.py 000301.SZ 日线 2024-01-01 2026-09-02")
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

    freq = FREQ_ALIASES.get(freq_in, freq_in)
    sdt = _parse_date(sdt_in)
    edt = _parse_date(edt_in)

    try:
        code, exchange = resolve_symbol(code_in)
        label, bars, prewarm = load_bars(code, exchange, freq, sdt, edt)
    except Exception as e:
        print(f"[错误] {e}")
        if not auto_mode:
            input("\n按回车退出...")
        return

    # 使用增量算法
    box_finder = IncrementalBoxFinder(window_size=20)
    ana = ChanAnalyzer(bars, symbol=label, freq=freq, box_finder=box_finder, start_dt=sdt)
    renderer = ReportRenderer(ana)

    # 终端输出
    renderer.print_terminal(sdt=sdt, edt=edt, prewarm=prewarm)

    # HTML 报告（文件名加增量标识）
    out_path = renderer.render_html(sdt=sdt, edt=edt, prewarm=prewarm)
    # 重命名为增量标识
    base, ext = os.path.splitext(out_path)
    new_path = base + "_增量" + ext
    try:
        os.rename(out_path, new_path)
        out_path = new_path
    except OSError:
        pass

    print("-" * 64)
    print(f"[HTML] 增量算法报告已生成：{out_path}")

    if not auto_mode:
        input("\n按回车退出...")


if __name__ == "__main__":
    main()
