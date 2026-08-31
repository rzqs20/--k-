# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r'D:/量化k线/缠论量化')
import data_loader
from chan.pipeline import run_pipeline
for code, sdt, edt in [('601088.SH', '2023-01-01', '2026-08-24'), ('000001.SZ', '2024-01-01', '2026-08-24')]:
    sym, freq, ks, pre = data_loader.load_bars(code, '日线', sdt, edt)
    r = run_pipeline(ks)
    up = sum(1 for b in r['bis'] if b.is_up)
    print('%s: 分型%d 笔%d(上%d下%d) 中枢%d 走势%d 背驰%d 买卖点%d' % (code, len(r['fxs']), len(r['bis']), up, len(r['bis'])-up, len(r['zhongshu']), len(r['trends']), len(r['beichis']), len(r['bs_points'])))
    for p in r['bs_points'][:8]:
        print('   ', p.type, p.time.strftime('%Y-%m-%d'), p.price, 'inv=' + str(p.invalid), '|', p.desc[:50])
    print()
