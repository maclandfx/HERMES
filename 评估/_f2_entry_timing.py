"""
F2入场时机实验 — 基于239笔F2信号池，对比不同入场方式
测试：
  1. 周一开盘价买入 (baseline)
  2. 周一收盘价买入（等开盘确认）
  3. 跳空高开>2%时延后到当日收盘买
  4. 跳空高开>3%时延后到次日开盘买
  5. 周一开盘价 vs 周一收盘价的收益差分析
"""
import sys, time
sys.path.insert(0, 'D:/Hermes/评估中心/tools/tdx_connector/scripts')
from weekly_formula_backtest import (load_all_daily, daily_to_weekly, compute_weekly_factors,
    load_benchmark, formula_2_main, run_formula_backtest)
import pandas as pd, numpy as np
from datetime import datetime, timedelta

TDX='D:/TDX/vipdoc'; START='20230101'; END='20251231'
HOLD=15
COST=0.00232

t0=time.time()
print(f'=== F2入场时机实验  {START}→{END}  ===')

daily=load_all_daily()
weekly=daily_to_weekly(daily)
factors=compute_weekly_factors(weekly)
bench=load_benchmark(daily)
if bench is None: sys.exit(1)

print('\n--- 跑F2信号池 ---')
hA, sA = run_formula_backtest(formula_2_main, 'F2', weekly, daily, factors, bench,
                               hold_days=HOLD, top_k=20, start=START, end=END, realistic=False)
print(f'  信号池: {len(hA)}笔')

# 从hA中提取每笔交易的周一日期和对应日K数据
def analyze_entry(hold_list, daily_dict):
    """基于信号池重新计算不同入场方式的收益"""
    results = {
        'open_buy': [],       # 1. 周一开盘价买入
        'close_buy': [],      # 2. 周一收盘价买入
        'gap_delay': [],      # 3. 跳空高开>2%延后到当日收盘
        'gap3_delay': [],     # 4. 跳空高开>3%延后到次日开盘
    }
    gap_stats = {'gap_up':0, 'gap_down':0, 'gap_flat':0}
    
    for x in hold_list:
        code=x['code']; T=x['T']  # T是周一日期
        dd=daily_dict.get(code)
        if dd is None:
            continue
        # 找T对应的日K
        idx=dd.index
        try:
            t_idx = idx.searchsorted(T, side='left')
            # T就是周一，直接取
            day_open=dd.iloc[t_idx]['open']
            day_close=dd.iloc[t_idx]['close']
            day_high=dd.iloc[t_idx]['high']
            day_low=dd.iloc[t_idx]['low']
            prev_close_idx=t_idx-1 if t_idx>0 else t_idx
            prev_close=dd.iloc[prev_close_idx]['close']
            
            # 持仓结束日
            exit_date = T + pd.Timedelta(days=HOLD)
            # 找最接近的交易日
            exit_idx=idx.searchsorted(exit_date, side='left')
            if exit_idx>=len(idx):
                exit_idx=len(idx)-1
            exit_price=dd.iloc[exit_idx]['close']
            exit_date_actual=idx[exit_idx]
            
            if exit_price<=0:
                continue
            
            # 计算跳空幅度
            if prev_close>0:
                gap_pct=(day_open-prev_close)/prev_close*100
            else:
                gap_pct=0
            if gap_pct>1: gap_stats['gap_up']+=1
            elif gap_pct<-1: gap_stats['gap_down']+=1
            else: gap_stats['gap_flat']+=1
            
            # 策略1: 周一开盘价买入
            net1=exit_price/day_open-1-COST
            results['open_buy'].append({'net':net1,'gap':gap_pct})
            
            # 策略2: 周一收盘价买入
            net2=exit_price/day_close-1-COST
            results['close_buy'].append({'net':net2,'gap':gap_pct})
            
            # 策略3: 跳空高开>2%时延后到当日收盘买，否则开盘买
            if gap_pct>2:
                entry3=day_close
            else:
                entry3=day_open
            net3=exit_price/entry3-1-COST
            results['gap_delay'].append({'net':net3,'gap':gap_pct})
            
            # 策略4: 跳空高开>3%时延后到次日开盘买，否则开盘买
            if gap_pct>3 and t_idx+1<len(idx):
                entry4=dd.iloc[t_idx+1]['open']
            else:
                entry4=day_open
            net4=exit_price/entry4-1-COST
            results['gap3_delay'].append({'net':net4,'gap':gap_pct})
            
        except:
            continue
    
    return results, gap_stats

results, gap_stats = analyze_entry(hA, daily)
print(f'\n跳空分布: 高开{gap_stats["gap_up"]}笔 低开{gap_stats["gap_down"]}笔 平开{gap_stats["gap_flat"]}笔')

# 汇总
print('\n'+'='*85)
print('F2入场时机实验 汇总')
print('='*85)
print(f'| {"策略":<40} | {"交易":>5} | {"胜率":>5} | {"单均净":>7} |')
print('|'+'-'*42+'|'+'-'*7+'|'+'-'*7+'|'+'-'*9+'|')

strategies = [
    ('1. 周一开盘价买入(baseline)', results['open_buy']),
    ('2. 周一收盘价买入', results['close_buy']),
    ('3. 跳空高开>2%延后收盘买', results['gap_delay']),
    ('4. 跳空高开>3%延后次日开盘买', results['gap3_delay']),
]

summary=[]
for name,data in strategies:
    if not data:
        continue
    df=pd.DataFrame(data)
    win=(df.net>0).mean()*100
    mn=df.net.mean()*100
    med=df.net.median()*100
    print(f'| {name:<40} | {len(df):>5} | {win:>5.1f} | {mn:>7.2f} |')
    summary.append({'name':name,'N':len(df),'win':win,'mn':mn,'med':med})

# 跳空高开笔的详细分析
print('\n--- 跳空高开>3%的笔 ---')
big_gaps=[r for r in results['open_buy'] if r['gap']>3]
if big_gaps:
    dg=pd.DataFrame(big_gaps)
    print(f'  笔数: {len(dg)}, 平均跳空: {dg.gap.mean():.1f}%, 平均收益: {dg.net.mean()*100:.2f}%')
    # 如果这些笔延后到次日开盘买，收益变化
    for x in hA:
        code=x['code']; T=x['T']
        dd=daily.get(code)
        if dd is None: continue
        idx=dd.index
        t_idx=idx.searchsorted(T, side='left')
        if t_idx>=len(idx)-1: continue
        day_open=dd.iloc[t_idx]['open']
        prev_close=dd.iloc[t_idx-1]['close'] if t_idx>0 else 0
        gap=(day_open-prev_close)/prev_close*100
        if gap>3:
            exit_date=T+pd.Timedelta(days=HOLD)
            exit_idx=idx.searchsorted(exit_date, side='left')
            if exit_idx>=len(idx): exit_idx=len(idx)-1
            exit_price=dd.iloc[exit_idx]['close']
            entry4=dd.iloc[t_idx+1]['open']
            net4=exit_price/entry4-1-COST
            net1=exit_price/day_open-1-COST
            diff=(net4-net1)*100
            if abs(diff)>5:
                print(f'  {code} {T.date()}: 开盘{day_open:.2f}→次日开盘{entry4:.2f} 收益差{diff:.2f}%')

print(f'\n总耗时: {time.time()-t0:.0f}s')

ts=datetime.now().strftime('%Y%m%d_%H%M%S')
path=f'D:/Hermes/同中书门下/产出/f2_entry_timing_{ts}.md'
with open(path,'w',encoding='utf-8') as f:
    f.write('# F2入场时机实验报告\n\n')
    f.write(f'区间: {START}-{END} | 持仓: {HOLD}天 | 成本: {COST*100:.3f}%\n\n')
    f.write(f'跳空分布: 高开{gap_stats["gap_up"]}笔 低开{gap_stats["gap_down"]}笔 平开{gap_stats["gap_flat"]}笔\n\n')
    f.write('| 策略 | 交易数 | 胜率% | 单均净% | 中位数% |\n')
    f.write('|------|--------|-------|----------|----------|\n')
    for r in summary:
        f.write(f'| {r["name"]} | {r["N"]} | {r["win"]:.1f} | {r["mn"]:.2f} | {r["med"]:.2f} |\n')
    f.write(f'\n生成: {datetime.now()}  耗时: {time.time()-t0:.0f}s\n')
print(f'\n报告已保存: {path}')
