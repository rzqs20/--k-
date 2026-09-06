# -*- coding: utf-8 -*-
"""
盘整区间质量分析类
==================
专门用于分析箱体（盘整区间）的内部特征，如收敛度、方向、量能变化等。
你可以在这里自定义算法，不影响箱体识别和突破监测逻辑。

使用方式：
    from core.box_quality_analyzer import BoxQualityAnalyzer
    analyzer = BoxQualityAnalyzer()
    boxes_with_quality = analyzer.analyze(boxes, bars)

每个箱体会新增以下字段：
    - conv_ratio: 收敛比（后半段振幅/前半段振幅）
    - vol_conv_ratio: 量能收敛比
    - conv_score: 收敛度评分
    - conv_label: 收敛度标签
    - quality: 自定义质量字段（可扩展）
"""
import bisect


class BoxQualityAnalyzer:
    """盘整区间质量分析器

    你可以在这里添加任意自定义分析方法，只要在 analyze() 中调用即可。
    所有分析结果都会作为字段添加到箱体字典中。
    """

    def __init__(self, **kwargs):
        """初始化参数，可通过 kwargs 覆盖默认阈值"""
        # 标准度阈值（可自定义）
        self.strong_standard_threshold = kwargs.get("strong_standard", 0.7)
        self.weak_standard_threshold = kwargs.get("weak_standard", 0.5)
        self.non_standard_threshold = kwargs.get("non_standard", 0.3)

    def analyze(self, boxes, bars, fxs=None, trends=None):
        """对所有箱体进行质量分析

        Parameters
        ----------
        boxes : list[dict]
            BoxFinder 输出的箱体列表
        bars : list
            原始K线列表
        fxs : list, optional
            笔端点分型列表（用于去极值计算ZG/ZD）
        trends : list[dict], optional
            趋势列表（用于找前一段趋势，判断放量/缩量盘整）
            每个趋势含 start/end/direction 字段

        Returns
        -------
        list[dict]
            每个箱体含原字段 + 质量分析字段
        """
        if not boxes or not bars:
            return []

        dts = [b.dt for b in bars]

        def _idx(dt):
            return bisect.bisect_right(dts, dt) - 1

        result = []
        for box in boxes:
            labeled = dict(box)
            si = _idx(box["start"])
            ei = _idx(box["end"])
            box_bars = bars[si:ei + 1]

            if not box_bars or len(box_bars) < 6:
                labeled.update(self._empty_quality())
                result.append(labeled)
                continue

            # === 1. 标准度分析（K线覆盖率+重叠区占比，可替换）===
            # 找到箱体内的分型
            box_fxs = []
            if fxs:
                box_fxs = [fx for fx in fxs if box["start"] <= fx.dt <= box["end"]]
            quality = self._analyze_standardness(box_bars, box, box_fxs)
            labeled.update(quality)

            # === 2. 成交量分析（放量/缩量盘整）===
            # 找到箱体开始前的最近一段趋势
            prev_trend = None
            if trends:
                for t in reversed(trends):
                    if t["end_time"] <= box["start"]:
                        prev_trend = t
                        break
            vol_quality = self._analyze_volume(box_bars, bars, prev_trend, si)
            labeled.update(vol_quality)

            # === 3. 在这里添加你的自定义分析 ===
            # 例如：
            # custom = self._my_custom_analysis(box_bars, box)
            # labeled.update(custom)

            result.append(labeled)

        return result

    def _analyze_standardness(self, box_bars, box, box_fxs=None):
        """箱体标准度分析：K线覆盖率 + 重叠区占比 双维度结合（带去极值）

        综合标准度 = 0.5 × K线覆盖率 + 0.5 × 重叠区占比
        - K线覆盖率 = 收盘价在[ZD, ZG]内的K线数 / 箱体总K线数（时间维度）
        - 重叠区占比 = (ZG - ZD) / (GG - DD)（空间维度）

        去极值逻辑：去掉1个最低顶分型和1个最高底分型，
        如果去极值后综合标准度更高，则采用去极值后的ZG/ZD。
        """
        gg = box.get("gg", 0)
        dd = box.get("dd", 0)
        zg = box.get("zg", 0)
        zd = box.get("zd", 0)

        total_bars = len(box_bars)
        full_range = gg - dd

        def _calc_score(zg_val, zd_val):
            """计算给定ZG/ZD下的综合标准度"""
            if full_range <= 0 or zg_val <= zd_val or total_bars <= 0:
                return 0.0, 0.0, 0.0, 0
            # 空间维度：重叠区占比
            overlap_ratio = (zg_val - zd_val) / full_range
            # 时间维度：K线覆盖率
            cover_count = sum(1 for b in box_bars if zd_val <= b.close <= zg_val)
            cover_ratio = cover_count / total_bars
            # 综合：各50%权重
            combined = 0.5 * cover_ratio + 0.5 * overlap_ratio
            return combined, cover_ratio, overlap_ratio, cover_count

        # 原始综合标准度
        original_score, orig_cover, orig_overlap, _ = _calc_score(zg, zd)

        # 去极值：如果有分型数据，尝试去掉1个最低顶和1个最高底
        trimmed = False
        if box_fxs and len(box_fxs) >= 4:
            top_fxs = [fx for fx in box_fxs if fx.mark == "G"]
            bot_fxs = [fx for fx in box_fxs if fx.mark == "D"]

            if len(top_fxs) >= 3 and len(bot_fxs) >= 3:
                # 去掉最低的顶分型（最接近中部的异常顶）
                top_prices = sorted([fx.high for fx in top_fxs])
                trimmed_top = top_prices[1:]  # 去掉最低的1个
                new_zg = min(trimmed_top)

                # 去掉最高的底分型（最接近中部的异常底）
                bot_prices = sorted([fx.low for fx in bot_fxs], reverse=True)
                trimmed_bot = bot_prices[1:]  # 去掉最高的1个
                new_zd = max(trimmed_bot)

                # 去极值后的综合标准度
                new_score, _, _, _ = _calc_score(new_zg, new_zd)

                # 如果去极值后综合标准度更高，且重叠区有效，则采用
                if new_score > original_score and new_zg > new_zd:
                    zg = new_zg
                    zd = new_zd
                    trimmed = True

        # 最终综合标准度
        standard_ratio, cover_ratio, overlap_ratio, cover_count = _calc_score(zg, zd)

        if standard_ratio >= 0.7:
            standard_score = 2
            standard_label = "强标准"
        elif standard_ratio >= 0.5:
            standard_score = 1
            standard_label = "弱标准"
        elif standard_ratio >= 0.3:
            standard_score = 0
            standard_label = "中性"
        else:
            standard_score = -1
            standard_label = "不标准"

        return {
            "standard_ratio": round(standard_ratio, 3),
            "standard_score": standard_score,
            "standard_label": standard_label,
            "zg_trimmed": zg,
            "zd_trimmed": zd,
            "trimmed": trimmed,
            "cover_ratio": round(cover_ratio, 3),
            "overlap_ratio": round(overlap_ratio, 3),
            "cover_count": cover_count,
            "total_bars": total_bars,
        }

    def _analyze_volume(self, box_bars, bars, prev_trend, box_start_idx):
        """成交量分析：判断箱体是放量盘整还是缩量盘整

        无未来函数：只用箱体开始之前的趋势数据，箱体内用已有的K线。
        前一段趋势 = 箱体开始时间之前的最近一段趋势。

        Parameters
        ----------
        box_bars : list
            箱体内的K线
        bars : list
            全部K线
        prev_trend : dict or None
            箱体开始前的最近一段趋势
        box_start_idx : int
            箱体开始K线索引

        Returns
        -------
        dict
            vol_ratio, vol_label, prev_trend_vol, box_vol
        """
        # 箱体内平均成交量
        box_vol = sum(b.vol for b in box_bars) / len(box_bars) if box_bars else 0

        # 前一段趋势的平均成交量
        prev_trend_vol = 0
        prev_trend_dir = "未知"
        if prev_trend and box_start_idx > 0:
            # 找到前一段趋势的K线范围（只用箱体开始之前的数据，无未来函数）
            dts = [b.dt for b in bars]
            import bisect as _bisect
            t_start_idx = _bisect.bisect_right(dts, prev_trend["start_time"]) - 1
            t_end_idx = _bisect.bisect_right(dts, prev_trend["end_time"]) - 1
            t_start_idx = max(0, t_start_idx)
            t_end_idx = min(box_start_idx - 1, t_end_idx)  # 严格在箱体开始之前
            if t_end_idx >= t_start_idx:
                trend_bars = bars[t_start_idx:t_end_idx + 1]
                prev_trend_vol = sum(b.vol for b in trend_bars) / len(trend_bars) if trend_bars else 0
                prev_trend_dir = prev_trend.get("direction", "未知")

        # 成交量比值
        if prev_trend_vol > 0:
            vol_ratio = box_vol / prev_trend_vol
        else:
            vol_ratio = 1.0  # 无前趋势数据时默认为平量

        # 判断放量/平量/缩量
        if vol_ratio >= 1.2:
            vol_label = "放量盘整"
        elif vol_ratio <= 0.8:
            vol_label = "缩量盘整"
        else:
            vol_label = "平量盘整"

        return {
            "vol_ratio": round(vol_ratio, 3),
            "vol_label": vol_label,
            "prev_trend_vol": round(prev_trend_vol, 2),
            "box_vol": round(box_vol, 2),
            "prev_trend_direction": prev_trend_dir,
        }

    def _empty_quality(self):
        """箱体K线不足时的空质量"""
        return {
            "standard_ratio": 0.0,
            "standard_score": 0,
            "standard_label": "数据不足",
            "vol_ratio": 1.0,
            "vol_label": "数据不足",
            "prev_trend_vol": 0,
            "box_vol": 0,
            "prev_trend_direction": "未知",
        }

    # ================================================================
    #  在下面添加你的自定义分析方法
    # ================================================================

    # def _my_custom_analysis(self, box_bars, box):
    #     """你的自定义分析方法
    #
    #     可以分析：
    #     - 顶分型/底分型的抬高/降低趋势
    #     - 箱体内部笔的振幅变化
    #     - 量价配合关系
    #     - 等等
    #
    #     返回一个字典，会自动添加到箱体字段中。
    #     """
    #     return {
    #         "my_metric": 0,
    #         "my_label": "示例",
    #     }
