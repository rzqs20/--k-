# -*- coding: utf-8 -*-
"""
筹码结构报告 · 终端交互式生成器

在终端运行：
    python cli_chip.py

流程：
  输入股票代码 → 确认市场 → 显示窗口 → （可选）日期区间 → （可选）算法参数
  → 生成 HTML 报告（可选自动打开浏览器）→ 继续生成下一份 / 退出

依赖：chip_report.ChipReport（算法 chip_distribution.ChipDistribution + KhDataLoader）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chip_report import ChipReport, _infer_exchange

BANNER = """
============================================================
   筹码结构报告生成器（不复权 · 滚动窗口 · 右侧筹码峰联动）
   输入 q 随时退出；括号内为默认值，直接回车采用默认
============================================================
"""


def ask(prompt: str, default: str = "") -> str:
    """带默认值提示的输入。"""
    suffix = f"（默认 {default}）" if default else ""
    try:
        v = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "q"
    return v if v else default


def parse_code(raw: str):
    """解析输入为 (code, exchange)；无法推断返回 (None, None)。"""
    raw = raw.strip().upper()
    if "." in raw:
        code, ex = raw.split(".", 1)
        return code.zfill(6), ex.upper()
    code = raw.zfill(6)
    return code, _infer_exchange(code)


def ask_algorithm():
    """交互式设置算法参数，返回 (window, decay, n_bins)。"""
    print("\n[算法参数] 滚动窗口 window / 每日留存率 decay / 价格分档 n_bins")
    w = ask("  滚动窗口（交易日，默认 250）", "250")
    d = ask("  每日留存率 decay（0~1，默认 0.98）", "0.98")
    b = ask("  价格分档 n_bins（默认 200）", "200")
    try:
        return int(w), float(d), int(b)
    except ValueError:
        print("  参数格式错误，改用默认值 (250, 0.98, 200)")
        return 250, 0.98, 200


def build_report() -> bool:
    """一次完整交互并生成报告。返回 False 表示用户退出。"""
    # 1) 股票代码
    raw = ask("股票代码", "000001")
    if raw.lower() == "q":
        return False
    code, ex = parse_code(raw)
    if not code.isdigit() or len(code) != 6:
        print(f"  代码格式不正确: {raw}，请输入 6 位数字（如 000001 / 600519 / 300750.SZ）")
        return True

    # 2) 市场确认
    ex_in = ask(f"市场（{ex}）", ex).upper()
    if ex_in == "Q":
        return False
    ex = ex_in if ex_in in ("SH", "SZ", "BJ") else ex
    print(f"  → 标的 {code}.{ex}")

    # 3) 显示窗口
    n_in = ask("最近 N 个交易日（0=全部，默认 500）", "500")
    if n_in.lower() == "q":
        return False
    try:
        show_n = int(n_in)
    except ValueError:
        show_n = 500

    # 4) 日期区间（可选）
    sdt = edt = None
    if ask("指定日期区间？(y/n，默认 n)", "n").lower() in ("y", "yes", "是"):
        sdt = ask("  开始日期 YYYY-MM-DD（可留空）")
        if sdt.lower() == "q":
            return False
        edt = ask("  结束日期 YYYY-MM-DD（可留空）")
        if edt.lower() == "q":
            return False
        sdt = sdt or None
        edt = edt or None

    # 5) 算法参数
    window, decay, n_bins = 250, 0.98, 200
    if ask("算法参数用默认值？(y/n，默认 y)", "y").lower() in ("n", "no", "否"):
        window, decay, n_bins = ask_algorithm()

    # 6) 打开浏览器
    open_browser = ask("生成后自动打开浏览器？(y/n，默认 y)", "y").lower() in ("y", "yes", "是")

    # 7) 生成
    print(f"\n  正在生成 {code}.{ex}（最近 {show_n} 日，window={window}，decay={decay}，bins={n_bins}）...")
    try:
        report = ChipReport(code, ex, show_n=show_n, start=sdt, end=edt,
                            window=window, decay=decay, n_bins=n_bins,
                            open_browser=open_browser)
        out = report.generate()
        print(f"  ✓ 完成: {out}")
    except FileNotFoundError as e:
        print(f"  ✗ 数据文件不存在: {e}")
        print("    请确认 khData 目录下存在对应数据库，或股票代码/市场是否正确。")
    except Exception as e:
        print(f"  ✗ 生成失败: {type(e).__name__}: {e}")
        print("    若为数据库被占用（KhQuant 运行中），请稍后重试。")
    return True


def main():
    print(BANNER)
    while True:
        print("-" * 60)
        if not build_report():
            print("\n已退出。")
            break
        again = ask("\n继续生成其他报告？(y/n，默认 n)", "n").lower()
        if again not in ("y", "yes", "是"):
            print("已退出。")
            break


if __name__ == "__main__":
    main()
