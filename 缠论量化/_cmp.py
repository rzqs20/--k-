# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r'D:/量化k线/缠论量化')
sys.path.insert(0, r'D:/量化k线')
import data_loader
import chan_trend as old  # 旧程序

# 新程序模块
from chan.include import process_inclusion as new_include
from chan.fenxing import find_fenxing as new_fx

sym, freq, ks, pre = data_loader.load_bars('601088.SH', '日线', '2023-01-01', '2026-08-24')

# 旧程序：CZSC 方式去包含 + check_fxs
old_bars = [old.RawBar(sym, k.time, k.open, k.close, k.high, k.low, k.volume, k.amount) for k in ks]
old_c = old.CZSC(old_bars)
old_ubi = old_c.bars_ubi
old_fxs = old.check_fxs(old_ubi)
print('旧程序: bars_ubi=%d, 分型=%d' % (len(old_ubi), len(old_fxs)))

# 新程序
new_kl = new_include(ks)
new_fxs = new_fx(new_kl)
print('新程序: 处理后K线=%d, 分型=%d' % (len(new_kl), len(new_fxs)))

# 对比前 20 个分型
print()
print('idx 旧分型(时间/价格) vs 新分型')
for i in range(min(20, len(old_fxs), len(new_fxs))):
    o = old_fxs[i]
    n = new_fxs[i]
    od = '顶' if o.mark == 'G' else '底'
    nd = '顶' if n.type == 'top' else '底'
    same = (od == nd and abs(o.fx - n.price) < 0.001)
    print('%2d %s %s %.3f | %s %s %.3f %s' % (i, od, o.dt.strftime('%m-%d'), o.fx, nd, n.time.strftime('%m-%d'), n.price, 'OK' if same else 'DIFF'))
