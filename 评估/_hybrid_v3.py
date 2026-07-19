"""
周线选股+日线操作 混合回测 v3
直接复用 weekly_formula_backtest.py 的原版 F2 引擎 (257笔基准)
新增两条路径B/C：在原版F2持仓上加不同出场机制
"""
import sys, time
sys.path.insert(0, 'D:/Hermes/评估中心/tools/tdx_connector/scripts')
from weekly_formula_backtest import (load_all_daily, daily_to_weekly, compute_weekly_factors,
    load_benchmark, is_eligible, get_limit_ratio, FORMULAS, formula_2_main, run_formula_backtest)
import pandas as pd, numpy as np
from datetime import datetime

TDX='D:/TDX/vipdoc'; START='20230101'; END='20251231'; HOLD=30
COST=0.00232

t0=time.time()
print(f'=== 周线选股+日线操作 混合回测 (原版F2引擎)  {START}→{END} ===')

print('\n加载日K...')
daily=load_all_daily()
print('\n聚合周K...')
weekly=daily_to_weekly(daily)
print(f'  周K: {len(weekly)}只')
print('\n计算周线因子...')
factors=compute_weekly_factors(weekly)
print('\n加载基准...')
bench=load_benchmark(daily)
if bench is None: sys.exit(1)
bkey='000300'
for k in daily:
    if '000300' in k.upper(): bkey=k; break
print(f'  基准: {bkey}')
print(f'  准备完成, {time.time()-t0:.0f}s')

# ===== 路径A: 原版F2周选 + 固定20天 (baseline) =====
print('\n--- 路径A: F2周选 + 固定20天 ---')
hA, sA = run_formula_backtest(formula_2_main, 'F2_周线主进', weekly, daily, factors, bench,
                               hold_days=HOLD, top_k=20, start=START, end=END, realistic=False)
print(f'  A: {len(hA)}笔, skip={sA}')

# ===== 路径B: F2周选 → 固定20天 + MA20周线止损 =====
print('\n--- 路径B: F2周选 + 固定20天 + MA20止损 ---')
hB=[]
for x in hA:
    code=x['code']; T=x['T']
    dd=daily.get(code)
    if dd is None: continue
    f=factors.get(code, {})
    ma20_s=f.get('ma20')
    if ma20_s is None:
        hB.append(x); continue
    entry=x['entry']; exit_ts=x['T']+pd.Timedelta(days=HOLD)
    # 查找买入对应日K索引
    idx=dd.index; dd_sorted_idx=idx.searchsorted(T, side='left')
    if dd_sorted_idx<0 or dd_sorted_idx>=len(dd):
        hB.append(x); continue
    start_i=dd_sorted_idx+1 if dd_sorted_idx<len(dd)-1 else dd_sorted_idx
    stop_triggered=False
    for ci in range(start_i, min(start_i+HOLD+5, len(dd))):
        cd=idx[ci]
        if cd > exit_ts: break
        # 周线MA20前向填充
        last_ma=ma20_s[ma20_s.index<=cd].iloc[-1] if (ma20_s.index<=cd).any() else np.nan
        if pd.notna(last_ma) and dd.iloc[ci]['close']<last_ma*0.98:
            net=dd.iloc[ci]['close']/entry-1-COST
            hB.append({'T':T,'code':code,'entry':entry,'exit':dd.iloc[ci]['close'],'net':net,'bench':x.get('bench',np.nan),'stop':True})
            stop_triggered=True;break
    if not stop_triggered:
        hB.append(x)
print(f'  B: {len(hB)}笔, 其中止损{sum(1 for x in hB if x.get("stop"))}笔')

# ===== 路径C: F2周选 → 固定20天 + 日线wave下穿avg减仓50% =====
print('\n--- 路径C: F2周选 + 20天 + wave减仓50% ---')
# 预计算日线wave/avg
dinds={}
for code,df in daily.items():
    try:
        C=df['close'] if 'close' in df.columns else df['c']
        L=df['low'] if 'low' in df.columns else df['l']
        H=df['high'] if 'high' in df.columns else df['h']
        mn10=L.rolling(10).min();mx25=H.rolling(25).max()
        wave=((C-mn10)/(mx25-mn10+0.001)*4).ewm(span=4,adjust=False).mean()
        dinds[code]={'wave':wave,'avg':wave.ewm(span=3,adjust=False).mean()}
    except: pass
print(f'  日线wave/avg完成 {len(dinds)}只')

hC=[]
for x in hA:
    code=x['code']; entry=x['entry']
    dd=daily.get(code)
    di=dinds.get(code)
    if dd is None or di is None:
        hC.append({'net':x['net']}); continue
    idx=dd.index
    dd_sorted_idx=idx.searchsorted(x['T'], side='left')
    if dd_sorted_idx<0 or dd_sorted_idx>=len(dd):
        hC.append({'net':x['net']}); continue
    si=dd_sorted_idx+1 if dd_sorted_idx<len(dd)-1 else dd_sorted_idx
    # 满仓限价
    ei2=min(si+HOLD,len(idx)-1)
    full_price=dd.iloc[ei2]['close']
    if full_price<=0:
        hC.append({'net':x['net']}); continue
    # 寻找wave下穿avg（用iloc避免Series匹配问题）
    half_price=None
    wave_s=di['wave']; avg_s=di['avg']
    for j in range(si+2, min(si+HOLD+2, len(idx))):
        w=wave_s.iloc[j] if j<len(wave_s) else np.nan
        a=avg_s.iloc[j] if j<len(avg_s) else np.nan
        if pd.isna(w) or pd.isna(a): continue
        pw=wave_s.iloc[j-1] if j-1<len(wave_s) else np.nan
        if pd.notna(pw) and pw>a and w<=a:
            half_price=dd.iloc[j]['close'];break
    if half_price and half_price>0:
        h_n=half_price/entry-1-COST/2
        f_n=full_price/entry-1-COST
        net=(h_n+f_n)/2
    else:
        net=full_price/entry-1-COST
    hC.append({'net':net})
print(f'  C: {len(hC)}笔')

# ===== 汇总 =====
def summarize(name, hold):
    if not hold:
        return {'name':name,'N':0,'win':0,'mn':0,'annual':0}
    df=pd.DataFrame(hold)
    net_col='net' if 'net' in df.columns else 'exit'
    if 'net' not in df.columns:
        df['net']=df['exit']/df['entry']-1-COST
    win=(df.net>0).mean()*100
    mn=df.net.mean()*100
    span=(pd.Timestamp(END)-pd.Timestamp(START)).days/365.25
    nyr=len(df)/span
    annual=((1+mn/100)**nyr-1)*100
    print(f'  {name}: {len(df)}笔 胜率{win:.1f}% 单均{mn:.2f}% 年化{annual:.1f}%')
    return {'name':name,'N':len(df),'win':win,'mn':mn,'annual':annual}

results=[summarize('A: F2周选+固定20天',hA),
         summarize('B: F2周选+20天+MA20止损',hB),
         summarize('C: F2周选+20天+wave减仓50%',hC)]

print('\n'+'='*80)
print('周线选股+日线操作 混合回测 汇总')
print('='*80)
print(f'| {"策略":<40} | {"交易":>5} | {"胜率":>5} | {"单均净":>7} | {"年化":>7} |')
print('|'+'-'*42+'|'+'-'*7+'|'+'-'*7+'|'+'-'*9+'|'+'-'*9+'|')
for r in sorted(results,key=lambda x:x['annual'],reverse=True):
    print(f'| {r["name"]:<40} | {r["N"]:>5} | {r["win"]:>5.1f} | {r["mn"]:>7.2f} | {r["annual"]:>7.1f} |')
print(f'\n总耗时: {time.time()-t0:.0f}s')

ts=datetime.now().strftime('%Y%m%d_%H%M%S')
path=f'D:/Hermes/同中书门下/产出/weekly_daily_hybrid_{ts}.md'
with open(path,'w',encoding='utf-8') as f:
    f.write('# 周线选股+日线操作 混合回测报告\n\n')
    f.write(f'区间: {START}-{END} | 持仓: {HOLD}天 | 成本: {COST*100:.3f}%\n')
    f.write(f'基于: weekly_formula_backtest.py 原版 F2 引擎\n\n')
    f.write('| 策略 | 交易数 | 胜率% | 单均净% | 年化净% |\n')
    f.write('|------|--------|-------|---------|----------|\n')
    for r in sorted(results,key=lambda x:x['annual'],reverse=True):
        f.write(f'| {r["name"]} | {r["N"]} | {r["win"]:.1f} | {r["mn"]:.2f} | {r["annual"]:.1f} |\n')
    f.write(f'\n生成: {datetime.now()}  耗时: {time.time()-t0:.0f}s\n')
print(f'\n报告已保存: {path}')
