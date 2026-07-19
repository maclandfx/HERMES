"""
F2入场时机对比：周五收盘买 vs 周一开盘买
基于239笔F2信号池，修正后的净收益计算
"""
import sys, time
sys.path.insert(0, 'D:/Hermes/评估中心/tools/tdx_connector/scripts')
from weekly_formula_backtest import (load_all_daily, daily_to_weekly, compute_weekly_factors,
    load_benchmark, formula_2_main, run_formula_backtest)
import pandas as pd, numpy as np
from datetime import datetime

TDX='D:/TDX/vipdoc'; START='20230101'; END='20251231'
HOLD=15
COST=0.00232

t0=time.time()
print(f'=== F2入场时机: 周五收盘 vs 周一开盘  {START}→{END} ===')

daily=load_all_daily()
weekly=daily_to_weekly(daily)
factors=compute_weekly_factors(weekly)
bench=load_benchmark(daily)
if bench is None: sys.exit(1)

print('\n--- 跑F2信号池 ---')
hA, sA = run_formula_backtest(formula_2_main, 'F2', weekly, daily, factors, bench,
                               hold_days=HOLD, top_k=20, start=START, end=END, realistic=False)
print(f'  信号池: {len(hA)}笔')

monday_open_nets = []
friday_close_nets = []
friday_delay_nets = []
stats = {'fri_up':0, 'fri_down':0, 'gap_up':0, 'gap_down':0}

for x in hA:
    code=x['code']; T=x['T']
    dd=daily.get(code)
    if dd is None: continue
    idx=dd.index
    mon_idx=idx.searchsorted(T, side='left')
    if mon_idx<0 or mon_idx>=len(idx): continue
    
    monday_open=dd.iloc[mon_idx]['open']
    friday_idx=mon_idx-1
    if friday_idx<0: continue
    friday_close=dd.iloc[friday_idx]['close']
    
    # 跳空
    gap_pct=(monday_open-friday_close)/friday_close*100
    if gap_pct>1: stats['gap_up']+=1
    elif gap_pct<-1: stats['gap_down']+=1
    fri_to_mon=(monday_open-friday_close)/friday_close*100
    if fri_to_mon>0: stats['fri_up']+=1
    else: stats['fri_down']+=1
    
    # 出口
    exit_date=T+pd.Timedelta(days=HOLD)
    ei=idx.searchsorted(exit_date, side='left')
    if ei>=len(idx): ei=len(idx)-1
    exit_price=dd.iloc[ei]['close']
    if exit_price<=0 or monday_open<=0 or friday_close<=0: continue
    
    # 策略1: 周一开盘买
    net1=(exit_price/monday_open)-1-COST
    # 策略2: 周五收盘买
    net2=(exit_price/friday_close)-1-COST
    # 策略3: 周五收盘买，周一低开>2%则周一开盘买
    if gap_pct<-2:
        entry3=monday_open
    else:
        entry3=friday_close
    net3=(exit_price/entry3)-1-COST
    
    monday_open_nets.append({'net':net1,'gap':gap_pct,'code':code})
    friday_close_nets.append({'net':net2,'gap':gap_pct,'code':code})
    friday_delay_nets.append({'net':net3,'gap':gap_pct,'code':code})

print(f'\n周五→周一跳空: 涨{stats["fri_up"]}笔 跌{stats["fri_down"]}笔')
print(f'周一跳空(±1%): 高开{stats["gap_up"]}笔 低开{stats["gap_down"]}笔')

print('\n'+'='*85)
print('F2入场时机: 周五收盘 vs 周一开盘')
print('='*85)
print(f'| {"策略":<45} | {"交易":>5} | {"胜率":>5} | {"单均净":>7} | {"中位数":>7} |')
print('|'+'-'*47+'|'+'-'*7+'|'+'-'*7+'|'+'-'*9+'|'+'-'*9+'|')

results=[]
for label,data in [
    ('1. 周一开盘价买入(baseline)',monday_open_nets),
    ('2. 周五收盘价买入',friday_close_nets),
    ('3. 周五收盘买(周一低开>2%则周一开盘买)',friday_delay_nets),
]:
    df=pd.DataFrame(data)
    if len(df)==0: continue
    win=(df.net>0).mean()*100
    mn=df.net.mean()*100
    med=df.net.median()*100
    print(f'| {label:<45} | {len(df):>5} | {win:>5.1f} | {mn:>7.2f} | {med:>7.2f} |')
    results.append({'label':label,'win':win,'mn':mn,'med':med})

# 对比分析
df1=pd.DataFrame(monday_open_nets)
df2=pd.DataFrame(friday_close_nets)
diff=df2.net.values-df1.net.values
avg_diff=diff.mean()*100
better=sum(diff>0)
print(f'\n--- 对比分析 ---')
print(f'周五收盘买相对周一开盘买的平均收益差: +{avg_diff:.2f}%')
print(f'周五收盘买更优的笔数: {better}/{len(df1)} ({better/len(df1)*100:.1f}%)')

# 跳空方向与收益差的关系
up_gaps=[diff[i] for i in range(len(diff)) if df1.iloc[i]['gap']>0]
down_gaps=[diff[i] for i in range(len(diff)) if df1.iloc[i]['gap']<0]
print(f'\n跳空高开时: 周五收盘买平均劣势 {sum(up_gaps)/len(up_gaps)*100:.2f}% ({len(up_gaps)}笔)')
print(f'跳空低开时: 周五收盘买平均优势 {sum(down_gaps)/len(down_gaps)*100:.2f}% ({len(down_gaps)}笔)')

print(f'\n总耗时: {time.time()-t0:.0f}s')

ts=datetime.now().strftime('%Y%m%d_%H%M%S')
path=f'D:/Hermes/同中书门下/产出/f2_entry_friday_{ts}.md'
with open(path,'w',encoding='utf-8') as f:
    f.write('# F2入场时机: 周五收盘 vs 周一开盘\n\n')
    f.write(f'区间: {START}-{END} | 持仓: {HOLD}天 | 成本: {COST*100:.3f}%\n\n')
    f.write('| 策略 | 交易数 | 胜率% | 单均净% | 中位数% |\n')
    f.write('|------|--------|-------|----------|----------|\n')
    for r in results:
        f.write(f'| {r["label"]} | {239} | {r["win"]:.1f} | {r["mn"]:.2f} | {r["med"]:.2f} |\n')
    f.write(f'\n--- 对比分析 ---\n\n')
    f.write(f'- 周五收盘买相对周一开盘买平均收益差: +{avg_diff:.2f}%\n')
    f.write(f'- 周五收盘买更优笔数: {better}/{len(df1)} ({better/len(df1)*100:.1f}%)\n')
    f.write(f'- 跳空高开时: 周五收盘买劣势 {sum(up_gaps)/len(up_gaps)*100:.2f}% ({len(up_gaps)}笔)\n')
    f.write(f'- 跳空低开时: 周五收盘买优势 {sum(down_gaps)/len(down_gaps)*100:.2f}% ({len(down_gaps)}笔)\n')
    f.write(f'\n生成: {datetime.now()}  耗时: {time.time()-t0:.0f}s\n')
print(f'\n报告已保存: {path}')
