# RangeBoxFinder —— 盘整箱体事后识别器（独立测试目录）

本目录是**新盘整逻辑的独立测试区**，与现有源码完全隔离：

- 新类：`range_box_finder.py`（RangeBoxFinder，未来函数版水平箱体识别）
- 自检：`synthetic_check.py`（5 组合成数据，验证各规则触发）
- 真实数据测试 + HTML 报告：`run_test.py`
- 生成的报告：`report_*.html`（深色金融风格，ECharts，离线可打开）

**删除方式**：测试完效果不好，直接删掉整个 `box_range_test` 文件夹即可，
不影响 `缠论分型笔` 下任何现有代码（已用 git 核对：本测试未改动任何源码）。

---

## 算法口径（未来函数版 · 事后回填）

1. **未来K线确认波峰/波谷**：`scipy.signal.find_peaks` 在 high/low 上找局部高低点，
   显著度 prominence = max(0.5×ATR14, 价格×0%)，最小间距 distance=5 根，
   过滤幅度太小的波动；相邻同类型只保留更极端者 → 严格交替的峰谷序列。
2. **稳定箱体**：上沿 U=median(峰价)，下沿 L=median(谷价)，W=U−L，要求：
   - ≥20 根K线（min_bars）；
   - ≥2 峰、≥2 谷（交替出现）；
   - 峰距上沿、谷距下沿均 ≤ 0.15W（peak_tol/trough_tol）；
   - ≥90% 收盘价落在 [L−0.1W, U+0.1W]（cover_ratio/cover_tol）；
   - 前/中/后三段收盘价中位数最大差 ≤ 0.25W（median_tol，防"先涨后跌首尾接近"）；
   - 可选窄幅：max_w_pct 限定 W/价格中值。
3. **扩展**：固定上下沿向左右逐根扩展（新纳入K线收盘价须在带内，防止吞掉突破段；
   若引入新转折点，上下沿调整幅度 ≤ 0.5W 才接受，防止把趋势包进来）。
4. **重叠/合并**：重叠候选保留更完整区间；相邻箱体合并后仍满足条件才合并。
5. **结束确认回填**：连续 3 根收盘价突破同一侧边界（+容差 breakout_tol）→ 确认离开，
   终点回填到该连续突破第一根之前；数据末尾未确认 → `confirmed=False`（尚未结束）。

输出：开始时间 / 结束时间（回填）/ 核心起止 / 上沿 / 下沿 / 峰谷数 / 覆盖 /
重心差 / **实际确认时间** / 突破方向 / 是否已确认。

> ⚠️ 回测注意：起点、终点、上下沿都是事后回填的，**实际确认时间之前**的信息
> 才是当时可用的信号，不要把回填起点当实时信号。

## 用法

```bash
# 1. 合成数据自检（12 项断言）
python synthetic_check.py

# 2. 真实数据测试 + HTML 报告（默认 3 个标的）
python run_test.py

# 自定义标的/周期/区间
python run_test.py --symbols 600519.SH --freq 日线 --start 20250101 --end 20260904
python run_test.py --symbols 000300.SH --freq 30分钟 --start 20260801 --end 20260904 --no-chan
```

Python：`C:\Users\xyz\AppData\Local\Programs\Python\Python310\python.exe`
（依赖 scipy / duckdb / pandas，本机已装）。

## 参数说明（构造 RangeBoxFinder 时传入，均为可调示例值）

| 参数 | 默认 | 含义 |
|---|---|---|
| min_distance | 5 | 转折点最小间距（根） |
| prominence_atr | 0.5 | 峰谷显著度 = ×ATR14（过滤小波动） |
| min_prominence_pct | 0.0 | 显著度下限 = 价格×%（可选） |
| atr_n | 14 | ATR 周期 |
| min_bars | 20 | 箱体最短K线数 |
| min_peaks / min_troughs | 2 / 2 | 最少峰 / 谷数 |
| peak_tol / trough_tol | 0.15 / 0.15 | 峰距上沿 / 谷距下沿 容差（×W） |
| cover_ratio / cover_tol | 0.90 / 0.10 | 收盘价在带内比例 / 带宽容差 |
| median_tol | 0.25 | 三段中位数最大差（×W） |
| max_w_pct | None | 窄幅限制：箱体高 / 价格中值 % |
| max_edge_shift | 0.5 | 扩展时上下沿最大调整（×W） |
| max_gap_merge | 5 | 相邻箱体合并最大间隔（根） |
| extend_strict_band | True | 扩展时新K线收盘价须在带内 |
| breakout_confirm | 3 | 连续突破根数 |
| breakout_tol | 0.0 | 突破容差（收盘需超出边界的比例） |

## 真实数据结果示例（2026-09-02 数据）

| 标的 | 周期 | 箱体 | 示例区间 | 状态 |
|---|---|---|---|---|
| 000001.SH | 日线 | 2 | 2024-03-15 ~ 2024-04-26（U=3090/L=2996） | 已确认向上突破 |
| 000001.SH | 日线 | 2 | 2026-05-20 ~ 2026-07-15（U=4175/L=3939） | 已确认向下突破 |
| 600887.SH | 日线 | 2 | 2025-07-15 ~ 2025-11-17（U=27.6/L=25.6） | 已确认向上突破 |
| 000300.SH | 30分钟 | 3 | 2026-05-15 ~ 2026-05-26（U=4938/L=4777） | 已确认向上突破 |

> 注：演示参数 peak_tol/trough_tol=0.25（用户示例 0.15 在日线上极严格，常识别 0 个，
> 属正常现象——真实日线很少出现 20+ 根绝对水平的箱体）。改回严格值：
> `run_test.py` 中 `DEMO_PARAMS` 置空或改 0.15 即可。

## 调用关系（只读调用，未侵入）

```
chan_report.load_bars（已有数据层，只读）→ RangeBoxFinder（本目录新类）
core.chan_analyzer.ChanAnalyzer（已有分析器，只读，取分型作图上参照）
```

本目录与 `缠论分型笔` 其他代码零耦合；删除本目录即可完全清理。
