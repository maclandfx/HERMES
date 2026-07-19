"""
日线公式回测器 v3 — 全信号一次性向量化计算，避免逐日逐股循环

用法：
  python3 daily_formula_backtest.py --start 20230101 --end 20251231 --hold-days 20 --top-k 5

回测规则：
  - 信号日收盘价买入，持有N个自然日（遇停牌顺延）
  - 止损：任意日收盘价 < MA20×0.98
  - 大盘多头过滤：上证综指 > MA60 且 MA60 向上
  - top_k=5（按 R0+50日涨幅排序）
  - 成本 0.232% + 滑点 0.2%
  - 排除：指数、北交所
"""
import os, struct, time, argparse
import pandas as pd
import numpy as np

TDX = 'D:/TDX/vipdoc'
DIV = {'sh': 1000, 'sz': 10, 'bj': 100}
COST = 0.00232
SLIP = 0.002
STOP = 0.98

def parse_day(market, code6, div):
    p = os.path.join(TDX, market, 'lday', f'{market}{code6}.day')
    if not os.path.exists(p): return None
    with open(p, 'rb') as f: raw = f.read()
    rows = []
    for i in range(0, len(raw)-31, 32):
        try:
            d = struct.unpack('<I', raw[i:i+4])[0]
            o = struct.unpack('<I', raw[i+4:i+8])[0] / div
            h = struct.unpack('<I', raw[i+8:i+12])[0] / div
            l = struct.unpack('<I', raw[i+12:i+16])[0] / div
            c = struct.unpack('<I', raw[i+16:i+20])[0] / div
            v = struct.unpack('<Q', raw[i+20:i+28])[0]
            rows.append((d, o, h, l, c, v))
        except: break
    if not rows: return None
    return pd.DataFrame(rows, columns=['d','o','h','l','c','v']).set_index('d').sort_index()

def load_all():
    t0 = time.time(); data = {}
    for market, div in DIV.items():
        dp = os.path.join(TDX, market, 'lday')
        if not os.path.exists(dp): continue
        for fn in os.listdir(dp):
            if not fn.endswith('.day'): continue
            code6 = fn[len(market):-4]
            if market == 'bj': continue
            if code6[:4] in ('8800','8801','8802','3990'): continue
            full = f'{market.upper()}{code6}'
            df = parse_day(market, code6, div)
            if df is not None and len(df) >= 60:
                data[full] = df
    print(f'  有效: {len(data)} 只, {time.time()-t0:.0f}s')
    return data

def calc_ind(df):
    C,H,L,O,V = df.c,df.h,df.l,df.o,df.v
    ind = pd.DataFrame(index=df.index)
    ind['c']=C; ind['h']=H; ind['l']=L; ind['o']=O; ind['v']=V
    C_r = C.rolling
    # MA batch
    ma_dict = {}
    for p in [5,10,13,20,21,30,34,45,55,60,89,90,120,144,233]:
        ma_dict[f'ma{p}'] = C_r(p).mean()
    for k,v in ma_dict.items():
        ind[k] = v
    ind['ema3']=C.ewm(span=3,adjust=False).mean()
    ind['ema7']=C.ewm(span=7,adjust=False).mean()
    ind['dif'] = C.ewm(span=12,adjust=False).mean()-C.ewm(span=26,adjust=False).mean()
    ind['dea'] = ind['dif'].ewm(span=9,adjust=False).mean()
    ind['vma5']=V.rolling(5).mean()
    ind['vrat']=V/(ind['vma5']+0.01)
    L10=L.rolling(10).min(); H25=H.rolling(25).max()
    wave=((C-L10)/(H25-L10+0.001)*4).ewm(span=4,adjust=False).mean()
    ind['wave']=wave; ind['avg']=wave.ewm(span=3,adjust=False).mean()
    ind['r0']=((C-C.shift(1))/(C.shift(1)+0.001)*100)*ind['vrat']
    L60=L.rolling(60).min(); H60=H.rolling(60).max()
    ind['pos60']=(C-L60)/(H60-L60+0.001)*100
    L120=L.rolling(120).min(); H120=H.rolling(120).max()
    ind['pos120']=(C-L120)/(H120-L120+0.001)*100
    ind['dcz']=C.rolling(20).median()
    ind['pct']=C.pct_change()*100
    ind['ent']=(C-L)/(H-L+0.001)
    ind['rs50']=C.pct_change(periods=50)
    ind['atr20']=C.rolling(20).apply(lambda x: (x[0]-x[-1]).abs()).fillna(0)  # 简化
    ind['h15']=H.rolling(15).max(); ind['l15']=L.rolling(15).min()
    ind['v15_max']=V.rolling(15).max()
    return ind

# ---------- 信号计算（向量化，一次性算全量） ----------

def sig_yaogu(ind):
    """妖股爆发: wave*25>80"""
    return (ind['wave']*25 > 80)

def sig_huangjin_yan(ind):
    """黄金右侧严: CROSS(pos60, MA6) AND pos60<35 AND pos120<25"""
    pos60 = ind['pos60']
    retail = pos60.rolling(6).mean()
    cross = (pos60 > retail) & (retail >= retail.shift(1))
    return cross & (pos60 < 35) & (ind['pos120'] < 25)

def sig_wushuang5(ind):
    """终极无双5: rs50>3% + wave<3.5 + C>DCZ*0.98 + ent>0.5 + dif>-0.15"""
    return (ind['rs50']>0.03) & (ind['wave']<3.5) & (ind['c']>ind['dcz']*0.98) & \
           (ind['ent']>0.50) & (ind['dif']>-0.15)

def sig_zj20wj(ind):
    """主进20稳健: 主力攻击 + MA20向上 + C>MA20"""
    abs_sum = abs(ind['r0'].shift(1))+abs(ind['r0'].shift(2))+abs(ind['r0'].shift(3))\
              +abs(ind['r0'].shift(4))+abs(ind['r0'].shift(5))
    attack = (ind['r0'] - abs_sum/2 > 0) & (ind['avg'] > ind['avg'].shift(1))
    return attack & (ind['ma20'] > ind['ma20'].shift(1)) & (ind['c'] > ind['ma20'])

def sig_zj20g(ind):
    """主进20改: 主进20稳健 + avg<0.8 + C>MA5 + V>VMA5 + EMA3>EMA7 + L<=MA20*1.015"""
    return sig_zj20wj(ind) & (ind['avg']<0.8) & (ind['c']>ind['ma5']) & \
           (ind['v']>ind['vma5']) & (ind['ema3']>ind['ema7']) & (ind['l']<=ind['ma20']*1.015)

def _max(a, b):
    return a.clip(lower=b)

def sig_huangjin(ind):
    """黄金右侧: 四层全红+QX>0 + 资金攻击 + 主力进 + avg<2.5"""
    C=ind['c']
    ma45=ind['ma45']; ma90=ind['ma90']; ma30=ind['ma30']; ma60=ind['ma60']; ma120=ind['ma120']
    layers = (C>ma60) & (C>=ma120) & (C>_max(ma45, ma90)) & (C>_max(ma30, ma60))
    if not layers.any(): return layers
    ma_arr=[C>ind[f'ma{p}'] for p in [5,13,21,34,55,89,144,233]]
    qx=sum(ma_arr)-3.8
    pct=ind['pct']; ent=ind['ent']; dcz=ind['dcz']; vat=ind['vrat']
    attack=(pct>5)&(ent>0.04)&(dcz>dcz.shift(1))&(vat>1.5)\
           &(ind['ma20']>ind['ma20'].shift(1))&(C>ind['ma20'])
    main=(ind['r0']>0)&(ind['avg']>ind['avg'].shift(1))
    return layers & (qx>0) & attack & main & (ind['avg']<2.5)

def sig_jinpai(ind):
    """金牌狙击主力: 大资金多头 + 资金攻击"""
    return sig_huangjin(ind)

def sig_4wei(ind):
    """四维共振主起: 四层+QX>0 + 主力强入(A/B级)"""
    C=ind['c']
    ma45=ind['ma45']; ma90=ind['ma90']; ma30=ind['ma30']; ma60=ind['ma60']; ma120=ind['ma120']
    layers=(C>ma60)&(C>=ma120)&(C>_max(ma45,ma90))&(C>_max(ma30,ma60))
    if not layers.any(): return layers
    ma_arr=[C>ind[f'ma{p}'] for p in [5,13,21,34,55,89,144,233]]
    qx=sum(ma_arr)-3.8
    r0=ind['r0']; avg=ind['avg']; ma20=ind['ma20']; vrat=ind['vrat']; dcz=ind['dcz']
    A=(r0>0)&(avg>avg.shift(1))&(ma20>ma20.shift(1))&(C>ma20)&(vrat>1.5)&(C>dcz)
    B=(r0>0)&(avg>avg.shift(1))&(dcz>=dcz.shift(1))&(avg<2.3)&(~A)
    return layers & (qx>0) & (A|B)

def sig_dczzc(ind):
    """20日DCZ双回踩: 强势主线 + 筹码重叠 + MA20趋势 + 回踩 + 资金控盘 + 次级共振"""
    C=ind['c']; ma20=ind['ma20']; rs50=ind['rs50']; rs120=ind['rs120']
    low=ind['l']; vat=ind['vrat']; pct=ind['pct']
    dcz=ind['dcz']
    strong=(rs50>0.05)|(rs120>0.08)
    overlap=abs(ma20-dcz)/(dcz+0.001)*100 < 8.0
    ma20_up=ma20 >= ma20.shift(1)*0.995
    c_above=C > ma20*0.98
    dcz_up=C > dcz*0.98
    l_down=(low <= ma20*1.015) & (C >= dcz*0.96)
    fund=(pct>1.0)&(pct<8.5)&(vat>0.9)
    sub=(C>ind['ema3'])&(ind['ema3']>ind['ma5'])
    return strong&overlap&ma20_up&c_above&dcz_up&l_down&fund&sub

def sig_qzjs(ind):
    """强主进精选: 主力进 + DCZ升 + 放量 + 站上DCZ + 花神红"""
    r0=ind['r0']; avg=ind['avg']; dcz=ind['dcz']; vrat=ind['vrat']; C=ind['c']
    main=(r0>0)&(avg>=avg.shift(1))&(avg.shift(1)<avg.shift(2))
    return main&(dcz>dcz.shift(5))&(C>=dcz)&(vrat>1.5)&(ind['ema3']>ind['ema7'])

def sig_tiemu(ind):
    """铁血埋伏: 核心趋势<42 + 勾头 + 中线底气 + 有过攻击 + 活跃度"""
    C=ind['c']; dif=ind['dif']; ma20=ind['ma20']; atr=ind['atr20']
    ma45=ind['ma45']; ma90=ind['ma90']; ma30=ind['ma30']; ma60=ind['ma60']
    core=50+20*(dif-ma20)/(atr+0.0001)
    core_p=50+20*(dif.shift(1)-ma20.shift(1))/(atr.shift(1)+0.0001)
    core_p2=50+20*(dif.shift(2)-ma20.shift(2))/(atr.shift(2)+0.0001)
    hook=(core>core_p)&(core_p<=core_p2)
    mid=(C>_max(ma45,ma90))&(C>_max(ma30,ma60))
    # 有过攻击: 15日内 pct>5 & ent>0.04 & vrat>1.5
    attack15=((ind['pct']>5)&(ind['ent']>0.04)&(ind['vrat']>1.5)).rolling(15).sum()>0
    act=(atr/(C+0.001)>0.04)
    return (core<42)&hook&mid&attack15&act

def sig_obv(ind):
    """主进OBV共振: MACD金叉 + 资金共振 + 20线多头 + DCZ守护"""
    C=ind['c']; ma20=ind['ma20']; dcz=ind['dcz']
    dif=ind['dif']; dea=ind['dea']
    jc=(dif>dea)&(dif.shift(1)<=dea.shift(1))
    zls=(ind['vrat']>1.1)&(ind['pct']>1.0)
    m20=(C>ma20)&(ma20>=ma20.shift(1))
    return jc&zls&m20&(C>dcz)

# ---------- 回测 ----------

def run_backtest_signals(signal_fn, name, inds, bull_dates, start, end, hold_days=20, top_k=5):
    """
    1. 一次性向量化计算全市场信号
    2. 按日期汇总，top_k选股
    3. 逐只算 entry/exit + 止损
    """
    # Step 1: 全量信号
    sig_frames = []
    for code, ind in inds.items():
        s = signal_fn(ind)
        if s.any():
            dates = s[s].index
            for ts in dates:
                sig_frames.append((code, int(ts)))
    if not sig_frames:
        return [], {'公式': name, '交易数': 0, '胜率': 0, '单均净%': 0, '年化净%': 0}

    # Step 2: 按日期汇总，过滤大盘多头 + start-end
    from collections import defaultdict
    day_pool = defaultdict(list)
    for code, ts in sig_frames:
        if ts < start or ts > end: continue
        if ts not in bull_dates: continue
        ind = inds[code]
        if ts not in ind.index: continue
        c = ind.loc[ts, 'c']
        cp = ind.loc[ts-1, 'c'] if ts-1 in ind.index else 0
        if cp > 0 and c >= cp * 1.095: continue  # 涨停跳过
        r0 = ind.loc[ts, 'r0'] if ts in ind['r0'].index else 0
        rs50 = ind.loc[ts, 'rs50'] if ts in ind['rs50'].index else 0
        score = (r0 if pd.notna(r0) else 0) + abs(rs50)*100 if pd.notna(rs50) else 0
        day_pool[ts].append((code, score))

    # Step 3: top_k
    selected = set()  # (code, ts)
    for ts in day_pool:
        day_pool[ts].sort(key=lambda x: x[1], reverse=True)
        for code, score in day_pool[ts][:top_k]:
            selected.add((code, ts))

    # Step 4: 逐只算 entry/exit
    holdings = []
    for code, ts in selected:
        ind = inds[code]
        entry = ind.loc[ts, 'c']
        ma20s = ind['ma20']
        cd = ts + 1
        days = 0
        exit_c = None; exit_d = None
        # 找下一个交易日
        while cd not in ind.index and cd < end + 300: cd += 1
        if cd >= end + 300: continue
        while days < hold_days and cd in ind.index:
            c = ind.loc[cd, 'c']
            ma20v = ma20s.loc[cd] if cd in ma20s.index else 0
            if ma20v > 0 and c < ma20v * STOP:
                exit_c = c; exit_d = cd; break
            days += 1
            cd += 1
            while cd not in ind.index and cd < end + 300: cd += 1
        if exit_c is None:
            if cd in ind.index:
                exit_c = ind.loc[cd, 'c']; exit_d = cd
            else: continue
        if exit_c <= 0: continue
        net = exit_c/entry - 1 - COST - SLIP
        holdings.append({'code': code, 'T': ts, 'exit': exit_d,
                         'entry': entry, 'exit_c': exit_c, 'net': net})

    if not holdings:
        return [], {'公式': name, '交易数': 0, '胜率': 0, '单均净%': 0, '年化净%': 0}

    df = pd.DataFrame(holdings)
    win = (df['net']>0).mean()*100
    mean_net = df['net'].mean()*100
    span = (end-start)/365.0
    nyr = len(df)/span if span > 0 else 1
    annual = ((1+df['net'].mean())**nyr-1)*100
    return holdings, {'公式': name, '交易数': len(df), '胜率': round(win,1),
                      '单均净%': round(mean_net,2), '年化净%': round(annual,1)}

# ---------- 主 ----------

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='20230101')
    ap.add_argument('--end', default='20251231')
    ap.add_argument('--hold-days', type=int, default=20)
    ap.add_argument('--top-k', type=int, default=5)
    args = ap.parse_args()
    start, end = int(args.start), int(args.end)
    t0 = time.time()

    print('='*60)
    print(f'日线公式回测器 v3  区间:{args.start}→{args.end}  持仓:{args.hold_days}天  top_k={args.top_k}')
    print('='*60)

    print('[1/3] 加载日K...')
    daily = load_all()
    print('[2/3] 计算指标...')
    inds = {}
    for i,(code,df) in enumerate(daily.items()):
        inds[code] = calc_ind(df)
        if (i+1)%2000==0: print(f'  {i+1}/{len(daily)}', end='\r')
    print(f'  {len(inds)} 只')

    # 大盘多头
    idx = parse_day('sh','000001',1000)
    if idx is not None:
        idx_c = idx['c']
        ma60 = idx_c.rolling(60).mean()
        if ma60.notna().sum() < 10: ma60 = idx_c.rolling(30).mean()
        bull = ((idx_c > ma60) & (ma60 > ma60.shift(5))).astype(int)
        bull_dates = set(bull[bull==1].index.astype(int))
    else:
        bull_dates = set()
    print(f'[2/3] 大盘多头日期: {len(bull_dates)}')

    formulas = [
        ('妖股爆发', sig_yaogu),
        ('黄金右侧严', sig_huangjin_yan),
        ('终极无双5', sig_wushuang5),
        ('主进20稳健', sig_zj20wj),
        ('主进20改', sig_zj20g),
        ('黄金右侧', sig_huangjin),
        ('金牌狙击主力', sig_jinpai),
        ('四维共振主起', sig_4wei),
        ('20日DCZ双回踩', sig_dczzc),
        ('主进OBV共振', sig_obv),
        ('铁血埋伏', sig_tiemu),
        ('强主进精选', sig_qzjs),
    ]

    print('[3/3] 执行回测...')
    results = []
    for name, fn in formulas:
        h, s = run_backtest_signals(fn, name, inds, bull_dates, start, end,
                                    hold_days=args.hold_days, top_k=args.top_k)
        results.append(s)
        print(f'  {name}: {s["交易数"]}笔  胜率{s["胜率"]}%  单均{s["单均净%"]}  年化{s["年化净%"]}')

    print('\n'+ '='*75)
    print('各公式横向对比')
    print('='*75)
    print(f'| {"公式":<16} | {"交易":>5} | {"胜率":>5} | {"单均净":>7} | {"年化":>7} |')
    print('|'+'-'*18+'|'+'-'*7+'|'+'-'*7+'|'+'-'*9+'|'+'-'*9+'|')
    for r in sorted(results, key=lambda x: x['年化净%'], reverse=True):
        print(f'| {r["公式"]:<16} | {r["交易数"]:>5} | {r["胜率"]:>5.1f} | {r["单均净%"]:>7.2f} | {r["年化净%"]:>7.1f} |')

    print(f'\n总耗时: {time.time()-t0:.0f}s')

    ts = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
    path = f'daily_formula_backtest_{ts}.md'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'# 日线公式回测报告\n\n')
        f.write(f'区间: {args.start}-{args.end} | 持仓: {args.hold_days}天 | top_k={args.top_k}\n\n')
        f.write('| 公式 | 交易数 | 胜率% | 单均净% | 年化净% |\n')
        f.write('|------|--------|-------|---------|----------|\n')
        for r in sorted(results, key=lambda x: x['年化净%'], reverse=True):
            f.write(f'| {r["公式"]} | {r["交易数"]} | {r["胜率"]:.1f} | {r["单均净%"]:.2f} | {r["年化净%"]:.1f} |\n')
        f.write(f'\n生成: {pd.Timestamp.now()}  耗时: {time.time()-t0:.0f}s\n')
    print(f'\n报告: {path}')
