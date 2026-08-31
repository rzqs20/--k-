import re, json
h = open(r'D:/量化k线/reports/000001_SZ_日线_20260824.html', encoding='utf-8').read()
m = re.search(r'var DATA = (\{.*?\});', h, re.S)
d = json.loads(m.group(1))
labels = d['catLabels']
print('K线数:', len(d['kline']), '| 区间:', labels[0], '~', labels[-1])
print()
print('== 所有中枢 ==')
for i, area in enumerate(d['zsAreas']):
    p1, p2 = area[0], area[1]
    s, e = p1['xAxis'], p2['xAxis']
    zg, zd = p1['yAxis'], p2['yAxis']
    print(f'中枢{i+1}: 索引[{s},{e}] 时间[{labels[s]} ~ {labels[e]}] 区间[{zd}, {zg}]')
print()
print('== 笔线（端点索引+价格）==')
bis = d['biLine']
for i in range(0, len(bis), 2):
    p1, p2 = bis[i], bis[i+1]
    print(f'笔{i//2+1}: [{p1[0]}]{labels[p1[0]]} {p1[1]} -> [{p2[0]}]{labels[p2[0]]} {p2[1]}')
