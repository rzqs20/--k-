# 回测策略类 —— 职责分工、目录说明与框架理解

> 本文档面向**所有协作智能体**，重点在第三节「对当前量化框架的理解」。
> 本文件夹归**回测策略编写智能体**（以下称"策略智能体"）管理。

---

## 1. 这个文件夹负责什么

**一句话：把算法智能体优化好的算法，按 KhQuant 回测框架写成可直接运行的策略，并在本地验证后部署回测。**

### 职责边界（多智能体分工）

| 角色 | 负责 | 不负责 |
|---|---|---|
| **算法智能体** | 优化缠论核心算法（分型/笔/箱体/突破/趋势），产出在 `D:\量化k线\缠论分型笔\core\`、`分型+笔.py`、`chan_report.py` | 写 KhQuant 策略、管回测配置 |
| **策略智能体（本文件夹）** | 把算法封装成 KhQuant 策略（`khHandlebar` 入口）、回测配置、本地验证、部署 | 改算法本身的数学逻辑 |
| **用户** | 在 KhQuant GUI 跑回测、看报告、给反馈 | — |

### 标准工作流

```
算法智能体 优化 core/ 算法（保证接口稳定）
   ↓
策略智能体 适配进策略（只改策略层，如 _analyze 的组装）
   ↓
策略智能体 本地验证（test_drive_strategy.py 回归，Python310）
   ↓
策略智能体 部署到 KhQuant 运行目录（复制 + 清 pyc）
   ↓
用户 重启 KhQuant → 跑回测 → 看结果
   ↓
反馈 → 迭代
```

### 关键路径（所有智能体都要知道）

| 用途 | 路径 |
|---|---|
| 算法源码（其他智能体管理） | `D:\量化k线\缠论分型笔\`（`core\`、`分型+笔.py`、`chan_report.py`） |
| **策略运行原件（本文件夹管理）** | `D:\量化k线\回测策略类\策略实例\缠论箱体突破策略_kh.py`（2026-09-09 起从 `缠论分型笔\strategies\` 迁移至此，本目录即原件，不再是副本） |
| **KhQuant 运行目录副本** | `C:\Users\xyz\AppData\Local\KhQuant\strategies\缠论箱体突破策略_kh.py`（真机回测加载这份，改原件后需重新覆盖） |
| 回测配置 | `D:\量化k线\回测策略类\策略实例\缠论箱体突破策略_kh.kh` |
| 回测结果 | `C:\Users\xyz\AppData\Local\KhQuant\backtest_results\strategy_*_<时间戳>\`（trades.csv / summary.csv / daily_stats.csv / config.csv） |
| 策略实时日志 | `D:\量化k线\回测策略类\回测实时日志.txt`（策略 LOG_FILE 指向此处；KhQuant 重启后新回测写这份，诊断信号用） |
| KhQuant 源码 | `D:\看海源码\CSkhQuant-main\`（只读；本文件夹 `框架源码\` 有副本） |
| 本地数据 | `D:\khData\`（DuckDB，SH/SZ 各一个 .db，日线/分钟线） |
| 本机 Python | **`C:\Users\xyz\AppData\Local\Programs\Python\Python310\python.exe`**（有 pandas 2.3.3 + duckdb；系统 PATH 的 python 不可用） |

---

## 2. 目录内容

| 文件 | 用途 | 备注 |
|---|---|---|
| `README.md` | 本文件：分工 + 框架理解 | 新智能体先读这个 |
| `核心接口速查.md` | KhQuant 关键 API 的签名/语义/源码行号 | 写策略前必读 |
| `看海策略编写规则.md` | KhQuant 官方策略 API 规范（init/khHandlebar/khGet/khPrice/khHistory/khHas/generate_signal/khMA） | 用户提供的规则原件 |
| `策略实例\` | **具体策略及配套 py 文件的集中地**（新增策略在此新增子目录或平铺） | 当前含：缠论箱体突破策略_kh.py / .kh / test_drive_strategy.py / debug_sell_688036.py / 两个历史备份 / 看海策略编写规则.md |
| `策略实例\缠论箱体突破策略_kh.py` | 当前策略（**运行原件，直接改这份**） | 改完需同步覆盖 KhQuant 运行目录副本 + 清 pycache |
| `策略实例\缠论箱体突破策略_kh.kh` | 回测配置示例（触发/股票池/资金/滑点/佣金） | 新策略照此结构写 .kh |
| `策略实例\test_drive_strategy.py` | 本地验证驱动：mock khQuantImport + 真实数据逐日驱动策略 | 部署前必须回归；STRAT_PATH 已指向本目录策略 |
| `策略实例\debug_sell_688036.py` | 卖出信号卡死问题调试脚本（探针日打印识别三要素） | 修复 `_first_top_fx` bug 时用 |
| `策略实例\*备份_20260907.py` | 历史版本快照（旧版/pending 版） | 仅存档，勿改 |
| `回测实时日志.txt` | KhQuant 回测实时日志（策略 LOG_FILE 落盘） | 用户习惯查看此文件 |
| `框架源码\` | KhQuant 回测引擎源码只读副本 | khQTTools.py / khQuantImport.py / khFrame.py |

> 注意：本文件夹是**策略工作区 + 参考库**，不存放算法源码（`core\` 等归算法智能体，放 `D:\量化k线\缠论分型笔\`）。策略通过 `sys.path` 引用 `D:\量化k线\缠论分型笔` 下的算法模块，避免双份代码漂移。

---

## 3. 我对当前量化框架的理解（重点）

### 3.1 回测引擎：KhQuant 的运转机制

#### 3.1.1 触发机制（重要，决定信号时间语义）

- `.kh` 配置里 `trigger.type = "1d"` → 走 `KLineTrigger`（khFrame.py:1115），**每个交易日触发一次**（`last_trigger_date != current_date` 才触发）。
- `custom_times` / `interval` 字段**只对 `type="custom"` 生效**，对 `"1d"` 无效——不要误以为 09:30 定时触发、更不是每 5 分钟触发。
- 每次触发调用一次 `strategy_module.khHandlebar(data)`（khFrame.py:2214），返回的信号列表交给 `trade_mgr.process_signals` 撮合。

#### 3.1.2 传入策略的 data 结构（khFrame.py:2156-2171）

```python
data = {
    "__current_time__": {"date": "2025-01-03", "time": "09:30:00", "datetime": "...", "timestamp": ..., "_dt": datetime},
    "__stock_list__":   [全部股票池代码],          # khGet(data,"stocks")
    "__positions__":    {持仓信息},                 # khGet(data,"positions")
    "__account__":      {"cash":..., "market_value":..., "total_asset":...},
    "000001.SZ":        <当日行情数据>,              # khPrice 从这里取
    "__framework__":    <框架实例>,
}
```

- **`khGet(data, "date_num")` 返回字符串**（如 `"20250103"`），不是 int。
- **`khGet(data, "stocks")` 返回整个股票池**，策略需自己循环处理。

#### 3.1.3 历史数据 khHistory（本项目最关键的坑点）

```python
hist = khHistory(sc, fields, count, freq, dn, fq="pre")
# 返回 {"000001.SZ": DataFrame}
```

**源码实证（khQTTools.py ~4597 行）：**
- 返回的 DataFrame **索引是 int（RangeIndex 0,1,2…）**，**真实日期在 `time` 列**。
- **数据不包含 current_time（dn）当天** → 窗口最后一天 = **上一交易日**。策略里"信号日 W = bars[-1] 的日期 = 上一交易日"。
- `fq='pre'` → 字段映射为 `open_front/high_front/low_front/close_front`（前复权）。
- `period '1d'` 即日线；回测中走 DuckDB 数据源（`D:\khData`），引擎内置缓存。

**给策略的硬性要求：取K线日期必须从 `row['time']` 解析，绝不能从 int 索引解析。**
（历史教训：把 int 索引当 Unix 时间戳 → 所有日期变 1970-01-01 → 买入判定恒真、卖出判定恒假 → "首日买满、永不卖出"。修复参考 `_row_datetime`。）

#### 3.1.4 当日价格 khPrice

- `khPrice(data, sc, "open")` 取**当日开盘价**（日线回测中当日K线已完整可用）。
- **无行情（停牌）时返回 `0.0`，不是 `None`** → 策略必须 `if not price: continue`，否则会以 0 价下单。

#### 3.1.5 下单 generate_signal（khQTTools.py:1462）

```python
generate_signal(data, code, price, ratio, action, reason) -> [signal_dict]
```

- **`ratio ≤ 1` 是比例语义**：买入 = 占**剩余现金**比例；卖出 = 占**可卖持仓**比例。
- `ratio > 1` 才是股数（须 100 整数倍）。
- 返回 `[{code, action, price, volume, reason, timestamp}]`，由引擎撮合（滑点/佣金/印花税在 config 里配）。
- 本项目约定：买入传 `0.2`（20% 现金仓）、卖出传 `1.0`（全仓）。

#### 3.1.6 撮合与费用（full_temp_running_config.kh）

- 滑点 `slippage.type=ratio, ratio=0.01`（单边约 0.5%，tick 相关）、佣金万 1（最低 5 元）、印花税万 5、`position_limit=0.95`、`order_limit=100`。
- 交易费用会真实吃掉收益，短线高频策略尤其敏感。

#### 3.1.7 数据源

- 日线/分钟线来自 `D:\khData`（DuckDB，SH/SZ 各一个 .db），经 `chan_report.load_bars(code, ex, "日线", sdt, edt, prewarm_bars=600)` 读取为 `RawBar` 列表（字段 open/high/low/close/amount，date 属性 `dt`）。
- 本地验证（test_drive）和 KhQuant 真机回测**用同一数据源**，结果可对照。

### 3.2 策略侧：T+1 pending 状态机（当前缠论箱体突破策略）

#### 时间语义

```
触发日 T（KhQuant 每天触发）→ 数据窗口最后一天 W = T-1（上一交易日，不含当日）
信号在 W 日收盘确认 → 记入 pending → W+1（=T）日开盘执行 → 真 T+1、无未来函数
```

#### 买入链路（两步）

1. **识别（W 日触发时）**：该股未持仓 + 150 根窗口内存在达标向上突破（突破成功、得分≥2、放量≥50%、**突破日 == W**）→ 记入 `pending_buy`。
2. **执行（T 日触发时）**：仍未持仓且持仓<5 只 → 按当日开盘价买入，仓位=剩余现金 20%。

#### 卖出链路（两步）

1. **识别（W 日触发时）**：该股持仓中 → 找**持仓突破日之后第一个顶分型**（笔端点 mark='G'），要求其**完整确认日（右侧K线日期）== W** → 记入 `pending_sell`。
2. **执行（T 日触发时）**：持仓中 → 按当日开盘价全部卖出。

#### 参数（策略顶部 params）

| 参数 | 值 | 含义 |
|---|---|---|
| min_score | 2 | 突破得分门槛 |
| vol_pct_threshold | 50 | 放量阈值（观察量/突破量 ≥50%） |
| position_ratio | 0.2 | 单只仓位=剩余现金 20% |
| max_positions | 5 | 最多 5 只（5×20%=满仓） |
| lookback_days | 150 | 分析窗口 150 根日线 |

#### ⚠️ 当前已知 bug（2026-09-09，待修复）

- 现象：部分股票买入后**永不卖出**（2025-01~2025-10 回测 27 笔交易中 5 只卡死，持仓 5~8 个月，期间出现多个确认顶分型也未卖）。
- 根因（已用调试脚本实证，见 `debug_sell_688036.py` 思路）：
  1. `_first_top_fx` **只返回突破后第一个顶分型**，后续顶分型永不检查；
  2. 第一个顶分型的确认窗口（确认日==W 那天）常因**笔尚未完成、分型还没进 fxs** 而错过，错过即永久卡死。
- 修复方向（待用户确认后实施）：判定从「确认日 == W」放宽为「**确认日 ≤ W 且该顶分型尚未卖出过**」，并遍历所有顶分型而非只看第一个。

### 3.3 本地验证（写策略/改策略后必做）

> 验证脚本在 `策略实例\` 下（脚本内部指向策略运行原件，位置不影响）。

```powershell
# 语法校验
& "C:\Users\xyz\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile <策略.py>

# 本地回归（mock KhQuant 环境：int索引+time列+不含当日，模拟真机语义）
cd D:\量化k线\回测策略类\策略实例
& "C:\Users\xyz\AppData\Local\Programs\Python\Python310\python.exe" test_drive_strategy.py `
    --stocks 000001.SZ,000858.SZ,002594.SZ,000333.SZ --start 20250101 --end 20260902 --mode without_today
```

- `--mode without_today` = KhQuant 真实语义（不含当日）；`with_today` 为对照。
- 验收标准：买卖配对无异常、无 1970 日期、无当日买+卖、信号与持仓天数合理。

### 3.4 部署（用户跑真机回测前）

1. 修改 `D:\量化k线\回测策略类\策略实例\缠论箱体突破策略_kh.py`（原件，直接改这份）；
2. `Copy-Item` 覆盖到 `C:\Users\xyz\AppData\Local\KhQuant\strategies\` 同名文件；
3. 清理 `__pycache__`（KhQuant strategies 目录 + D盘 core 目录），比对 SHA256 确认一致；
4. **必须让用户彻底重启 KhQuant 再回测**（见 3.5 模块缓存坑）。

### 3.5 环境与经验坑（血泪总结）

| 坑 | 说明 |
|---|---|
| **KhQuant 进程模块缓存** | GUI 是长驻进程，已 import 的模块不会因文件更新而重载。**改代码后不重启 KhQuant → 跑的还是旧代码**（曾致 `cannot import name IncrementalBoxFinder`）。每次改完必须重启。 |
| **int 索引当时间戳 → 1970** | khHistory 索引是 0,1,2…，必须从 time 列取日期（`_row_datetime`）。 |
| **khPrice 停牌返回 0.0** | 不是 None，判断要用 `if not price`，否则 0 价下单。 |
| **numpy datetime64** | time 列在 pandas 里是 numpy datetime64，`_to_datetime` 需支持 `.item()` 纳秒换算。 |
| **trigger 1d ≠ 定时触发** | 每天一次、在"当日K线可用"后触发；信号日 W=上一交易日。 |
| **系统 python 无 pandas** | 一律用 Python310 跑本地脚本；KhQuant 自身环境另算。 |

---

## 4. 接口约定（写给算法智能体）

策略通过 `sys.path.insert(0, r"D:\量化k线\缠论分型笔")` 引用算法模块，**依赖以下稳定接口**（算法改动请保持兼容，或在文档中标注变更）：

```python
# 分型/笔
from chan_fx_bi import RawBar              # bar: dt/open/high/low/close/amount/vol/id/freq
# 分析器（核心入口）
from core.chan_analyzer import ChanAnalyzer
ana = ChanAnalyzer(bars, symbol=sc, freq="日线", box_finder=..., start_dt=...)
ana.fxs                       # 笔端点分型列表（fx.dt, fx.mark: 'G'顶/'D'底, fx.high/low）
boxes = ana.find_boxes()      # 箱体列表，含 zg/zd/gg/dd/start/end/reason 等
# 箱体算法（策略模式，可替换）
from core.box_finder import BoxFinder, IncrementalBoxFinder
# 突破分析（find_boxes 后由策略继续调用）
ana.trend_classifier.calc_box_percentiles(boxes, bars)
ana.unified_breakout_analyzer.analyze(boxes_pct, bars, segments=ana.finished_segments)
# 卖出信号生成器
from core.sell_signal_generator import SellSignalGenerator
```

**数据接口（chan_report）**：
```python
from chan_report import load_bars
label, bars, prewarm = load_bars(code, ex, "日线", sdt, edt, prewarm_bars=600)
```

> 算法智能体新产出算法时：把新类/新函数放到 `D:\量化k线\缠论分型笔\core\`（或根目录），在 README/迭代日志里写明接口签名与变更，策略智能体负责适配进策略。
