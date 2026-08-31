# -*- coding: utf-8 -*-
import sys, hashlib, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
site = r'C:\Users\xyz\AppData\Local\Programs\Python\Python310\lib\site-packages\czsc\utils\plotting\lightweight'
src  = r'D:\量化k线\缠论仓库\czsc-master\czsc\utils\plotting\lightweight'
def h(p):
    return hashlib.md5(open(p,'rb').read()).hexdigest()[:12]
print("文件                    site(官方)     src(仓库)     状态")
for f in ['_data.py', '_html_renderer.py', '__init__.py']:
    ha = h(os.path.join(site, f))
    hb = h(os.path.join(src, f))
    mark = "一致 ✅" if ha == hb else "不一致 ❌"
    print(f"{f:<22} {ha}  {hb}  {mark}")
# 确认仓库无补丁残留
txt = open(os.path.join(src, '_data.py'), encoding='utf-8').read()
print()
print("仓库 _data.py 含 zs_lines:", 'zs_lines' in txt)
print("仓库 _data.py 含 bs_markers:", 'bs_markers' in txt)
txt2 = open(os.path.join(src, '_html_renderer.py'), encoding='utf-8').read()
print("仓库 _html_renderer.py 含 createPriceLine:", 'createPriceLine' in txt2)
