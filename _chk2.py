# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
d = open(r'D:/量化k线/czsc_report.py', encoding='utf-8').read()
print('has render_echarts:', 'def render_echarts' in d)
print('has def main:', 'def main()' in d)
print('has render_html:', 'def render_html' in d)
i = d.find('# ---- 4)')
if i >= 0:
    print('=== section 4 ===')
    print(d[i:i+700])
else:
    print('no section4 marker; find 4)')
    j = d.find('4) HTML')
    print(d[j-100:j+500] if j >= 0 else 'none')
