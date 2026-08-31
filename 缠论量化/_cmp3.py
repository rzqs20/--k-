# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r'D:/量化k线/缠论量化')
sys.path.insert(0, r'D:/量化k线')
import data_loader
import chan_trend as old
from chan.include import process_inclusion as new_inc, remove_include as new_rem
from chan.fenxing import check_fxs as new_fxs

sym, freq, ks, pre = data_loader.load_bars('601088.SH', '日线', '2023-01-01', '2026-08-24')
old_bars = [old.RawBar(sym, k.time, k.open, k.close, k.high, k.low, k.volume, k.amount) for k in ks]

# 旧程序：独立去包含（CZSC 流程）+ check_fxs
ubi_old = []
for b in old_bars:
    if len(ubi_old) < 2:
        ubi_old.append(old.NewBar.from_raw(b))
    else:
        has_inc, merged = old.remove_include(ubi_old[-2], ubi_old[-1], b)
        if has_inc:
            ubi_old[-1] = merged
        else:
            ubi_old.append(old.NewBar.from_raw(b))
fxs_old = old.check_fxs(ubi_old)
print('旧: 去包含K线=%d 分型=%d' % (len(ubi_old), len(fxs_old)))

# 新程序（已复制逻辑）
kl_new = new_inc(ks)
fxs_new = new_fxs(kl_new)
print('新: 去包含K线=%d 分型=%d' % (len(kl_new), len(fxs_new)))

# 对比前 15 个
print()
for i in range(min(15, len(fxs_old), len(fxs_new))):
    o = fxs_old[i]
    n = fxs_new[i]
    od = '顶' if o.mark == 'G' else '底'
    nd = '顶' if n.type == 'top' else '底'
    same = (od == nd and abs(o.fx - n.price) < 0.001 and o.dt == n.time)
    print('%2d %s %s %.3f | %s %s %.3f %s' % (i, od, o.dt.strftime('%m-%d'), o.fx, nd, n.time.strftime('%m-%d'), n.price, 'OK' if same else 'DIFF'))
