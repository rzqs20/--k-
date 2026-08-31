# -*- coding: utf-8 -*-
import sys, hashlib, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
site = r'C:\Users\xyz\AppData\Local\Programs\Python\Python310\lib\site-packages\czsc\utils\plotting\lightweight'
src  = r'D:\量化k线\缠论仓库\czsc-master\czsc\utils\plotting\lightweight'
def h(p):
    return hashlib.md5(open(p,'rb').read()).hexdigest()[:12]
print("文件                    site(官方)     src(仓库)")
for f in ['_data.py', '_html_renderer.py', '__init__.py', '_theme.py', '_signals.py']:
    a = os.path.join(site, f)
    b = os.path.join(src, f)
    ha = h(a) if os.path.exists(a) else 'N/A'
    hb = h(b) if os.path.exists(b) else 'N/A'
    mark = "一致 ✅" if ha == hb and ha != 'N/A' else "不一致 ❌"
    print(f"{f:<22} {ha}  {hb}  {mark}")
# 检查仓库里是否残留补丁痕迹
txt = open(os.path.join(src, '_data.py'), encoding='utf-8').read()
print()
print("仓库 _data.py 含 zs_lines:", 'zs_lines' in txt)
txt2 = open(os.path.join(src, '_html_renderer.py'), encoding='utf-8').read()
print("仓库 _html_renderer.py 含 createPriceLine:", 'createPriceLine' in txt2)
