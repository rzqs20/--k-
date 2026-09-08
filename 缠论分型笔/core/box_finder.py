# -*- coding: utf-8 -*-
"""
箱体/盘整识别器（BoxFinder）
独立封装，便于未来优化盘整算法而不影响其他模块。

算法：同类型分型斜率 + 绝对涨跌幅 双条件法
- 计算相邻顶/底分型之间的斜率(涨跌幅%/K线数) 和 绝对涨跌幅%
- 两个阈值都取分位数自适应（默认前60%最平缓）
- 分型"平缓"需同时满足：斜率<=斜率阈值 且 绝对涨跌幅<=涨跌幅阈值
- 段首分型允许不满足（趋势终点），只要后面连续>=3个满足
- 扩展时实时检查重叠区(ZG>ZD)，一旦破坏则停止
- 整体高度(GG-DD)在 [min_h_pct, max_h_pct]% → 成立

用法：
    from core.box_finder import BoxFinder
    bf = BoxFinder(slope_quantile=0.6, chg_quantile=0.6)
    boxes = bf.find(fxs, bars)
"""
import bisect
from abc import ABC, abstractmethod


class BoxFinderBase(ABC):
    """
    箱体识别器抽象基类（策略模式）。
    所有箱体算法都继承此类，实现 find(fxs, bars) 方法。
    ChanAnalyzer 通过传入不同的 box_finder 切换算法。
    """

    @abstractmethod
    def find(self, fxs, bars):
        """
        执行箱体识别。

        Parameters
        ----------
        fxs : list
            笔端点分型列表（按时间升序）
        bars : list
            K线列表

        Returns
        -------
        list
            箱体列表，每个箱体是 dict，至少包含：
            start_time, end_time, GG, DD, ZG, ZD, fxs, bar_count
        """
        pass


class IncrementalBoxFinder(BoxFinderBase):
    """
    增量箱体识别器。

    核心特性：
    - 滚动窗口阈值：用最近N个分型的前60%分位，而非全量
    - 确认锁定：箱体一旦确认，起点和边界锁定，后续数据不再修改
    - 保留段首允许和向前扩展（只在确认时一次性执行）

    Parameters
    ----------
    slope_quantile : float
        斜率分位数（0~1），越小越严格
    chg_quantile : float
        绝对涨跌幅分位数（0~1），越小越严格
    min_fx : int
        箱体最少分型数
    min_h_pct : float
        箱体最小全高（%）
    max_h_pct : float
        箱体最大全高（%）
    window_size : int
        滚动窗口大小（最近多少个分型计算阈值）
    """

    def __init__(self, slope_quantile=0.6, chg_quantile=0.6, min_fx=4,
                 min_h_pct=0.5, max_h_pct=50.0, window_size=20):
        self.slope_quantile = slope_quantile
        self.chg_quantile = chg_quantile
        self.min_fx = min_fx
        self.min_h_pct = min_h_pct
        self.max_h_pct = max_h_pct
        self.window_size = window_size

    def find(self, fxs, bars, start_dt=None):
        """
        执行增量箱体识别。箱体确认后锁定，不随后续数据变化。

        Parameters
        ----------
        fxs : list
            笔端点分型列表
        bars : list
            K线列表
        start_dt : datetime, optional
            起始日期，之前的分型只用于计算阈值，不参与箱体构成
        """
        if len(fxs) < self.min_fx:
            return []

        dts = [b.dt for b in bars]

        def _idx(dt):
            return bisect.bisect_right(dts, dt) - 1

        # 预计算所有分型的斜率和涨跌幅（基于前一个同类型分型）
        slope_of = {}
        chg_of = {}
        tops = [fx for fx in fxs if fx.mark == "G"]
        bots = [fx for fx in fxs if fx.mark == "D"]

        for i in range(1, len(tops)):
            dpct = abs(tops[i].high - tops[i-1].high) / ((tops[i].high + tops[i-1].high) / 2) * 100
            dn = max(1, _idx(tops[i].dt) - _idx(tops[i-1].dt))
            slope_of[tops[i].dt] = dpct / dn
            chg_of[tops[i].dt] = dpct
        for i in range(1, len(bots)):
            dpct = abs(bots[i].low - bots[i-1].low) / ((bots[i].low + bots[i-1].low) / 2) * 100
            dn = max(1, _idx(bots[i].dt) - _idx(bots[i-1].dt))
            slope_of[bots[i].dt] = dpct / dn
            chg_of[bots[i].dt] = dpct

        def _calc_threshold(end_idx):
            """计算滚动窗口阈值：end_idx之前最近window_size个分型"""
            start = max(0, end_idx - self.window_size)
            window_fxs = fxs[start:end_idx]
            slopes = [slope_of[fx.dt] for fx in window_fxs if fx.dt in slope_of]
            chgs = [chg_of[fx.dt] for fx in window_fxs if fx.dt in chg_of]
            slopes.sort()
            chgs.sort()
            slope_thr = slopes[int(len(slopes) * self.slope_quantile)] if slopes else 999
            chg_thr = chgs[int(len(chgs) * self.chg_quantile)] if chgs else 999
            return slope_thr, chg_thr

        def _ok(fx, slope_thr, chg_thr):
            if fx.dt not in slope_of:
                return True
            return slope_of[fx.dt] <= slope_thr and chg_of[fx.dt] <= chg_thr

        def _overlap_ok(run):
            t = [fx.high for fx in run if fx.mark == "G"]
            b = [fx.low for fx in run if fx.mark == "D"]
            if not t or not b:
                return True
            return min(t) > max(b)

        def _try_extend_back(start, run, gg, dd):
            """向前扩展1-2个分型（只在确认时执行一次）"""
            final_mid = (gg + dd) / 2
            extended = 0
            for back in range(1, 3):
                idx = start - back
                if idx < 0:
                    break
                fx = fxs[idx]
                fx_price = fx.high if fx.mark == "G" else fx.low
                first_fx = run[0]
                if first_fx.mark == "G":
                    in_half = dd <= fx_price <= final_mid
                else:
                    in_half = final_mid <= fx_price <= gg
                if in_half:
                    run.insert(0, fx)
                    extended += 1
                else:
                    break
            return extended

        boxes = []
        confirmed_ends = set()  # 已确认箱体的终点索引，避免重复

        # 预热：找到start_dt后的第一个分型索引，之前的分型只用于计算阈值
        start_idx = 0
        if start_dt is not None:
            while start_idx < len(fxs) and fxs[start_idx].dt < start_dt:
                start_idx += 1

        i = 0  # 从0开始遍历，start_dt之前的分型只用于计算阈值
        while i < len(fxs):
            # 跳过已确认箱体覆盖的范围
            if i in confirmed_ends:
                i += 1
                continue

            # start_dt之前的分型不做箱体判断，只用于计算阈值
            if i < start_idx:
                i += 1
                continue

            # 用滚动窗口计算当前阈值
            slope_thr, chg_thr = _calc_threshold(i)

            # 段首允许：当前不平缓但后面连续≥3个平缓
            if _ok(fxs[i], slope_thr, chg_thr):
                start = i
            else:
                k = i + 1
                cnt = 0
                while k < len(fxs) and _ok(fxs[k], slope_thr, chg_thr):
                    cnt += 1
                    k += 1
                if cnt >= 3:
                    start = i
                else:
                    i += 1
                    continue

            # 扩展run
            j = start + 1
            while j < len(fxs) and j - start < self.min_fx:
                if not _ok(fxs[j], slope_thr, chg_thr):
                    break
                if not _overlap_ok(fxs[start:j+1]):
                    break
                j += 1

            # 层2：提前向后扩展1个分型
            early_extended = 0
            if j - start >= self.min_fx:
                temp_run = fxs[start:j]
                temp_gg = max(fx.high for fx in temp_run)
                temp_dd = min(fx.low for fx in temp_run)
                temp_mid = (temp_gg + temp_dd) / 2
                idx = start - 1
                if idx >= 0:
                    fx = fxs[idx]
                    fx_price = fx.high if fx.mark == "G" else fx.low
                    first_fx = temp_run[0]
                    if first_fx.mark == "G":
                        in_half = temp_dd <= fx_price <= temp_mid
                    else:
                        in_half = temp_mid <= fx_price <= temp_gg
                    if in_half:
                        start = idx
                        early_extended = 1

            # 继续扩展到最大
            while j < len(fxs):
                if not _ok(fxs[j], slope_thr, chg_thr):
                    break
                if not _overlap_ok(fxs[start:j+1]):
                    break
                j += 1

            run = fxs[start:j]
            n_top = sum(1 for fx in run if fx.mark == "G")
            n_bot = sum(1 for fx in run if fx.mark == "D")

            if len(run) >= self.min_fx and n_top >= 2 and n_bot >= 2:
                gg = max(fx.high for fx in run)
                dd = min(fx.low for fx in run)
                full_hp = (gg - dd) / ((gg + dd) / 2) * 100
                zg = min(fx.high for fx in run if fx.mark == "G")
                zd = max(fx.low for fx in run if fx.mark == "D")
                nb = _idx(run[-1].dt) - _idx(run[0].dt) + 1
                hp = (zg - zd) / ((zg + zd) / 2) * 100 if zg > zd else 0

                if self.min_h_pct <= full_hp <= self.max_h_pct and zg > zd:
                    # 层3：确认时向前扩展1-2个分型（一次性，之后锁定）
                    orig_run = list(run)
                    orig_gg, orig_dd, orig_zg, orig_zd = gg, dd, zg, zd
                    orig_full_hp, orig_hp, orig_nb = full_hp, hp, nb
                    extended_count = _try_extend_back(start, run, gg, dd)
                    if extended_count > 0:
                        gg = max(fx.high for fx in run)
                        dd = min(fx.low for fx in run)
                        full_hp = (gg - dd) / ((gg + dd) / 2) * 100
                        zg = min(fx.high for fx in run if fx.mark == "G")
                        zd = max(fx.low for fx in run if fx.mark == "D")
                        nb = _idx(run[-1].dt) - _idx(run[0].dt) + 1
                        hp = (zg - zd) / ((zg + zd) / 2) * 100 if zg > zd else 0
                        if not (self.min_h_pct <= full_hp <= self.max_h_pct and zg > zd):
                            run = orig_run
                            gg, dd, zg, zd = orig_gg, orig_dd, orig_zg, orig_zd
                            full_hp, hp, nb = orig_full_hp, orig_hp, orig_nb
                            extended_count = 0

                    total_ext = extended_count + early_extended
                    ext_note = f"，前扩{total_ext}分型" if total_ext > 0 else ""
                    boxes.append({
                        "start": run[0].dt, "end": run[-1].dt,
                        "zg": zg, "zd": zd, "gg": gg, "dd": dd,
                        "n_fx": len(run), "n_bis": len(run) - 1,
                        "bars": nb, "h_pct": hp, "full_h_pct": full_hp,
                        "reason": f"{len(run)}分型增量(滚动窗口{self.window_size},斜率<={slope_thr:.3f}%/根,涨跌幅<={chg_thr:.1f}%)，全高{full_hp:.2f}%{ext_note}",
                    })
                    # 锁定：标记已确认范围，后续遍历跳过
                    for idx in range(start, j):
                        confirmed_ends.add(idx)

            i = j if j > start else start + 1

        return boxes




class BoxFinder(BoxFinderBase):
    """
    箱体/盘整识别器。所有参数在构造时配置，find() 方法执行识别。

    Parameters
    ----------
    slope_quantile : float
        斜率分位数（0~1），越小越严格
    chg_quantile : float
        绝对涨跌幅分位数（0~1），越小越严格
    min_fx : int
        箱体最少分型数
    min_h_pct : float
        箱体最小全高（%）
    max_h_pct : float
        箱体最大全高（%）
    """

    def __init__(self, slope_quantile=0.6, chg_quantile=0.6, min_fx=4,
                 min_h_pct=0.5, max_h_pct=50.0):
        self.slope_quantile = slope_quantile
        self.chg_quantile = chg_quantile
        self.min_fx = min_fx
        self.min_h_pct = min_h_pct
        self.max_h_pct = max_h_pct

    def find(self, fxs, bars, start_dt=None):
        """
        执行箱体识别。

        Parameters
        ----------
        fxs : list
            笔端点分型列表（按时间排序，已去重）
        bars : list
        start_dt : datetime, optional
            起始日期（全量算法忽略此参数）
            原始K线列表（RawBar）

        Returns
        -------
        list[dict]
            每个箱体含 start/end/zg/zd/gg/dd/n_fx/n_bis/bars/h_pct/full_h_pct/reason
        """
        dts = [b.dt for b in bars]

        def _idx(dt):
            return bisect.bisect_right(dts, dt) - 1

        tops = [fx for fx in fxs if fx.mark == "G"]
        bots = [fx for fx in fxs if fx.mark == "D"]
        if len(tops) < 2 or len(bots) < 2:
            return []

        slope_of = {}
        chg_of = {}
        for i in range(1, len(tops)):
            dpct = abs(tops[i].high - tops[i-1].high) / ((tops[i].high + tops[i-1].high) / 2) * 100
            dn = max(1, _idx(tops[i].dt) - _idx(tops[i-1].dt))
            slope_of[tops[i].dt] = dpct / dn
            chg_of[tops[i].dt] = dpct
        for i in range(1, len(bots)):
            dpct = abs(bots[i].low - bots[i-1].low) / ((bots[i].low + bots[i-1].low) / 2) * 100
            dn = max(1, _idx(bots[i].dt) - _idx(bots[i-1].dt))
            slope_of[bots[i].dt] = dpct / dn
            chg_of[bots[i].dt] = dpct

        all_slopes = sorted(slope_of.values())
        all_chgs = sorted(chg_of.values())
        slope_thr = all_slopes[int(len(all_slopes) * self.slope_quantile)] if all_slopes else 999
        chg_thr = all_chgs[int(len(all_chgs) * self.chg_quantile)] if all_chgs else 999

        def _ok(fx):
            if fx.dt not in slope_of:
                return True
            return slope_of[fx.dt] <= slope_thr and chg_of[fx.dt] <= chg_thr

        def _overlap_ok(run):
            t = [fx.high for fx in run if fx.mark == "G"]
            b = [fx.low for fx in run if fx.mark == "D"]
            if not t or not b:
                return True
            return min(t) > max(b)

        boxes = []
        i = 0
        while i < len(fxs):
            if _ok(fxs[i]):
                start = i
            else:
                k = i + 1
                cnt = 0
                while k < len(fxs) and _ok(fxs[k]):
                    cnt += 1
                    k += 1
                if cnt >= 3:
                    start = i
                else:
                    i += 1
                    continue

            j = start + 1
            # 第一步：先扩展到min_fx个分型
            while j < len(fxs) and j - start < self.min_fx:
                if not _ok(fxs[j]):
                    break
                if not _overlap_ok(fxs[start:j+1]):
                    break
                j += 1
            # 第二步：如果够min_fx个，提前向后扩展1个分型（按分型类型判断上下半区）
            early_extended = 0
            if j - start >= self.min_fx:
                temp_run = fxs[start:j]
                temp_gg = max(fx.high for fx in temp_run)
                temp_dd = min(fx.low for fx in temp_run)
                temp_mid = (temp_gg + temp_dd) / 2
                idx = start - 1
                if idx >= 0:
                    fx = fxs[idx]
                    fx_price = fx.high if fx.mark == "G" else fx.low
                    # 前一个分型(run[0])是顶分型→当前是底分型→应在下半区[DD,mid]
                    # 前一个分型是底分型→当前是顶分型→应在上半区[mid,GG]
                    first_fx = temp_run[0]
                    if first_fx.mark == "G":
                        # 当前是底分型，应在下半区
                        in_half = temp_dd <= fx_price <= temp_mid
                    else:
                        # 当前是顶分型，应在上半区
                        in_half = temp_mid <= fx_price <= temp_gg
                    if in_half:
                        start = idx
                        early_extended = 1
            # 第三步：继续扩展run到最大
            while j < len(fxs):
                if not _ok(fxs[j]):
                    break
                if not _overlap_ok(fxs[start:j+1]):
                    break
                j += 1
            run = fxs[start:j]
            n_top = sum(1 for fx in run if fx.mark == "G")
            n_bot = sum(1 for fx in run if fx.mark == "D")
            if len(run) >= self.min_fx and n_top >= 2 and n_bot >= 2:
                gg = max(fx.high for fx in run)
                dd = min(fx.low for fx in run)
                full_hp = (gg - dd) / ((gg + dd) / 2) * 100
                zg = min(fx.high for fx in run if fx.mark == "G")
                zd = max(fx.low for fx in run if fx.mark == "D")
                nb = _idx(run[-1].dt) - _idx(run[0].dt) + 1
                hp = (zg - zd) / ((zg + zd) / 2) * 100 if zg > zd else 0
                if self.min_h_pct <= full_hp <= self.max_h_pct and zg > zd:
                    # 向前扩展：箱体起点前1-2个分型，按分型类型判断上下半区
                    orig_run = list(run)
                    orig_gg, orig_dd, orig_zg, orig_zd = gg, dd, zg, zd
                    orig_full_hp, orig_hp, orig_nb = full_hp, hp, nb
                    extended_count = 0
                    final_mid = (gg + dd) / 2
                    for back in range(1, 3):
                        idx = start - back
                        if idx < 0:
                            break
                        fx = fxs[idx]
                        fx_price = fx.high if fx.mark == "G" else fx.low
                        # 前一个分型(run[0])是顶分型→当前是底分型→应在下半区[DD,mid]
                        # 前一个分型是底分型→当前是顶分型→应在上半区[mid,GG]
                        first_fx = run[0]
                        if first_fx.mark == "G":
                            in_half = dd <= fx_price <= final_mid
                        else:
                            in_half = final_mid <= fx_price <= gg
                        if in_half:
                            run.insert(0, fx)
                            extended_count += 1
                        else:
                            break
                    if extended_count > 0:
                        # 重新计算边界
                        gg = max(fx.high for fx in run)
                        dd = min(fx.low for fx in run)
                        full_hp = (gg - dd) / ((gg + dd) / 2) * 100
                        zg = min(fx.high for fx in run if fx.mark == "G")
                        zd = max(fx.low for fx in run if fx.mark == "D")
                        nb = _idx(run[-1].dt) - _idx(run[0].dt) + 1
                        hp = (zg - zd) / ((zg + zd) / 2) * 100 if zg > zd else 0
                        # 扩展后不满足条件则回退
                        if not (self.min_h_pct <= full_hp <= self.max_h_pct and zg > zd):
                            run = orig_run
                            gg, dd, zg, zd = orig_gg, orig_dd, orig_zg, orig_zd
                            full_hp, hp, nb = orig_full_hp, orig_hp, orig_nb
                            extended_count = 0
                    total_ext = extended_count + early_extended
                    ext_note = f"，前扩{total_ext}分型" if total_ext > 0 else ""
                    boxes.append({
                        "start": run[0].dt, "end": run[-1].dt,
                        "zg": zg, "zd": zd, "gg": gg, "dd": dd,
                        "n_fx": len(run), "n_bis": len(run) - 1,
                        "bars": nb, "h_pct": hp, "full_h_pct": full_hp,
                        "reason": f"{len(run)}分型双条件(斜率<={slope_thr:.3f}%/根,涨跌幅<={chg_thr:.1f}%)，全高{full_hp:.2f}%{ext_note}",
                    })
            i = j if j > start else start + 1
        return boxes
