# -*- coding: utf-8 -*-
"""缠论量化逻辑 - 数据模型
每层输入输出严格对应（K线→分型→笔→线段→中枢→走势→背驰→买卖点）
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class KLine:
    """模块1 输入：原始K线；输出：处理后K线（含 elements 原始回溯）"""
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float = 0.0
    elements: list = field(default_factory=list)  # 构成它的原始K线（合并时累积）


@dataclass
class FenXing:
    """模块2 输出：分型"""
    type: str          # 'top' 顶 / 'bottom' 底
    time: datetime
    price: float
    k_index: int       # 处理后K线索引（中K）
    high: float = 0.0  # 中K最高价（用于分型区间/包含判定）
    low: float = 0.0   # 中K最低价

    @property
    def is_top(self):
        return self.type == 'top'


@dataclass
class Bi:
    """模块3 输出：笔"""
    index: int
    direction: str     # 'up' / 'down'
    start_time: datetime
    end_time: datetime
    start_price: float
    end_price: float
    high: float
    low: float
    is_confirmed: bool
    fx_start: FenXing = None
    fx_end: FenXing = None
    bars: list = field(default_factory=list)   # 构成笔的去包含K线（对齐 czsc check_bi）

    @property
    def is_up(self):
        return self.direction == 'up'


@dataclass
class Segment:
    """模块4 输出：线段（次级别为笔）"""
    index: int
    direction: str
    start_time: datetime
    end_time: datetime
    start_price: float
    end_price: float
    high: float
    low: float
    is_confirmed: bool
    bis: list = field(default_factory=list)   # 构成笔

    @property
    def is_up(self):
        return self.direction == 'up'


@dataclass
class ZhongShu:
    """模块5 输出：中枢"""
    index: int
    level: str         # 'stroke' 笔中枢 / 'segment' 线段中枢
    direction: str     # 'up' 上升 / 'down' 下降（由第一单元决定）
    start_time: datetime
    end_time: datetime
    ZD: float          # 下沿 = max(前三单元 low)
    ZG: float          # 上沿 = min(前三单元 high)
    unit_count: int
    status: str        # 'extending' 延伸中 / 'finished' 已终结
    units: list = field(default_factory=list)  # 构成单元（笔或线段）
    gg: float = 0.0    # 最高
    dd: float = 0.0    # 最低

    @property
    def is_up(self):
        return self.direction == 'up'


@dataclass
class Trend:
    """模块6 输出：走势类型"""
    type: str          # 'trend_up' 上涨 / 'trend_down' 下跌 / 'consolidation' 盘整
    level: str
    start_time: datetime
    end_time: datetime
    start_price: float
    end_price: float
    center_list: list = field(default_factory=list)  # 中枢列表

    @property
    def is_trend_up(self):
        return self.type == 'trend_up'

    @property
    def is_trend_down(self):
        return self.type == 'trend_down'


@dataclass
class Beichi:
    """模块7 输出：背驰信号"""
    type: str          # 'top' 顶背驰 / 'bottom' 底背驰
    level: str
    time: datetime
    price: float
    compare_segments: tuple = ()     # (b段描述, c段描述)
    is_confirmed: bool = False
    method: str = 'macd'             # 'macd' / 'price'


@dataclass
class BSPoint:
    """模块8 输出：买卖点"""
    type: str          # '1B' '2B' '3B' '1S' '2S' '3S'
    level: str
    time: datetime
    price: float
    status: str        # 'confirmed' / 'unconfirmed'
    invalid: bool = False
    desc: str = ""
    strength: str = ""   # 二买/二卖强弱：强/弱

    @property
    def is_buy(self):
        return self.type.endswith('B')
