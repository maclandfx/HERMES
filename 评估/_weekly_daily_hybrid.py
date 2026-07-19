"""
周线选股 + 日线操作 混合回测

路径A (baseline): 周线F2选入 → 固定20交易日硬出
路径B: 周线F2选入 → 周线池内每日用 主进20稳健 信号找入场点 → 固定20天出
路径C: 周线F2选入 → 固定20天 → wave下穿avg减仓50%(其余不变)
"""
import struct, os, time, math
import pandas as pd, numpy as np
from collections import defaultdict
from datetime import datetime

TDX='D:/TDX/vipdoc'; DIV={'sh':1000,'sz':10,'bj':100}
START='20230101'; END='20251231'; HOLD=20
COST=0.00432  # 双边约0.232%*2

t0=time.time()
print(f'=== 周线选股+日线操作 混合回测  区间:{START}→{END} ===')

# ===== 1. 加载日K =====
data={}
for market,div in DIV.items():
    dp=os.path.join(TDX,market,'lday')
    for fn in sorted(os.listdir(dp)):
        if not fn.endswith('.day'): continue
        code6=fn[len(market):-4]
        if market=='bj' or code6[:4] in ('8800','8801','8802','3990'): continue
        p=os.path.join(dp,fn)
        with open(p,'rb') as f: raw=f.read()
        rows=[]
        for i in range(0,len(raw)-31,32):
            try:
                d=struct.unpack('<I',raw[i:i+4])[0]
                o=struct.unpack('<I',raw[i+4:i+8])[0]/div
                h=struct.unpack('<I',raw[i+8:i+12])[0]/div
                l=struct.unpack('<I',raw[i+12:i+16])[0]/div
                c=struct.unpack('<I',raw[i+16:i+20])[0]/div
                v=struct.unpack('<Q',raw[i+20:i+28])[0]
                rows.append((d,o,h,l,c,v))
            except: break
        if rows:
            df=pd.DataFrame(rows,columns=['d','o','h','l','c','v']).set_index('d').sort_index()
            df.index=pd.to_datetime(df.index.astype(str))
            if len(df)>=60: data[code6]=df
print(f'[1/3] 加载日K {len(data)} 只, {time.time()-t0:.0f}s')

# ===== 2. 周线化 (周末最后1天=周线收盘) =====
weekly={}
for code,df in data.items():
    try:
        wd=df.groupby(df.index.to_period('W')).last()
        wd.index=wd.index.to_timestamp()
        wd=wd[['o','h','l','c','v']]
        if len(wd)>=30: weekly[code]=wd
    except: pass
print(f'[1/3] 周线 {len(weekly)} 只')

# ===== 3. 周线因子 + F2信号 =====
def comp_weekly_factors(weekly_dict):
    factors={}
    for code,df in weekly_dict.items():
        C=df['c']
        f={}
        # wave + avg (用周close)
        L10=df['l'].rolling(10).min();H25=df['h'].rolling(25).max()
        wave=((C-L10)/(H25-L10+0.001)*4).ewm(span=4,adjust=False).mean()
        f['wave']=wave; f['avg']=wave.ewm(span=3,adjust=False).mean()
        # 花神（wave>avg）
        f['huashen']=(wave>f['avg']).astype(int)
        # 主力资金强度(类r0，周线)
        vr=df['v']/(df['v'].rolling(5).mean()+0.01)
        f['r0']=((C-C.shift(1))/(C.shift(1)+0.001)*100)*vr
        f['dcz']=C.rolling(3).median()
        # MA20 (周线)
        f['ma20']=C.rolling(20).mean()
        f['close']=C
        # 大盘多头（沪深300代理→用上证指数）
        factors[code]=f
    return factors

w_factors=comp_weekly_factors(weekly)
print(f'[2/3] 周线因子完成, {time.time()-t0:.0f}s')

def f2_signal(f, ts):
    """F2 周线主进选股"""
    try:
        r0=f['r0']; wave=f['wave']; avg=f['avg']; dc=f['dcz']; ma20=f['ma20']; C=f['close']
        ts=ts  # 周线日期 (周末日期)
        r0_abs5=sum(abs(r0.shift(n)) for n in range(1,6))/5
        main=(r0>0)&(avg>avg.shift(1))
        dc_ref3=dc.shift(3)
        A=main & (dc>dc_ref3) & (pd.notna(dc))
        B=main & (dc>=dc_ref3) & (avg<2.3) & ~A
        core=A|B
        trend=pd.notna(C)&pd.notna(ma20)&(C>=ma20)&(pd.notna(dc)&(C>=dc))
        try:
            return bool(core.loc[ts]) and bool(trend.loc[ts])
        except:
            return False
    except:
        return False

# ===== 4. 日K指标 =====
def calc_daily(df):
    C=df['c']; V=df['v']
    ind=pd.DataFrame(index=df.index)
    ind['c']=C; ind['wave']=(C-C.rolling(10).min())/(C.rolling(25).max()-C.rolling(10).min()+0.001)*4
    ind['wave']=ind['wave'].ewm(span=4,adjust=False).mean()
    ind['avg']=ind['wave'].ewm(span=3,adjust=False).mean()
    ind['vrat']=V/(V.rolling(5).mean()+0.01)
    ind['r0']=((C-C.shift(1))/(C.shift(1)+0.001)*100)*ind['vrat']
    ind['ma20']=C.rolling(20).mean()
    return ind

dinds={}; t1=time.time()
for code,df in data.items(): dinds[code]=calc_daily(df)
print(f'[2/3] 日K指标 {len(dinds)} 只, {time.time()-t1:.0f}s')

# ===== 5. 主进20稳健日线信号 =====
def sig_zj20(ind, dt):
    try:
        r0=ind['r0']; avg=ind['avg']
        r0v=r0.loc[dt] if dt in r0.index else np.nan
        if pd.isna(r0v): return False
        abs5=sum(abs(r0.loc[dt-pd.Timedelta(days=n)]) for n in range(1,6) if dt-pd.Timedelta(days=n) in r0.index)
        if abs5==0: return False
        avgv=avg.loc[dt] if dt in avg.index else np.nan
        prev_avg=avg.loc[dt-pd.Timedelta(days=1)] if dt-pd.Timedelta(days=1) in avg.index else np.nan
        ma20v=ind['ma20'].loc[dt] if dt in ind['ma20'].index else np.nan
        if pd.isna(avgv) or pd.isna(prev_avg) or pd.isna(ma20v): return False
        return bool((r0v>abs5/2) and (avgv>prev_avg) and (ind['c'].loc[dt]>ma20v))
    except:
        return False

# ===== 6. 回测引擎 =====
def get_hold_days(dt, dd):
    """从dt起数HOLD个交易日"""
    idx=list(dd.index)
    try: si=idx.index(dt)
    except: return None
    ei=min(si+HOLD, len(idx)-1)
    return idx[ei]

def run_A():
    """路径A: F2周选 → 固定HOLD天硬出"""
    print('\n--- 路径A: F2周选 + 固定20天 ---')
    hold=[]; skip=0
    for code,df in weekly.items():
        ws=df.index
        for i in range(30, len(ws)-HOLD):
            T=ws[i]
            if not (pd.Timestamp(START)<=T<=pd.Timestamp(END)): continue
            if not f2_signal(w_factors.get(code,{}), T): continue
            # 买入: 周一开盘价 (下一日)
            dd=data.get(code)
            if dd is None: continue
            mon=T+pd.Timedelta(days=1)
            try: ei=dd.index.searchsorted(mon, side='left')
            except: continue
            if ei>=len(dd) or ei<0: skip+=1; continue
            entry=dd.iloc[ei]['o']
            if entry<=0: continue
            # 涨停检查
            if ei>0 and dd.iloc[ei]['o']>=dd.iloc[ei-1]['c']*1.095: skip+=1; continue
            exit_dt=get_hold_days(T, dd)
            if exit_dt is None: continue
            ei2=dd.index.searchsorted(exit_dt, side='left')
            if ei2>=len(dd): continue
            ex=dd.iloc[ei2]['c']
            if ex<=0: skip+=1; continue
            net=ex/entry-1-COST
            hold.append({'code':code,'T':T,'net':net,'entry':entry,'exit':ex})
    print(f'  路径A: {len(hold)}笔, skip={skip}')
    return hold

def run_B():
    """路径B: F2周选 → 周一那日用主进20稳健看是否能买入 → 固定20天出"""
    print('\n--- 路径B: F2周选 + 主进20稳健日线入场(周一) ---')
    hold=[]
    for code,df in weekly.items():
        ws=df.index
        for i in range(30, len(ws)-HOLD):
            T=ws[i]
            if not (pd.Timestamp(START)<=T<=pd.Timestamp(END)): continue
            if not f2_signal(w_factors.get(code,{}), T): continue
            dd=data.get(code)
            if dd is None: continue
            di=dinds.get(code)
            if di is None: continue
            mon=T+pd.Timedelta(days=1)
            # 看周一当天是否有主进20稳健信号
            if not sig_zj20(di, mon): continue
            # 买入价
            try: ei=dd.index.searchsorted(mon, side='left')
            except: continue
            if ei>=len(dd) or ei<0: continue
            entry=dd.iloc[ei]['o']
            if entry<=0: continue
            if ei>0 and dd.iloc[ei]['o']>=dd.iloc[ei-1]['c']*1.095: continue
            exit_dt=get_hold_days(mon, dd)
            if exit_dt is None: continue
            ei2=dd.index.searchsorted(exit_dt, side='left')
            if ei2>=len(dd): continue
            ex=dd.iloc[ei2]['c']
            if ex<=0: continue
            net=ex/entry-1-COST
            hold.append({'code':code,'T':T,'net':net,'entry':entry,'exit':ex})
    print(f'  路径B: {len(hold)}笔')
    return hold

def run_C():
    """路径C: F2周选 → 固定HOLD天, wave下穿avg减仓50% (用日K wave/avg)"""
    print('\n--- 路径C: F2周选 + wave减仓50% ---')
    hold=[]
    for code,df in weekly.items():
        ws=df.index
        for i in range(30, len(ws)-HOLD):
            T=ws[i]
            if not (pd.Timestamp(START)<=T<=pd.Timestamp(END)): continue
            if not f2_signal(w_factors.get(code,{}), T): continue
            dd=data.get(code)
            if dd is None: continue
            di=dinds.get(code)
            if di is None: continue
            mon=T+pd.Timedelta(days=1)
            try: ei=dd.index.searchsorted(mon, side='left')
            except: continue
            if ei>=len(dd): continue
            entry=dd.iloc[ei]['o']
            if entry<=0: continue
            if ei>0 and dd.iloc[ei]['o']>=dd.iloc[ei-1]['c']*1.095: continue
            # 模拟: 持有期间看wave是否下穿avg，下穿则卖一半，其余继续
            idx=dd.index
            si=ei
            half_sold=False; half_price=None
            for j in range(si+1, min(si+HOLD+5, len(idx))):
                dt=idx[j]
                if j-si<1: continue  # 至少持有1天
                w=di['wave'].loc[dt] if dt in di['wave'].index else np.nan
                a=di['avg'].loc[dt] if dt in di['avg'].index else np.nan
                if pd.isna(w) or pd.isna(a): continue
                prev_dt=idx[j-1]
                prev_w=di['wave'].loc[prev_dt] if prev_dt in di['wave'].index else np.nan
                if pd.notna(prev_w) and prev_w>a and w<=a:
                    half_price=dd.iloc[j]['c']
                    half_sold=True
                    break
            # 满仓限
            ei2=min(si+HOLD, len(idx)-1)
            full_price=dd.iloc[ei2]['c']
            if full_price<=0: continue
            if half_sold and half_price and half_price>0:
                half_net=half_price/entry-1-COST/2  # 一半仓位，成本减半
                full_net=full_price/entry-1-COST
                net=(half_net+full_net)/2
            else:
                net=full_price/entry-1-COST
            hold.append({'code':code,'T':T,'net':net,'entry':entry,'exit':full_price})
    print(f'  路径C: {len(hold)}笔')
    return hold

def summarize(name, hold):
    if not hold: return {'name':name,'N':0,'win':0,'mn':0,'annual':0}
    df=pd.DataFrame(hold)
    win=(df.net>0).mean()*100
    mn=df.net.mean()*100
    span=(pd.Timestamp(END)-pd.Timestamp(START)).days/365.25
    nyr=len(df)/span
    annual=((1+df.net.mean())**nyr-1)*100
    print(f'  {name}: {len(df)}笔 胜率{win:.1f}% 单均{mn:.2f}% 年化{annual:.1f}%')
    return {'name':name,'N':len(df),'win':win,'mn':mn,'annual':annual}

print('[3/3] 执行回测...')
results=[]
for label,hold in [('路径A: F2周选+固定20天',run_A()),
                   ('路径B: F2周选+主进20稳健入场',run_B()),
                   ('路径C: F2周选+wave减仓50%',run_C())]:
    results.append(summarize(label,hold))

print('\n'+'='*80)
print('周线选股 + 日线操作 混合回测 汇总')
print('='*80)
print(f'| {"策略":<36} | {"交易":>5} | {"胜率":>5} | {"单均净":>7} | {"年化":>7} |')
print('|'+'-'*38+'|'+'-'*7+'|'+'-'*7+'|'+'-'*9+'|'+'-'*9+'|')
for r in sorted(results,key=lambda x:x['annual'],reverse=True):
    print(f'| {r["name"]:<36} | {r["N"]:>5} | {r["win"]:>5.1f} | {r["mn"]:>7.2f} | {r["annual"]:>7.1f} |')
print(f'\n总耗时: {time.time()-t0:.0f}s')

ts=datetime.now().strftime('%Y%m%d_%H%M%S')
path=f'D:/Hermes/同中书门下/产出/weekly_daily_hybrid_{ts}.md'
with open(path,'w',encoding='utf-8') as f:
    f.write('# 周线选股 + 日线操作 混合回测报告\n\n')
    f.write(f'区间: {START}-{END} | 持仓: {HOLD}天 | 成本: {COST*100:.3f}%\n\n')
    f.write('| 策略 | 交易数 | 胜率% | 单均净% | 年化净% |\n')
    f.write('|------|--------|-------|---------|----------|\n')
    for r in sorted(results,key=lambda x:x['annual'],reverse=True):
        f.write(f'| {r["name"]} | {r["N"]} | {r["win"]:.1f} | {r["mn"]:.2f} | {r["annual"]:.1f} |\n')
    f.write(f'\n生成: {datetime.now()}  耗时: {time.time()-t0:.0f}s\n')
print(f'\n报告已保存: {path}')
