# -*- coding: utf-8 -*-
"""筹码峰计算逻辑 · 讲解示意图生成脚本（供 README/讲解使用）"""
import sys, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["SimHei"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chip_distribution import ChipDistribution, load_front_daily

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# 图1：单日三角形分布（一天 100 万股，最低 10 元，最高 12 元，收盘 11.5 元）
# ---------------------------------------------------------------------------
low, high, close, vol = 10.0, 12.0, 11.5, 100.0  # 单位：万股
cd_tmp = ChipDistribution(n_bins=21)
cd_tmp._bins = np.linspace(low, high, 21)
cd_tmp._bin_w = (high - low) / 20
c = cd_tmp._tri_dist(low, high, close, vol)

fig, ax = plt.subplots(figsize=(9, 4.6), dpi=130)
ax.bar(cd_tmp.bins, c, width=0.095, color="#f87171", alpha=0.85,
       edgecolor="none", label="每档筹码量（万股）")
# 理论三角形轮廓
xx = np.linspace(low, high, 400)
yy = np.where(xx <= close, (xx - low) / (close - low), (high - xx) / (high - close))
yy = yy * vol / yy.sum() * 20 / 0.095  # 缩放到柱状图尺度
ax.plot(xx, yy, color="#1f2937", lw=1.6, ls="--", label="三角形理论轮廓")
ax.axvline(close, color="#ef4444", lw=1.2, ls=":")
ax.annotate("顶点=收盘价 11.5\n（当天成交最集中的价位）", xy=(close, c.max() * 0.85),
            xytext=(11.15, c.max() * 0.72), fontsize=10, color="#ef4444",
            arrowprops=dict(arrowstyle="->", color="#ef4444"))
ax.annotate("最低价 10.0\n（此价位筹码为 0）", xy=(low, 0.2), xytext=(10.05, c.max() * 0.45),
            fontsize=9, color="#6b7280", arrowprops=dict(arrowstyle="->", color="#6b7280"))
ax.annotate("最高价 12.0\n（此价位筹码为 0）", xy=(high, 0.2), xytext=(11.35, c.max() * 0.30),
            fontsize=9, color="#6b7280", arrowprops=dict(arrowstyle="->", color="#6b7280"))
ax.set_title("第 1 步：单日成交量按『三角形』摊到价格区间\n"
             "一天成交 100 万股，价格在 10~12 元，收盘 11.5 元", fontsize=12)
ax.set_xlabel("价格（元）")
ax.set_ylabel("筹码量（万股）")
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.25)
fig.tight_layout()
p1 = os.path.join(OUT, "图1_单日三角形分布.png")
fig.savefig(p1)
plt.close(fig)
print("saved:", p1)

# ---------------------------------------------------------------------------
# 图2：真实数据 —— 原始分布 vs 平滑后 vs 识别出的峰（000001.SZ 最近一日）
# ---------------------------------------------------------------------------
rows = load_front_daily("000001", "SZ")
cd = ChipDistribution(window=250, decay=0.98, n_bins=200)
snaps = cd.compute(rows)
s = snaps[-1]
total = s.total

# 原始直方图（归一化到 %）
dist_pct = s.dist / total * 100.0
b = cd.bins

# 平滑（与算法一致：3 档平均）
w = cd.smooth
sm = np.convolve(dist_pct, np.ones(w) / w, mode="same")
pad = w // 2
sm[:pad] = dist_pct[:pad]
sm[-pad:] = dist_pct[-pad:]

# 峰（与算法一致）
peaks = s.peaks

fig, ax = plt.subplots(figsize=(10.5, 5.2), dpi=130)
ax.bar(b, dist_pct, width=(b[1]-b[0])*0.92, color="#9ca3af", alpha=0.55,
       edgecolor="none", label="原始分布（200 个价格档，锯齿状）")
ax.plot(b, sm, color="#f59e0b", lw=2.2, label=f"平滑后（{w} 档平均，去掉毛刺）")
for p in peaks:
    ax.axvline(p["price"], color="#ef4444", lw=1.0, ls="--", alpha=0.8)
    ax.annotate(f"峰 {p['price']:.2f} 元\n占比 {p['share']*100:.1f}%",
                xy=(p["price"], sm[abs(b - p["price"]).argmin()]),
                xytext=(p["price"] + (b[-1]-b[0])*0.045, sm[abs(b - p["price"]).argmin()] + 0.5),
                fontsize=9, color="#ef4444",
                arrowprops=dict(arrowstyle="->", color="#ef4444", lw=1))
ax.set_title(f"第 2 步：从筹码分布里『找峰』（{s.dt}，{s.close:.2f} 元收盘）\n"
             "峰 = 平滑后比左右邻居都高、且占比 ≥3% 的价格档，按量从大到小排序", fontsize=12)
ax.set_xlabel("价格（元）")
ax.set_ylabel("筹码占比（%）")
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.25)
fig.tight_layout()
p2 = os.path.join(OUT, "图2_筹码峰识别过程.png")
fig.savefig(p2)
plt.close(fig)
print("saved:", p2)
print("实际识别出的峰:", [(p["price"], f"{p['share']*100:.1f}%") for p in peaks])
