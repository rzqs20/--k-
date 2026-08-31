# -*- coding: utf-8 -*-
import sys, os, zipfile, shutil
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

whl = os.path.join(os.environ['TEMP'], 'czsc_wheel', 'czsc-1.0.1-cp310-abi3-win_amd64.whl')
src  = 'D:/量化k线/缠论仓库/czsc-master/czsc/utils/plotting/lightweight/'

tmp = os.path.join(os.environ['TEMP'], 'czsc_extract')
if os.path.exists(tmp):
    shutil.rmtree(tmp)
os.makedirs(tmp)
with zipfile.ZipFile(whl) as z:
    z.extractall(tmp)

# 只恢复被我补丁污染过的 3 个文件
files = [
    'czsc/utils/plotting/lightweight/_data.py',
    'czsc/utils/plotting/lightweight/_html_renderer.py',
    'czsc/utils/plotting/lightweight/__init__.py',
]
for f in files:
    s = os.path.join(tmp, f)
    d = os.path.join(src, os.path.basename(f))
    if os.path.exists(s):
        shutil.copyfile(s, d)
        print('已恢复官方原版:', os.path.basename(f))
    else:
        print('MISSING:', f)
print('DONE')