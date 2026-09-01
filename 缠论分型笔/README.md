# 缠论 · 分型 / 笔 / 线段（Python 版）

从 GitHub 仓库 **czsc-master**（Rust 版 czsc-core）移植的缠论核心算法：
**「去包含关系 → 顶/底分型 → 笔」严格对齐 Rust 版 czsc-core；
「线段」为自定义实现（同向笔极值递推）**。
按需求刻意**不含**：中枢、买卖点、背驰、趋势判断。

---

## 📁 文件结构

```
缠论分型笔/
├── 分型+笔.py          # 核心算法模块（数据结构 + 去包含 + 分型 + 笔 + 线段 + CZSC 分析器）
├── chan_report.py      # 报告程序（读取 D:\khData → 分析 → 输出文本 + HTML 图表报告）
├── assets/
│   └── echarts.min.js  # 离线图表渲染资源（HTML 报告无需联网）
├── reports/            # 生成的 HTML 图表报告
│   ├── 000001_SH_日线_20240630.html
│   └── 000001_SH_30分钟_20250815.html
└── README.md           # 本说明
```

## 🧩 核心模块（分型+笔.py）

| 组件 | 说明 |
|---|---|
| `RawBar` / `NewBar` | 原始K线 / 去包含K线（记录合并来源 elements） |
| `FX` | 分型：`mark='G'顶 / 'D'底`，含强度 power_str、量能 power_volume |
| `BI` | 笔：direction、get_high/get_low/get_power/get_length |
| `Segment` | 线段：direction、get_high/get_low/get_power、finished（是否已确认） |
| `remove_include()` | 包含关系处理（向上取高 / 向下取低，量额累加） |
| `check_fx()` / `check_fxs()` | 分型识别（顶底强制交替） |
| `check_bi()` | 笔划分（底起选最高顶 / 顶起选最低底，并列保留首个） |
| `check_segments()` | 线段划分（自定义：同向笔极值递推，见下方规则） |
| `CZSC` | 增量分析器：update_bar 逐根喂入、fx_list / bi_list / segments / get_finished_bis / last_bi_extend |

> 分型/笔算法已与 Rust 版 czsc-core 自带测试数据对拍验证：4 笔、12 个分型完全一致；
> 线段逻辑已通过单元验证（创新高延伸 / 不创新高结束 / 孤笔跳过 / 未完成段）；
> 增量喂入与一次性构造结果一致。

## 📐 线段划分规则（自定义）

- 从第一笔开始，其方向即线段方向；
- **向上线段**：起点固定为该起始笔的起点，向后扫描：跳过反向（向下）笔，
  向上笔**创新高**则延伸（更新线段终点），一旦出现不创新高的向上笔，
  线段结束于**最后一个创新高的向上笔**；
- **向下线段**：对称地，向下笔**创新低**才延伸，不创新低即结束；
- 线段结束后，**从终点笔的下一笔立即开始反方向线段**——线段首尾相接、
  连续覆盖所有笔，**不产生空档**；
- 至少 1 笔即可成段（不设 3 笔下限）；
- 延伸到数据最后一笔的线段标记为「未完成」（`finished=False`，行情可能继续）。

> 说明：由于不设成段下限，当某段反向力度极弱（仅 1~2 笔）时，会出现极短线段，
> 这是「无空档、连续延伸」逻辑的自然结果。

## 🚀 使用方法

### 1. 报告程序（最常用）

```bash
# 命令行：代码 周期 起始日期 终止日期
python chan_report.py 600000.SH 日线 2024-01-01 2024-12-31
python chan_report.py 000001.SZ 30分钟 2025-08-01 2025-08-31

# 交互模式
python chan_report.py
```

> 需使用安装了 duckdb 的 Python（本机为系统 Python 3.10）：
> `C:\Users\xyz\AppData\Local\Programs\Python\Python310\python.exe chan_report.py ...`

**输出**：
- 终端文本报告：结构统计 + 线段清单 + 笔清单 + 分型清单（时间/值/强度/量能）
- HTML 图表报告：K线 + 笔(灰细线) + 线段(蓝粗线) + 顶分型(红三角)/底分型(绿三角) + 成交量
  自动存到 `reports/` 并尝试用浏览器打开

**支持周期**：1/5/15/30/60/120 分钟、日线、周线、月线（周/月由日线重采样）

### 2. 直接在代码里调用

```python
from 分型+笔 import CZSC, bars_from_rows   # 或 import chan_fx_bi 后使用

rows = [{"dt": ..., "open": .., "close": .., "high": .., "low": .., "vol": .., "amount": ..}, ...]
bars = bars_from_rows(rows, symbol="600000.SH", freq="日线")
c = CZSC(bars, max_bi_num=50, min_bi_len=6)

for fx in c.fx_list:      # 分型
    print(fx.mark, fx.dt, fx.fx, fx.power_str())
for bi in c.bi_list:      # 笔
    print(bi.direction, bi.start_dt, bi.end_dt, bi.get_low(), bi.get_high())
for seg in c.segments:    # 线段（含未完成段）
    print(seg.direction, seg.start_dt, seg.end_dt, seg.finished, seg.get_length())
```

## 📝 数据说明

- 数据源：`D:\khData`（DuckDB，每个标的一个 .db），字段 `time/open/high/low/close/volume/amount`
- 数据覆盖：日线自 2016 年起；分钟数据自 2025-07 起（早于此区间无分钟数据会提示）
- 预热：数据不足 600 根时自动向前补足历史K线，保证缠论结构完整

## ⚠️ 免责声明

本工具仅作缠论技术分析参考，不构成任何投资建议。
