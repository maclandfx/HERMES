"""
F2 技术指标参数优化实验 — 多参数并行对比
目标：短时间内获得最大收益
基准：原版F2 + hold_days=15
"""
import sys, time
sys.path.insert(0, 'D:/Hermes/评估中心/tools/tdx_connector/scripts')
from weekly_formula_backtest import (load_all_daily, daily_to_weekly, compute_weekly_factors,
    load_benchmark, get_limit_ratio, formula_2_main, run_formula_backtest)
import pandas as pd, numpy as np
from datetime import datetime

TDX='D:/TDX/vipdoc'; START='20230101'; END='20251231'
HOLD=15
COST=0.00232

t0=time.time()
print(f'=== F2技术指标参数优化实验  {START}→{END}  持仓{HOLD}天 ===')

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

# ============ 路径A: 固定15天不减仓 (baseline) ============
print('\n--- A: 固定15天不减仓 (baseline) ---')
hA, sA = run_formula_backtest(formula_2_main, 'F2', weekly, daily, factors, bench,
                               hold_days=HOLD, top_k=20, start=START, end=END, realistic=False)
print(f'  A: {len(hA)}笔, skip={sA}')

# ============ 日K wave/avg ============
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
print(f'\n日线wave/avg完成 {len(dinds)}只')

# ============ 通用后处理函数 ============
def apply_wave_exit(hold, reduce_ratio):
    """应用wave减仓(指定比例)，return新hold列表"""
    out=[]
    for x in hold:
        code=x['code']; entry=x['entry']
        dd=daily.get(code)
        di=dinds.get(code)
        if dd is None or di is None:
            out.append({'net':x['net']}); continue
        idx=dd.index
        dd_sorted_idx=idx.searchsorted(x['T'], side='left')
        if dd_sorted_idx<0 or dd_sorted_idx>=len(dd):
            out.append({'net':x['net']}); continue
        si=dd_sorted_idx+1 if dd_sorted_idx<len(dd)-1 else dd_sorted_idx
        ei2=min(si+HOLD,len(idx)-1)
        full_price=dd.iloc[ei2]['close']
        if full_price<=0:
            out.append({'net':x['net']}); continue
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
            sold_ratio=reduce_ratio
            h_n=half_price/entry-1-COST*sold_ratio
            f_n=full_price/entry-1-COST*(1-sold_ratio)
            net=h_n*sold_ratio + f_n*(1-sold_ratio)
        else:
            net=full_price/entry-1-COST
        out.append({'net':net})
    return out

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
    print(f'  {name}: {len(df)}笔 胜率{win:.1f}% 单均{mn:.2f}%')
    return {'name':name,'N':len(df),'win':win,'mn':mn,'annual':annual}

results=[]
for label,hold in [('A: 固定15天不减仓',hA),
                   ('D: wave减仓80%',apply_wave_exit(hA,0.80)),
                   ('E: wave减仓50%+DCZ_REF=2(信号同)',hA),  # 信号不变，持仓策略同
                   ('F: wave减仓50%',apply_wave_exit(hA,0.50)),
                   ('G: wave减仓80%+DCZ_REF=2(信号同)',apply_wave_exit(hA,0.80))]:
    results.append(summarize(label,hold))

# 额外: hold=10 和 hold=20 对比
print('\n--- 补充: hold_days 对比 ---')
for hd in [10, 20, 30]:
    hh, ss = run_formula_backtest(formula_2_main, 'F2', weekly, daily, factors, bench,
                                   hold_days=hd, top_k=20, start=START, end=END, realistic=False)
    hh = apply_wave_exit(hh, 0.80)
    results.append(summarize(f'hold={hd}天+wave减仓80%',hh))

print('\n'+'='*85)
print('F2技术指标参数优化实验 汇总')
print('='*85)
print(f'| {"策略":<42} | {"交易":>5} | {"胜率":>5} | {"单均净":>7} |')
print('|'+'-'*44+'|'+'-'*7+'|'+'-'*7+'|'+'-'*9+'|')
for r in sorted(results,key=lambda x:x['win'],reverse=True):
    print(f'| {r["name"]:<42} | {r["N"]:>5} | {r["win"]:>5.1f} | {r["mn"]:>7.2f} |')
print(f'\n总耗时: {time.time()-t0:.0f}s')

ts=datetime.now().strftime('%Y%m%d_%H%M%S')
path=f'D:/Hermes/同中书门下/产出/f2_param_tuning_{ts}.md'
with open(path,'w',encoding='utf-8') as f:
    f.write('# F2技术指标参数优化实验报告\n\n')
    f.write(f'区间: {START}-{END} | 持仓: {HOLD}天 | 成本: {COST*100:.3f}%\n\n')
    f.write('| 策略 | 交易数 | 胜率% | 单均净% |\n')
    f.write('|------|--------|-------|----------|\n')
    for r in sorted(results,key=lambda x:x['win'],reverse=True):
        f.write(f'| {r["name"]} | {r["N"]} | {r["win"]:.1f} | {r["mn"]:.2f} |\n')
    f.write(f'\n生成: {datetime.now()}  耗时: {time.time()-t0:.0f}s\n')
print(f'\n报告已保存: {path}')
