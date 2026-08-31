# -*- coding: utf-8 -*-
"""模块4：线段生成（次级别：笔）

输入：模块3 的笔列表
输出：线段列表（direction/start/end/high/low/is_confirmed/bis）

规则（简化可落地版）：
1. 线段 = 连续的笔构成的有方向走势，至少 3 笔，且前三笔存在价格重叠
2. 方向由进入线段的第一笔方向决定
3. 特征序列：向上线段的特征序列 = 所有向下笔；向下 = 所有向上笔
4. 终结判定：
   - 向上线段：特征序列（向下笔）出现顶分型，且该顶分型高点 = 线段最高点 → 终结
   - 向下线段：特征序列（向上笔）出现底分型，且该底分型低点 = 线段最低点 → 终结
5. 前线段终结后，新线段自动开始，方向相反
"""
from .models import Segment


def generate_segment(bis):
    """从笔生成线段。返回 (线段列表, 未完成线段 或 None)"""
    segs = []
    i = 0
    n = len(bis)
    while i < n - 2:
        b1, b2, b3 = bis[i], bis[i + 1], bis[i + 2]
        # 前三笔方向交替（b1,b3 同向）
        if not (b1.direction != b2.direction and b2.direction != b3.direction):
            i += 1
            continue
        # 前三笔价格重叠
        zd = max(b1.low, b2.low, b3.low)
        zg = min(b1.high, b2.high, b3.high)
        if zd > zg:
            i += 1
            continue
        direction = b1.direction
        seg_bis = [b1, b2, b3]
        feat = [b2]  # 特征序列（反向笔）
        j = i + 3
        end_j = None
        while j < n:
            bi = bis[j]
            if bi.direction == direction:
                seg_bis.append(bi)   # 同向笔，趋势延续
            else:
                feat.append(bi)      # 反向笔 = 特征序列元素
                seg_bis.append(bi)
                # 特征序列顶/底分型判定
                if len(feat) >= 3:
                    f1, f2, f3 = feat[-3:]
                    if direction == 'up':
                        # 顶分型：f2 高点最高，且 f2 高点 = 线段最高点
                        if f2.high >= f1.high and f2.high >= f3.high:
                            seg_high = max(b.high for b in seg_bis)
                            if abs(f2.high - seg_high) < 1e-6:
                                end_j = j
                                break
                    else:
                        # 底分型：f2 低点最低，且 f2 低点 = 线段最低点
                        if f2.low <= f1.low and f2.low <= f3.low:
                            seg_low = min(b.low for b in seg_bis)
                            if abs(f2.low - seg_low) < 1e-6:
                                end_j = j
                                break
            j += 1
        if end_j is None:
            # 未找到终结点：换起点继续找（不能 break 整个函数）
            i += 1
            continue
        # 旧线段 = seg_bis 去掉终结笔（特征序列分型笔，归新线段）
        s_bis = seg_bis[:-1]
        if len(s_bis) < 3:
            i = end_j
            continue
        seg = Segment(
            index=len(segs) + 1,
            direction=direction,
            start_time=s_bis[0].start_time,
            end_time=s_bis[-1].end_time,
            start_price=s_bis[0].start_price,
            end_price=s_bis[-1].end_price,
            high=max(b.high for b in s_bis),
            low=min(b.low for b in s_bis),
            is_confirmed=True,
            bis=s_bis,
        )
        segs.append(seg)
        i = end_j  # 新线段从终结笔（特征序列分型笔）开始，方向与其一致（=前线段反向）
    return segs
