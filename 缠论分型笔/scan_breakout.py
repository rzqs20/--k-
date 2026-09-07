# -*- coding: utf-8 -*-
"""
全市场扫描：寻找最新日期处于放量向上突破附近的股票
- 支持断点续传：随时中断，下次自动从断点继续
- 只用日k
- 终止日期：2026-08-05
- 每60只输出一波当前结果
"""
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 日志文件
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "扫描日志.txt")
PROGRESS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "扫描进度.txt")
RESULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "扫描结果_放量向上突破.txt")

_log_f = open(LOG_PATH, "a", encoding="utf-8")

def log(*args, **kwargs):
    msg = " ".join(str(a) for a in args)
    print(msg, **kwargs)
    _log_f.write(msg + "\n")
    _log_f.flush()

from chan_report import load_bars
from core.chan_analyzer import ChanAnalyzer

# ==================== 参数 ====================
END_DATE = datetime(2026, 9, 3)
START_DATE = datetime(2025, 1, 1)
FREQ = "日线"

VOL_PCT_THRESHOLD = 0       # 放量阈值（0=不限制）
MIN_SCORE = 0               # 最低得分（0=不限制）
BREAKOUT_START = datetime(2026, 9, 1)
BREAKOUT_END = datetime(2026, 9, 2)
MIN_BARS = 100
BATCH_SIZE = 60

# ==================== 断点续传 ====================
def load_progress():
    """读取已处理的股票集合"""
    processed = set()
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    processed.add(line)
    return processed

def save_progress(processed):
    """保存已处理的股票集合"""
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        for code in sorted(processed):
            f.write(code + "\n")

def append_result(r):
    """追加结果到结果文件"""
    with open(RESULT_PATH, "a", encoding="utf-8") as f:
        vol_tag = "放量" if r["is_voluminous"] else "无量"
        f.write(f"{r['label']} | 第{r['attempt_count']}次尝试 | "
                f"观察日{r['observe_time'].strftime('%Y-%m-%d') if r['observe_time'] else '-'} | "
                f"突破日{r['breakout_time'].strftime('%Y-%m-%d') if r['breakout_time'] else '-'} | "
                f"观察量{r['observe_vol_pct']:.0f}% | 突破量{r['breakout_vol_pct']:.0f}% | "
                f"{vol_tag} | 得分{r['score']} | 突破后涨跌{r['breakout_pct']:+.2f}% | 距今天数{r['days_from_breakout']}\n")

# ==================== 遍历 ====================
def scan_all():
    db_files = []
    for ex in ("SH", "SZ"):
        ex_dir = os.path.join(r"D:\khData", ex)
        if os.path.exists(ex_dir):
            for f in os.listdir(ex_dir):
                if f.endswith(".db"):
                    code = f.replace(".db", "")
                    db_files.append((code, ex))

    # 断点续传
    processed = load_progress()
    if processed:
        log(f"断点续传：已处理 {len(processed)} 只，继续扫描剩余 {len(db_files) - len(processed)} 只")
    else:
        # 初始化结果文件
        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            f.write(f"全市场扫描：放量向上突破附近股票\n")
            f.write(f"终止日期: {END_DATE.date()}, 周期: {FREQ}\n")
            f.write(f"筛选: 向上突破 + 放量(量能>{VOL_PCT_THRESHOLD}%) + 突破日在{BREAKOUT_START.date()}~{BREAKOUT_END.date()}\n")
            f.write("=" * 90 + "\n\n")

    log(f"共 {len(db_files)} 只股票，已处理 {len(processed)} 只")
    log(f"筛选: 向上突破 + 放量 + 突破日在{BREAKOUT_START.date()}~{BREAKOUT_END.date()}")
    log(f"每{BATCH_SIZE}只输出一波，结果实时追加到 {RESULT_PATH}")
    log("=" * 90)

    results = []
    skipped = 0
    errors = 0
    new_processed = 0
    t0 = time.time()

    def print_batch():
        elapsed = time.time() - t0
        total_processed = len(processed) + new_processed
        log(f"\n--- 进度 {total_processed}/{len(db_files)} ({total_processed*100//len(db_files)}%) | "
              f"本轮用时{elapsed:.0f}s | 本轮命中{len(results)}只 | 跳过{skipped} | 错误{errors} ---")
        if results:
            sorted_r = sorted(results, key=lambda x: x["days_from_breakout"])
            log(f"{'代码':<12} {'第几次':<6} {'观察日':<12} {'突破日':<12} "
                  f"{'观察量%':<8} {'突破量%':<8} {'得分':<4} {'放量':<4} {'突破后涨跌':<10} {'距今天数':<6}")
            log("-" * 90)
            for r in sorted_r[-20:]:
                vol_tag = "是" if r["is_voluminous"] else "否"
                log(f"{r['label']:<12} "
                      f"第{r['attempt_count']}次{'':<2} "
                      f"{r['observe_time'].strftime('%m-%d') if r['observe_time'] else '-':<12} "
                      f"{r['breakout_time'].strftime('%m-%d') if r['breakout_time'] else '-':<12} "
                      f"{r['observe_vol_pct']:.0f}%{'':<5} "
                      f"{r['breakout_vol_pct']:.0f}%{'':<5} "
                      f"{r['score']:<4} "
                      f"{vol_tag:<4} "
                      f"{r['breakout_pct']:+.2f}%{'':<5} "
                      f"{r['days_from_breakout']:<6}")
        log()

    for idx, (code, ex) in enumerate(db_files):
        stock_key = f"{code}.{ex}"
        if stock_key in processed:
            continue

        # 每BATCH_SIZE只输出一次 + 保存进度
        if new_processed > 0 and new_processed % BATCH_SIZE == 0:
            print_batch()
            save_progress(processed)

        try:
            label, bars, prewarm = load_bars(code, ex, FREQ, START_DATE, END_DATE)
            processed.add(stock_key)
            new_processed += 1

            if len(bars) < MIN_BARS:
                skipped += 1
                continue

            ana = ChanAnalyzer(bars, symbol=label, freq=FREQ)
            boxes = ana.find_boxes()
            if not boxes:
                skipped += 1
                continue

            boxes_pct = ana.trend_classifier.calc_box_percentiles(boxes, bars)
            boxes = ana.unified_breakout_analyzer.analyze(boxes_pct, bars, segments=ana.finished_segments)

            for bx in boxes:
                ub = bx.get("unified_breakout", {})
                if not ub.get("success") or ub.get("final_direction") != "up":
                    continue

                success_attempt = None
                for att in ub.get("attempts", []):
                    if att.get("status") == "成功":
                        success_attempt = att
                        break
                if not success_attempt:
                    continue

                bo_time = success_attempt.get("breakout_time")
                if not bo_time or bo_time.date() < BREAKOUT_START.date() or bo_time.date() > BREAKOUT_END.date():
                    continue

                obs_vol_pct = success_attempt.get("observe_vol_pct", 0)
                bo_vol_pct = success_attempt.get("breakout_vol_pct", 0)
                score = success_attempt.get("score", 0)
                is_voluminous = obs_vol_pct >= VOL_PCT_THRESHOLD or bo_vol_pct >= VOL_PCT_THRESHOLD

                if score < MIN_SCORE or not is_voluminous:
                    continue

                days_diff = (END_DATE - bo_time).days
                r = {
                    "label": label,
                    "attempt_count": ub.get("attempt_count", 1),
                    "observe_time": success_attempt.get("observe_time"),
                    "breakout_time": bo_time,
                    "observe_vol_pct": obs_vol_pct,
                    "breakout_vol_pct": bo_vol_pct,
                    "score": score,
                    "is_voluminous": is_voluminous,
                    "breakout_pct": ub.get("final_breakout_pct", 0),
                    "days_from_breakout": days_diff,
                }
                results.append(r)
                append_result(r)  # 实时追加到结果文件
                break

        except Exception:
            errors += 1
            continue

    # 最终输出
    print_batch()
    save_progress(processed)

    elapsed = time.time() - t0
    total_processed = len(processed)
    log("=" * 90)
    log(f"扫描完成！本轮用时 {elapsed:.0f}s，累计处理 {total_processed}/{len(db_files)}")
    log(f"本轮命中: {len(results)} 只，结果已保存到: {RESULT_PATH}")

    if total_processed >= len(db_files):
        log("全部扫描完成！可以删除 扫描进度.txt 重新开始")

    return results


if __name__ == "__main__":
    scan_all()

