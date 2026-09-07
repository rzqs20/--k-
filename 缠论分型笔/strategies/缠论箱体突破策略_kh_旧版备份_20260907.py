# coding: utf-8
"""
策略名称：缠论箱体突破策略
策略说明：
- 买入：箱体向上突破（突破GG，放量确认）
- 卖出：突破后出现的第一个顶分型（T日确认T-1日顶分型，T日卖出）
- 无未来函数：所有判断基于截至当前日期的数据
"""
from khQuantImport import *
import sys
import os
import logging
from datetime import datetime

# ==================== 实时日志配置 ====================
LOG_FILE = r"D:\量化k线\缠论分型笔\回测实时日志.txt"
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

# ==================== 策略参数 ====================
params = {
    'min_score': 2,
    'vol_pct_threshold': 50,
    'position_ratio': 0.2,
    'max_positions': 5,
    'lookback_days': 150,
}

# ==================== 全局状态 ====================
g = {
    'breakout_signals': {},
    'sell_signals': {},
    'last_calc_date': {},
    'buy_records': {},
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


def _calc_breakouts(sc, dn):
    """计算截至dn日的所有向上突破信号和卖出信号"""
    try:
        hist = khHistory(sc, ["open", "high", "low", "close", "amount"],
                         params['lookback_days'], "1d", dn, fq="pre")
        if not hist or sc not in hist:
            return [], []

        df = hist[sc]
        if len(df) < 100:
            return [], []

        # 用RawBar创建（和chan_report.py一致）
        bars = []
        for i, (idx, row) in enumerate(df.iterrows()):
            dt = _to_datetime(idx)
            amount = float(row['amount']) if 'amount' in row else 0
            bar = RawBar(
                symbol=sc, dt=dt,
                open=float(row['open']), close=float(row['close']),
                high=float(row['high']), low=float(row['low']),
                vol=amount, amount=amount, id=i, freq="1d",
            )
            bars.append(bar)

        ana = ChanAnalyzer(bars, symbol=sc, freq="日线")
        boxes = ana.find_boxes()
        if not boxes:
            return [], []

        boxes_pct = ana.trend_classifier.calc_box_percentiles(boxes, bars)
        boxes = ana.unified_breakout_analyzer.analyze(boxes_pct, bars, segments=ana.finished_segments)

        # 提取向上突破信号
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

        sells = sell_gen.generate_signals(bars, breakouts, ana.fxs)
        return breakouts, sells

    except Exception as e:
        logging.warning(f"{sc} 计算突破信号失败: {e}")
        return [], []


# ==================== 策略入口 ====================
def init(stocks=None, data=None):
    log("=" * 60)
    log("缠论箱体突破策略启动")
    log(f"参数: 最低得分={params['min_score']}, 放量阈值={params['vol_pct_threshold']}%")
    log(f"单只仓位={params['position_ratio']}, 最大持仓={params['max_positions']}")
    log(f"实时日志: {LOG_FILE}")
    log("=" * 60)


def khHandlebar(data: Dict) -> List[Dict]:
    signals = []
    dn = khGet(data, "date_num")
    current_date = _dn_to_date(dn)

    for sc in khGet(data, "stocks"):
        if sc not in g['last_calc_date'] or g['last_calc_date'][sc] != dn:
            breakouts, sells = _calc_breakouts(sc, dn)
            g['breakout_signals'][sc] = breakouts
            g['sell_signals'][sc] = sells
            g['last_calc_date'][sc] = dn

        breakouts = g['breakout_signals'].get(sc, [])
        sells = g['sell_signals'].get(sc, [])
        current_price = khPrice(data, sc, "open")
        has_position = khHas(data, sc)

        # 卖出判断
        if has_position:
            for sell in sells:
                sell_time = sell.get("sell_time")
                if sell_time and hasattr(sell_time, 'date') and sell_time.date() == current_date:
                    top_fx = sell.get('top_fx_time')
                    top_fx_str = top_fx.strftime('%m-%d') if top_fx else '未知'
                    reason = f"顶分型卖出({top_fx_str})，持有{sell.get('hold_days', 0)}天，收益{sell.get('return_pct', 0):.2f}%"
                    signals.extend(generate_signal(data, sc, current_price, 1.0, 'sell', reason))
                    log(f"[卖出] {sc} | {current_date} | 价格{current_price:.2f} | {reason}")
                    if sc in g['buy_records']:
                        del g['buy_records'][sc]
                    break

        # 买入判断
        if not has_position and len(g['buy_records']) < params['max_positions']:
            for bo in breakouts:
                bo_time = bo.get("breakout_time")
                if bo_time and hasattr(bo_time, 'date') and bo_time.date() == current_date:
                    reason = f"箱体向上突破，得分{bo['score']}，观察量{bo['observe_vol_pct']:.0f}%，突破量{bo['breakout_vol_pct']:.0f}%"
                    signals.extend(generate_signal(data, sc, current_price, params['position_ratio'], 'buy', reason))
                    g['buy_records'][sc] = {"buy_time": bo_time, "buy_price": current_price}
                    log(f"[买入] {sc} | {current_date} | 价格{current_price:.2f} | {reason}")
                    break

    if signals:
        log(f"--- {current_date} 产生{len(signals)}个信号 ---")

    return signals
