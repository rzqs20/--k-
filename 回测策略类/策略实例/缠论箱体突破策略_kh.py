# coding: utf-8
"""
策略名称：缠论箱体突破策略（T+1 增量状态机版 · pending 队列）
策略说明：
- 信号日 W = 数据窗口最后一天（KhQuant 回测触发时含当日K线 → W=今天；不含时 → W=昨天）
- 买入：W 日收盘确认箱体向上突破（突破GG，得分达标，放量确认）→ W+1 交易日开盘买入
- 卖出：持仓对应突破后的第一个顶分型，W 日确认 → W+1 交易日开盘卖出
- 通过 pending 队列在信号日确认、下一交易日执行，兼容"含当日/不含当日"两种引擎语义，
  保证真 T+1、无未来函数、无当日"买→卖"抖动
- 持仓绑定突破日(breakout_time)，卖出信号只匹配自己的持仓

修复记录：
1.（旧版→T+1版）买入由"突破日==今天"改为"突破日==窗口最后一天"；卖出与持仓一一绑定；
   去掉"未出现顶分型持有到最后"兜底；补 typing 导入
2.（T+1版→pending版）KhQuant 回测触发时窗口含当日K线（09:30 触发、当日收盘数据已可用），
   "窗口最后一天==信号日"会坍缩成"当日确认当日执行"→ 每天卖+买抖动。
   改为：信号日确认的事件入 pending 队列，下一交易日开盘统一执行
"""
from typing import Dict, List
from khQuantImport import *
import sys
import os
import logging
import bisect
from datetime import datetime, timedelta

# ==================== 实时日志配置 ====================
LOG_FILE = r"D:\量化k线\回测策略类\回测实时日志.txt"
_file_handler = None

def _setup_logging():
    global _file_handler
    if _file_handler is None:
        _file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
        _file_handler.setLevel(logging.INFO)
        _file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
        logging.getLogger().addHandler(_file_handler)
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(f"=== 回测实时日志启动 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")

_setup_logging()

def log(msg):
    logging.info(msg)
    print(msg, flush=True)

# ==================== 加载缠论模块（参考chan_report.py的正确方式） ====================
CHAN_PATH = r"D:\量化k线\缠论分型笔"
sys.path.insert(0, CHAN_PATH)

import importlib.util as _ilu

def _load_chan_module():
    """加载分型+笔模块，先注册到sys.modules供dataclass解析"""
    for name in ("chan_fx_bi.py", "分型+笔.py"):
        path = os.path.join(CHAN_PATH, name)
        if os.path.exists(path):
            spec = _ilu.spec_from_file_location("chan_fx_bi", path)
            mod = _ilu.module_from_spec(spec)
            sys.modules["chan_fx_bi"] = mod  # 关键：先注册，dataclass才能解析类型
            spec.loader.exec_module(mod)
            return mod
    raise ImportError("未找到 分型+笔.py")

cb = _load_chan_module()
RawBar = cb.RawBar

from core.chan_analyzer import ChanAnalyzer
from core.sell_signal_generator import SellSignalGenerator
from core.box_finder import IncrementalBoxFinder

# ==================== 策略参数 ====================
params = {
    'min_score': 2,
    'vol_pct_threshold': 50,
    'position_ratio': 0.2,
    'max_positions': 5,
    'lookback_days': 150,
}

# ==================== 全局状态 ====================
# 说明：KhQuant 回测触发时窗口含当日K线（当日收盘数据可用），故采用「信号日确认 → 下一交易日执行」的 pending 机制：
#   - 信号日 W = 窗口最后一天（含当日时为今天）
#   - W 日收盘确认的突破/顶分型 → 记入 pending → W 的下一个交易日开盘执行
# 这样无论引擎是否提供当日K线，都能保证真正的 T+1，无未来函数、无当日抖动。
g = {
    'positions': {},       # sc -> {"breakout_time", "buy_price", "buy_date", ...}
    'pending_buy': {},     # sc -> {"breakout_time", "score", "observe_vol_pct", "breakout_vol_pct"}  W日确认，待W+1买入
    'pending_sell': {},    # sc -> {"top_fx_time"}  W日确认，待W+1卖出
    'bars': {},            # sc -> 当日分析用bars（窗口截至dn）
    'breakouts': {},       # sc -> 当日分析出的达标向上突破
    'fxs': {},             # sc -> 当日分析出的分型
    'last_calc_date': {},  # sc -> 最后计算日期，每日只算一次
    'last_w': {},          # sc -> 上次已处理的信号日（窗口最后一天），防止重复入队
}
sell_gen = SellSignalGenerator()


def _dn_to_date(dn):
    """date_num(20260901) → datetime.date"""
    if isinstance(dn, (int, float)):
        s = str(int(dn))
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8])).date()
    if isinstance(dn, str):
        return datetime.strptime(dn[:8], "%Y%m%d").date()
    if hasattr(dn, 'date'):
        return dn.date()
    return dn


def _to_datetime(val):
    """统一转换为datetime"""
    if hasattr(val, 'to_pydatetime'):
        return val.to_pydatetime()
    if hasattr(val, 'item'):  # numpy datetime64 / 其他可 item() 类型
        try:
            inner = val.item()
            if isinstance(inner, (int, float)) and not isinstance(val, (datetime,)):
                ts = inner
                if abs(ts) > 10 ** 14:      # 纳秒
                    ts = ts / 1e9
                elif abs(ts) > 10 ** 11:    # 微秒
                    ts = ts / 1e6
                elif abs(ts) > 10 ** 8:     # 毫秒
                    ts = ts / 1e3
                return datetime(1970, 1, 1) + timedelta(seconds=ts)
            return _to_datetime(inner)
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(val[:19], fmt)
            except ValueError:
                continue
    if isinstance(val, (int, float)):
        s = str(int(val))
        if len(s) == 8:
            return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return datetime.fromtimestamp(val)
    if hasattr(val, 'year'):
        return datetime.combine(val, datetime.min.time())
    return datetime.now()


def _row_datetime(row, idx):
    """优先从 khHistory 返回的 time 列取K线日期（KhQuant 的 DataFrame 索引是 int 序号，
    日期在 time 列中；旧版从索引取日期会把 int 误解析成 1970 时间戳）。"""
    try:
        t = row.get('time')
        if t is not None:
            import pandas as _pd
            if isinstance(t, _pd.Timestamp) or hasattr(t, 'to_pydatetime') or isinstance(t, datetime):
                return _to_datetime(t)
            if isinstance(t, str) and t.strip():
                return _to_datetime(t)
            if hasattr(t, 'item'):  # numpy datetime64
                return _to_datetime(t)
    except Exception:
        pass
    return _to_datetime(idx)  # 兜底：索引（mock/旧数据源为 datetime 索引时）


def _analyze(sc, dn):
    """加载截至dn的 lookback_days 根日线并做箱体突破分析。
    返回 (bars, breakouts, fxs)；数据不足或异常时 bars 为 None。
    breakouts: 达标（得分+放量）的成功向上突破列表，含 breakout_time/observe_time/score/vol
    fxs: 笔端点分型（含顶分型 mark='G'）
    """
    try:
        hist = khHistory(sc, ["open", "high", "low", "close", "amount"],
                         params['lookback_days'], "1d", dn, fq="pre")
        if not hist or sc not in hist:
            return None, [], []

        df = hist[sc]
        if len(df) < 100:
            return None, [], []

        bars = []
        for i, (idx, row) in enumerate(df.iterrows()):
            dt = _row_datetime(row, idx)
            amount = float(row['amount']) if 'amount' in row else 0
            bar = RawBar(
                symbol=sc, dt=dt,
                open=float(row['open']), close=float(row['close']),
                high=float(row['high']), low=float(row['low']),
                vol=amount, amount=amount, id=i, freq="1d",
            )
            bars.append(bar)

        # 增量箱体识别（滚动窗口阈值 + 确认锁定，箱体确认后不随后续数据变化；
        # 与 chan_incremental.py 的 IncrementalBoxFinder 同一算法，window_size=20）
        ana = ChanAnalyzer(bars, symbol=sc, freq="日线",
                           box_finder=IncrementalBoxFinder(window_size=20))
        boxes = ana.find_boxes()
        if not boxes:
            return bars, [], ana.fxs

        boxes_pct = ana.trend_classifier.calc_box_percentiles(boxes, bars)
        boxes = ana.unified_breakout_analyzer.analyze(boxes_pct, bars, segments=ana.finished_segments)

        # 提取达标的向上突破
        breakouts = []
        for bx in boxes:
            ub = bx.get("unified_breakout", {})
            if not ub.get("success") or ub.get("final_direction") != "up":
                continue
            for att in ub.get("attempts", []):
                if att.get("status") != "成功":
                    continue
                score = att.get("score", 0)
                obs_vol = att.get("observe_vol_pct", 0)
                bo_vol = att.get("breakout_vol_pct", 0)
                is_vol = obs_vol >= params['vol_pct_threshold'] or bo_vol >= params['vol_pct_threshold']
                if score < params['min_score'] or not is_vol:
                    continue
                breakouts.append({
                    "breakout_time": _to_datetime(att.get("breakout_time")),
                    "observe_time": _to_datetime(att.get("observe_time")),
                    "score": score,
                    "observe_vol_pct": obs_vol,
                    "breakout_vol_pct": bo_vol,
                })

        return bars, breakouts, ana.fxs

    except Exception as e:
        logging.warning(f"{sc} 计算突破信号失败: {e}")
        return None, [], []


def _calc_breakouts(sc, dn):
    """兼容旧接口：返回 (breakouts, sells)，供外部诊断/旧调用使用"""
    bars, breakouts, fxs = _analyze(sc, dn)
    if bars is None:
        return [], []
    sells = sell_gen.generate_signals(bars, breakouts, fxs)
    return breakouts, sells


def _first_top_fx(bars, fxs, bo_time):
    """持仓对应突破后的第一个顶分型（mark='G' 且 fx.dt > bo_time）。
    返回 (fx, confirm_date)：
      confirm_date = 该分型完整确认日的 date（= 顶分型中间K线的右侧K线日期），
                     未确认（右侧K线不在窗口内）时返回 None
    """
    dts = [b.dt for b in bars]
    for fx in fxs:
        if fx.mark != "G":
            continue
        if fx.dt <= bo_time:
            continue
        fx_idx = bisect.bisect_right(dts, fx.dt) - 1
        if fx_idx + 1 < len(bars):
            return fx, bars[fx_idx + 1].dt.date()
        return fx, None  # 分型位于窗口最末，尚未完整确认
    return None, None  # 突破后尚无顶分型，继续持有


# ==================== 策略入口 ====================
def init(stocks=None, data=None):
    log("=" * 60)
    log("缠论箱体突破策略启动（T+1 增量状态机版）")
    log(f"参数: 最低得分={params['min_score']}, 放量阈值={params['vol_pct_threshold']}%")
    log(f"单只仓位={params['position_ratio']}, 最大持仓={params['max_positions']}")
    log(f"实时日志: {LOG_FILE}")
    log("=" * 60)


def khHandlebar(data: Dict) -> List[Dict]:
    signals = []
    dn = khGet(data, "date_num")
    current_date = _dn_to_date(dn)

    for sc in khGet(data, "stocks"):
        # 每日每只股票只分析一次
        if sc not in g['last_calc_date'] or g['last_calc_date'][sc] != dn:
            bars, breakouts, fxs = _analyze(sc, dn)
            g['bars'][sc] = bars
            g['breakouts'][sc] = breakouts
            g['fxs'][sc] = fxs
            g['last_calc_date'][sc] = dn

        bars = g['bars'].get(sc)
        breakouts = g['breakouts'].get(sc, [])
        fxs = g['fxs'].get(sc, [])
        if not bars or len(bars) < 100:
            continue

        # 信号日 W = 窗口最后一天（KhQuant 的 khHistory 不含当日 → W=上一交易日）
        last_day = bars[-1].dt.date()
        current_price = khPrice(data, sc, "open")
        if not current_price:
            continue  # 当日停牌/无行情（khPrice 返回 0.0 或 None），跳过交易（pending 保留，复牌日再执行）

        # ==================== 1. 执行 W-1 日确认的待办（今日开盘执行 = 真 T+1） ====================
        # 1a. 卖出：昨日确认顶分型 → 今日卖出
        if sc in g['pending_sell']:
            if sc in g['positions']:
                pos = g['positions'][sc]
                ret = (current_price - pos['buy_price']) / pos['buy_price'] * 100
                hold_days = (current_date - pos['buy_date']).days
                top_str = g['pending_sell'][sc]['top_fx_time'].strftime('%m-%d')
                reason = f"顶分型卖出({top_str})，持有{hold_days}天，收益{ret:.2f}%"
                signals.extend(generate_signal(data, sc, current_price, 1.0, 'sell', reason))
                log(f"[卖出] {sc} | {current_date} | 价格{current_price:.2f} | {reason}")
                del g['positions'][sc]
            del g['pending_sell'][sc]

        # 1b. 买入：昨日确认突破 → 今日买入
        if sc in g['pending_buy']:
            if sc not in g['positions'] and len(g['positions']) < params['max_positions']:
                pb = g['pending_buy'][sc]
                reason = (f"T+1买入：{pb['breakout_time'].date()}突破GG，得分{pb['score']}，"
                          f"观察量{pb['observe_vol_pct']:.0f}%，突破量{pb['breakout_vol_pct']:.0f}%")
                signals.extend(generate_signal(data, sc, current_price, params['position_ratio'], 'buy', reason))
                g['positions'][sc] = {
                    "breakout_time": pb['breakout_time'],
                    "buy_price": current_price,
                    "buy_date": current_date,
                    "score": pb['score'],
                    "observe_vol_pct": pb['observe_vol_pct'],
                    "breakout_vol_pct": pb['breakout_vol_pct'],
                }
                log(f"[买入] {sc} | {current_date} | 价格{current_price:.2f} | {reason}")
            del g['pending_buy'][sc]

        # ==================== 2. 识别 W 日新事件（窗口前进时）→ 记入 pending，W+1 执行 ====================
        if g['last_w'].get(sc) != last_day:
            g['last_w'][sc] = last_day

            # 2a. W 日收盘确认新突破（未持仓时）→ 明日买入
            if sc not in g['positions']:
                for bo in breakouts:
                    bo_time = bo.get("breakout_time")
                    if bo_time and bo_time.date() == last_day:
                        g['pending_buy'][sc] = {
                            "breakout_time": bo_time,
                            "score": bo['score'],
                            "observe_vol_pct": bo['observe_vol_pct'],
                            "breakout_vol_pct": bo['breakout_vol_pct'],
                        }
                        break

            # 2b. W 日收盘确认顶分型（持仓对应突破后的第一个顶分型）→ 明日卖出
            if sc in g['positions']:
                fx, confirm_day = _first_top_fx(bars, fxs, g['positions'][sc]['breakout_time'])
                if fx and confirm_day == last_day:
                    g['pending_sell'][sc] = {"top_fx_time": fx.dt}

    if signals:
        log(f"--- {current_date} 产生{len(signals)}个信号 ---")

    return signals
