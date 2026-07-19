"""
周线选股+日线操作 混合回测（基于TDX本地数据）
复用 weekly_formula_backtest 的原版 F2 引擎 + 日K数据

路径A: F2周选 → 周一开盘买入 → 固定20交易日卖出 (baseline)
路径B: F2周选 → 周一开盘买入 → 固定20天 + MA20周线止损
路径C: F2周选 → 周一开盘买入 → 固定20天 + 日线wave下穿avg减仓50%
"""
import struct, os, time
import pandas as pd, numpy as np
from collections import defaultdict
from datetime import datetime

TDX='D:/TDX/vipdoc'; DIV={'sh':1000,'sz':10,'bj':100}
START='20230101'; END='20251231'; HOLD=20
COST=0.00232

t0=time.time()
print(f'=== 周线选股+日线操作 混合回测  {START}→{END} ===')

# ===== 1. 加载日K =====
def load_daily():
    data={}
    for m,div in DIV.items():
        dp=os.path.join(TDX,m,'lday')
        for fn in sorted(os.listdir(dp)):
            if not fn.endswith('.day'): continue
            code6=fn[len(m):-4]
            if m=='bj' or code6[:4] in ('8800','8801','8802','3990'): continue
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
    return data

# ===== 2. 周线化 =====
def to_weekly(daily):
    wk={}
    for code,df in daily.items():
        try:
            wd=df.groupby(df.index.to_period('W')).last()
            wd.index=wd.index.to_timestamp()
            if len(wd)>=30: wk[code]=wd
        except: pass
    return wk

# ===== 3. 周线F2因子（简化，核心信号） =====
def comp_factors(weekly):
    factors={}
    idx_df=None
    for code in ('000300','000001'):
        if code in weekly:
            idx_df=weekly[code]['c']
            break
    for code,df in weekly.items():
        try:
            C=df['c'];H=df['h'];L=df['l'];O=df['o'];V=df['v']
            f={}
            ma20=C.rolling(20).mean()
            # R0 主力进
            VV=V/(V.rolling(5).mean()+0.001)
            R0=((C-C.shift(1))/(C.shift(1)+0.001)*100)*VV
            R0abs=(abs(R0.shift(1))+abs(R0.shift(2))+abs(R0.shift(3))+abs(R0.shift(4))+abs(R0.shift(5))/2)
            f['main_in']=R0>R0abs
            # DCZ 筹码
            mid=(H+L)/2; DCZ=mid.ewm(span=10,adjust=False).mean()
            f['DCZ']=DCZ
            # wave/avg
            mn10=L.rolling(10).min();mx25=H.rolling(25).max()
            wave=((C-mn10)/(mx25-mn10+0.001)*4).ewm(span=4,adjust=False).mean()
            avg=wave.ewm(span=3,adjust=False).mean()
            f['wave']=wave;f['avg']=avg;f['huashen']=wave>avg
            f['ma20']=ma20;f['close']=C
            f['avg_turn']=avg>=avg.shift(1)
            factors[code]=f
        except: pass
    return factors

print('加载日K...')
daily=load_daily(); print(f'  日K: {len(daily)}只')
print('聚合周K...')
weekly=to_weekly(daily); print(f'  周K: {len(weekly)}只')
print('计算周线F2因子...')
wfac=comp_factors(weekly); print(f'  因子完成 {len(wfac)}只')
print(f'  耗时 {time.time()-t0:.0f}s')

# F2信号（原版简化）
def f2(f,ts):
    try:
        main=f['main_in'];DCZ=f['DCZ'];avg=f['avg'];hu=f['huashen']
        ma20=f['ma20'];C=f['close']
        # A: 主进 + DCZ>REF3 + 量比
        A=main.loc[ts] if ts in main.index else False
        dc_v=DCZ.loc[ts] if ts in DCZ.index else np.nan
        dc3=DCZ.shift(3).loc[ts] if ts in DCZ.shift(3).index else np.nan
        if pd.notna(dc_v) and pd.notna(dc3):
            A=A and (dc_v>dc3)
        else: return False
        # B: 主进 + DCZ>=REF3 + avg<2.3 + 花神
        avg_v=avg.loc[ts] if ts in avg.index else np.nan
        hu_v=hu.loc[ts] if ts in hu.index else False
        dc_eq=dc_v>=dc3 if pd.notna(dc_v) and pd.notna(dc3) else False
        B=main.loc[ts] if ts in main.index else False
        B=B and dc_eq and pd.notna(avg_v) and avg_v<2.3 and hu_v
        if not (A or B): return False
        # 趋势过滤
        c_v=C.loc[ts] if ts in C.index else np.nan
        m20_v=ma20.loc[ts] if ts in ma20.index else np.nan
        return pd.notna(c_v) and pd.notna(m20_v) and c_v>=m20_v and pd.notna(dc_v) and c_v>=dc_v
    except: return False

# 大盘多头过滤
def market_bull(ws,T):
    if '000001' not in wfac or '000300' not in wfac: return True
    idx=wfac['000300']['close']
    try:
        cv=idx.loc[T];ma=idx.rolling(60).mean().loc[T]
        prev=idx.rolling(60).mean().shift(5).loc[T]
        if pd.notna(cv) and pd.notna(ma) and pd.notna(prev):
            return cv>ma and ma>prev
    except: pass
    return True

def get_limit(code):
    u=code
    if u.startswith('30') or u.startswith('68'): return 0.195
    if u.startswith('8'): return 0.295
    return 0.095

# ===== 4. 三条路径 =====
def run_A(fac,daily,market_filter=True):
    """F2周选 → 周一开盘 → 固定20交易日出"""
    print('\n--- A: F2周选 + 固定20天 ---')
    hold=[];skip=0
    for code,f in fac.items():
        if code in ('000300','000001','000688','399001','399300'): continue
        ws=f['close'].index
        dd=daily.get(code)
        if dd is None: continue
        for i in range(30,len(ws)-HOLD):
            T=ws[i]
            if not (pd.Timestamp(START)<=T<=pd.Timestamp(END)): continue
            if market_filter and not market_bull(ws,T): continue
            if not f2(f,T): continue
            mon=T+pd.Timedelta(days=1)
            try: ei=dd.index.searchsorted(mon,side='left')
            except: continue
            if ei>=len(dd): continue
            entry=dd.iloc[ei]['o']
            if entry<=0: continue
            lim=get_limit(code)
            if ei>0 and dd.iloc[ei]['o']>=dd.iloc[ei-1]['c']*(1+lim): skip+=1;continue
            # 固定20交易日
            idx=dd.index;si=ei
            ei2=min(si+HOLD,len(idx)-1)
            ex=dd.iloc[ei2]['c']
            if ex<=0: skip+=1;continue
            net=ex/entry-1-COST
            hold.append({'net':net})
    print(f'  A: {len(hold)}笔, skip={skip}')
    return hold

def run_B(fac,daily):
    """F2周选 → 周一开盘 → 固定20天 + 周线MA20止损(跌破-2%)"""
    print('\n--- B: F2周选 + 固定20天 + MA20止损 ---')
    hold=[]
    for code,f in fac.items():
        if code in ('000300','000001','000688','399001','399300'): continue
        ws=f['close'].index
        dd=daily.get(code)
        if dd is None: continue
        ma20_s=f['ma20']
        for i in range(30,len(ws)-HOLD):
            T=ws[i]
            if not (pd.Timestamp(START)<=T<=pd.Timestamp(END)): continue
            if not f2(f,T): continue
            mon=T+pd.Timedelta(days=1)
            try: ei=dd.index.searchsorted(mon,side='left')
            except: continue
            if ei>=len(dd): continue
            entry=dd.iloc[ei]['o']
            if entry<=0: continue
            lim=get_limit(code)
            if ei>0 and dd.iloc[ei]['o']>=dd.iloc[ei-1]['c']*(1+lim): continue
            idx=dd.index;si=ei
            ex_price=None;stop=False
            for j in range(si+1,min(si+HOLD+5,len(idx))):
                dt=idx[j]
                # 周线MA20前向填充到日
                last_ma=ma20_s[ma20_s.index<=dt].iloc[-1] if (ma20_s.index<=dt).any() else np.nan
                if pd.notna(last_ma) and dd.iloc[j]['c']<last_ma*0.98:
                    ex_price=dd.iloc[j]['c'];stop=True;break
                if j-si>=HOLD:
                    ex_price=dd.iloc[j]['c'];break
            if ex_price is None or ex_price<=0: continue
            net=ex_price/entry-1-COST
            hold.append({'net':net})
    print(f'  B: {len(hold)}笔')
    return hold

def run_C(fac,daily):
    """F2周选 → 周一开盘 → 固定20天 + 日线wave下穿avg减仓50%"""
    print('\n--- C: F2周选 + wave减仓50% ---')
    hold=[]
    for code,f in fac.items():
        if code in ('000300','000001','000688','399001','399300'): continue
        ws=f['close'].index
        dd=daily.get(code)
        if dd is None: continue
        di=dinds.get(code)
        if di is None: continue
        for i in range(30,len(ws)-HOLD):
            T=ws[i]
            if not (pd.Timestamp(START)<=T<=pd.Timestamp(END)): continue
            if not f2(f,T): continue
            mon=T+pd.Timedelta(days=1)
            try: ei=dd.index.searchsorted(mon,side='left')
            except: continue
            if ei>=len(dd): continue
            entry=dd.iloc[ei]['o']
            if entry<=0: continue
            lim=get_limit(code)
            if ei>0 and dd.iloc[ei]['o']>=dd.iloc[ei-1]['c']*(1+lim): continue
            idx=dd.index;si=ei
            half_price=None;full_price=dd.iloc[min(si+HOLD,len(idx)-1)]['c']
            # 寻找wave下穿avg
            for j in range(si+2,min(si+HOLD+2,len(idx))):
                dt=idx[j]
                w=di['wave'].loc[dt] if dt in di['wave'].index else np.nan
                a=di['avg'].loc[dt] if dt in di['avg'].index else np.nan
                if pd.isna(w) or pd.isna(a): continue
                pd_=idx[j-1]
                pw=di['wave'].loc[pd_] if pd_ in di['wave'].index else np.nan
                if pd.notna(pw) and pw>a and w<=a:
                    half_price=dd.iloc[j]['c'];break
            if full_price<=0: continue
            if half_price and half_price>0:
                h_n=half_price/entry-1-COST/2
                f_n=full_price/entry-1-COST
                net=(h_n+f_n)/2
            else:
                net=full_price/entry-1-COST
            hold.append({'net':net})
    print(f'  C: {len(hold)}笔')
    return hold

# 日线指标（wave/avg）
print('计算日线wave/avg...')
dinds={}
for code,df in daily.items():
    try:
        C=df['c'];L=df['l'];H=df['h']
        mn10=L.rolling(10).min();mx25=H.rolling(25).max()
        wave=((C-mn10)/(mx25-mn10+0.001)*4).ewm(span=4,adjust=False).mean()
        dinds[code]={'wave':wave,'avg':wave.ewm(span=3,adjust=False).mean()}
    except: pass
print(f'  日线指标完成 {len(dinds)}只')

# 运行
print('\n执行回测...')
results=[]
for label,hold in [('A: F2周选+固定20天',run_A(wfac,daily)),
                   ('B: F2周选+20天+MA20止损',run_B(wfac,daily)),
                   ('C: F2周选+20天+wave减仓50%',run_C(wfac,daily))]:
    if not hold:
        results.append({'name':label,'N':0,'win':0,'mn':0,'annual':0})
        continue
    df=pd.DataFrame(hold)
    win=(df.net>0).mean()*100
    mn=df.net.mean()*100
    span=(pd.Timestamp(END)-pd.Timestamp(START)).days/365.25
    nyr=len(df)/span
    annual=((1+mn/100)**nyr-1)*100
    print(f'  {label}: {len(df)}笔 胜率{win:.1f}% 单均{mn:.2f}% 年化{annual:.1f}%')
    results.append({'name':label,'N':len(df),'win':win,'mn':mn,'annual':annual})

print('\n'+'='*80)
print('周线选股+日线操作 混合回测 汇总')
print('='*80)
print(f'| {"策略":<38} | {"交易":>5} | {"胜率":>5} | {"单均净":>7} | {"年化":>7} |')
print('|'+'-'*40+'|'+'-'*7+'|'+'-'*7+'|'+'-'*9+'|'+'-'*9+'|')
for r in sorted(results,key=lambda x:x['annual'],reverse=True):
    print(f'| {r["name"]:<38} | {r["N"]:>5} | {r["win"]:>5.1f} | {r["mn"]:>7.2f} | {r["annual"]:>7.1f} |')
print(f'\n总耗时: {time.time()-t0:.0f}s')

ts=datetime.now().strftime('%Y%m%d_%H%M%S')
path=f'D:/Hermes/同中书门下/产出/weekly_daily_hybrid_{ts}.md'
with open(path,'w',encoding='utf-8') as f:
    f.write('# 周线选股+日线操作 混合回测报告\n\n')
    f.write(f'区间: {START}-{END} | 持仓: {HOLD}天 | 成本: {COST*100:.3f}%\n\n')
    f.write('| 策略 | 交易数 | 胜率% | 单均净% | 年化净% |\n')
    f.write('|------|--------|-------|---------|----------|\n')
    for r in sorted(results,key=lambda x:x['annual'],reverse=True):
        f.write(f'| {r["name"]} | {r["N"]} | {r["win"]:.1f} | {r["mn"]:.2f} | {r["annual"]:.1f} |\n')
    f.write(f'\n生成: {datetime.now()}  耗时: {time.time()-t0:.0f}s\n')
print(f'\n报告已保存: {path}')
