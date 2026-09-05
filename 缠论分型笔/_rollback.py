# -*- coding: utf-8 -*-
"""回滚 find_boxes 到无跳点版本"""
p = r'D:\量化k线\缠论分型笔\core\chan_analyzer.py'
with open(p, encoding='utf-8') as f:
    c = f.read()

# 1. 函数签名恢复
old_sig = "    def find_boxes(self, slope_quantile=0.6, chg_quantile=0.6, min_fx=4,\n                   min_h_pct=0.5, max_h_pct=50.0, max_skip=1, max_span=15):"
new_sig = "    def find_boxes(self, slope_quantile=0.6, chg_quantile=0.6, min_fx=4,\n                   min_h_pct=0.5, max_h_pct=50.0):"
assert old_sig in c, "sig not found"
c = c.replace(old_sig, new_sig)

# 2. docstring 恢复
old_doc = """          6. 整体高度(GG-DD)在 [min_h_pct, max_h_pct]% → 成立
          7. 跳点容错：遇到斜率过大的异常分型时，允许跳过它看下下个同类型分型，
             若回归平缓则把异常点包含进箱体（每箱体最多 max_skip 个跳点）
          8. 跳点跨度限制：跳过的两个同类型分型之间K线数超过 max_span 则跳点无效"""
new_doc = "          6. 整体高度(GG-DD)在 [min_h_pct, max_h_pct]% → 成立"
assert old_doc in c, "doc not found"
c = c.replace(old_doc, new_doc)

# 3. 扩展循环恢复成简单版本
old_loop = """            j = start + 1
            skip_count = 0
            exempt = set()
            while j < len(fxs):
                fx = fxs[j]
                fx_ok = _ok(fx) or fx.dt in exempt
                if not fx_ok:
                    jumped = False
                    if skip_count < max_skip:
                        nxt = None
                        for k in range(j+1, len(fxs)):
                            if fxs[k].mark == fx.mark:
                                nxt = fxs[k]
                                break
                        prv = None
                        for k in range(j-1, start-1, -1):
                            if fxs[k].mark == fx.mark:
                                prv = fxs[k]
                                break
                        if nxt is not None and prv is not None:
                            if fx.mark == "G":
                                dpct = abs(nxt.high - prv.high) / ((nxt.high + prv.high) / 2) * 100
                            else:
                                dpct = abs(nxt.low - prv.low) / ((nxt.low + prv.low) / 2) * 100
                            dn = max(1, _idx(nxt.dt) - _idx(prv.dt))
                            if dpct / dn <= slope_thr and dpct <= chg_thr and dn <= max_span:
                                if _overlap_ok(fxs[start:j+1]):
                                    skip_count += 1
                                    exempt.add(nxt.dt)
                                    jumped = True
                                    j += 1
                    if not jumped:
                        break
                    continue
                if not _overlap_ok(fxs[start:j+1]):
                    break
                j += 1"""
new_loop = """            j = start + 1
            while j < len(fxs):
                if not _ok(fxs[j]):
                    break
                if not _overlap_ok(fxs[start:j+1]):
                    break
                j += 1"""
assert old_loop in c, "loop not found"
c = c.replace(old_loop, new_loop)

# 4. reason 恢复
old_reason = '''                        "reason": f"{len(run)}分型双条件(斜率<={slope_thr:.3f}%/根,涨跌幅<={chg_thr:.1f}%)，跳点{skip_count}(跨度<={max_span})，全高{full_hp:.2f}%",'''
new_reason = '''                        "reason": f"{len(run)}分型双条件(斜率<={slope_thr:.3f}%/根,涨跌幅<={chg_thr:.1f}%)，全高{full_hp:.2f}%",'''
assert old_reason in c, "reason not found"
c = c.replace(old_reason, new_reason)

with open(p, 'w', encoding='utf-8') as f:
    f.write(c)
print("done: 已回滚到无跳点版本")
