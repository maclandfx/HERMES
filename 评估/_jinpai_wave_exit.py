"""
金牌狙击紧 回测 + 花女线下穿出场机制

出场逻辑：
- wave 上穿 avg → 趋势强（进场）
- wave 下穿 avg → 趋势弱（临时出来）
日线建仓时无法用小时数据（TDX无小时回测文件），用日线MA5下穿MA10替代。

对比：固定持仓20天 vs 花女线出场
"""
import struct, os, time, pandas as pd, numpy as np
from collections import defaultdict

TDX='D:/TDX/vipdoc'; DIV={'sh':1000,'sz':10,'bj':100}
START, END, HOLD, TOPK = 20230101, 20251231, 20, 5

t0=time.time()
print(f'=== 金牌狙击紧 花女线出场实验  区间:{START}→{END}  top_k:{TOPK} ===')

# 1. 加载
data={}
for market,div in DIV.items():
    dp=os.path.join(TDX,market,'lday')
    for fn in os.listdir(dp):
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
            if len(df)>=60:
                df=df[(df.index>=START)&(df.index<=END)]
                if len(df)>=20: data[f'{market.upper()}{code6}']=df
print(f'[1/4] 加载 {len(data)} 只, {time.time()-t0:.0f}s')

# 2. 指标
def calc(df):
    C,H,L,O,V=df.c,df.h,df.l,df.o,df.v
    ind=pd.DataFrame(index=df.index)
    ind['c']=C;ind['h']=H;ind['l']=L;ind['v']=V
    ind['ema3']=C.ewm(span=3,adjust=False).mean();ind['ema7']=C.ewm(span=7,adjust=False).mean()
    ind['vma5']=V.rolling(5).mean();ind['vrat']=V/(ind['vma5']+0.01)
    L10=L.rolling(10).min();H25=H.rolling(25).max()
    wave=((C-L10)/(H25-L10+0.001)*4).ewm(span=4,adjust=False).mean()
    ind['wave']=wave;ind['avg']=wave.ewm(span=3,adjust=False).mean()
    ind['r0']=((C-C.shift(1))/(C.shift(1)+0.001)*100)*ind['vrat']
    ind['dcz']=C.rolling(20).median()
    ind['pct']=C.pct_change()*100
    L60=L.rolling(60).min();H60=H.rolling(60).max()
    ind['conc_proxy']=(H60-L60)/(H60+0.001)*100
    ind['rs50']=C.pct_change(periods=50)
    # MA5/MA10 日线出场代理（小时线代理）+ MA20 止损
    ind['ma5']=C.rolling(5).mean();ind['ma10']=C.rolling(10).mean()
    ind['ma20']=C.rolling(20).mean()
    return ind

inds={}; t1=time.time()
for c,df in data.items(): inds[c]=calc(df)
print(f'[2/4] 指标 {len(inds)} 只, {time.time()-t1:.0f}s')

# 3. 大盘多头
p='D:/TDX/vipdoc/sh/lday/sh000001.day'
with open(p,'rb') as f: raw=f.read()
rows=[]
for i in range(0,len(raw)-31,32):
    try:
        d=struct.unpack('<I',raw[i:i+4])[0]
        c=struct.unpack('<I',raw[i+16:i+20])[0]/1000
        rows.append((d,c))
    except: break
idx=pd.DataFrame(rows,columns=['d','c']).set_index('d').sort_index()
ma60=idx.c.rolling(60).mean()
bull_dates=set((idx.c>ma60).loc[ma60>ma60.shift(5)].index.astype(int))
print(f'[2/4] 大盘多头 {len(bull_dates)} 天')

# 4. 信号
def sig_base20(ind):
    abs5=sum(abs(ind['r0'].shift(n)) for n in range(1,6))
    att=(ind['r0']-abs5/2>0)&(ind['avg']>ind['avg'].shift(1))
    return att&(ind['c']>ind['c'].rolling(20).mean())

def sig_jp_core(ind):
    abs5=sum(abs(ind['r0'].shift(n)) for n in range(1,6))/5
    main=(ind['r0']>abs5)&(ind['avg']>ind['avg'].shift(1))&(ind['avg'].shift(1)<ind['avg'].shift(2))
    vol_up=ind['vrat']>1.5; price_up=ind['pct']>3
    return main&vol_up&price_up

def sig_jp_tight(ind):
    return sig_jp_core(ind)&(ind['conc_proxy']<25)

# 5. 回测引擎（两种出场）
def get_exit_date(ind, t, hold_max):
    """花女线下穿出场：wave 从 >avg 变成 <=avg 的当天出；MA5下穿MA10代理小时线；MA20止损"""
    cd=int(t); days=0; hard_stop=hold_max*2
    while True:
        if cd not in ind.index:
            cd+=1
            hard_stop-=1
            if hard_stop<=0:
                return None, days, '超时'
            continue
        c=ind.loc[cd,'c']; w=ind.loc[cd,'wave']; a=ind.loc[cd,'avg']
        m5=ind.loc[cd,'ma5']; m10=ind.loc[cd,'ma10']; m20=ind.loc[cd,'ma20']
        if days>0:
            prev_w=ind.loc[cd-1,'wave'] if cd-1 in ind.index else w
            if pd.notna(w) and pd.notna(a) and pd.notna(prev_w) and prev_w>a and w<=a:
                return c, days, 'wave下穿avg'
            prev_m5=ind.loc[cd-1,'ma5'] if cd-1 in ind.index else m5
            if pd.notna(m5) and pd.notna(m10) and pd.notna(prev_m5) and prev_m5>m10 and m5<=m10:
                return c, days, 'ma5下穿ma10'
            if pd.notna(m20) and c < m20*0.98:
                return c, days, 'MA20止损'
        days+=1
        if days>=hold_max:
            return c, days, '满仓限'
        cd+=1

def run_exit(fn,name,exit_type='wave'):
    pool=defaultdict(list)
    for code,ind in inds.items():
        s=fn(ind)
        for ts in s[s].index:
            t=int(ts)
            if t<START or t>END or t not in bull_dates: continue
            c=ind.loc[ts,'c'];cp=ind.loc[ts-1,'c'] if ts-1 in ind.index else 0
            if cp>0 and c>=cp*1.095: continue
            r0v=ind.loc[ts,'r0'] if pd.notna(ind.loc[ts,'r0']) else 0
            rs50v=ind.loc[ts,'rs50'] if pd.notna(ind.loc[ts,'rs50']) else 0
            pool[t].append((code,r0v+abs(rs50v)*100))
    sel=set()
    for t in pool:
        pool[t].sort(key=lambda x:x[1],reverse=True)
        for code,score in pool[t][:TOPK]: sel.add((code,t))
    holdings=[]
    for code,t in sel:
        ind=inds[code];entry=ind.loc[t,'c']
        if exit_type=='fixed':
            idx_list=list(ind.index)
            start_i=idx_list.index(t) if t in idx_list else 0
            end_i=min(start_i+HOLD, len(idx_list)-1)
            ex=ind.loc[idx_list[end_i],'c']
        else:
            ex,days,reason=get_exit_date(ind,t,HOLD)
        if ex is None or ex<=0: continue
        net=ex/entry-1-0.00232-0.002
        holdings.append({'net':net})
    if not holdings: return {'公式':name,'交易数':0,'胜率':0,'单均净%':0,'年化净%':0,'均持仓天':0}
    df=pd.DataFrame(holdings);win=(df.net>0).mean()*100;mn=df.net.mean()*100
    span=(END-START)/365;nyr=len(df)/span;annual=((1+df.net.mean())**nyr-1)*100
    return {'公式':name,'交易数':len(df),'胜率':round(win,1),'单均净%':round(mn,2),'年化净%':round(annual,1)}

formulas=[('主进20稳健',sig_base20),('金牌狙击紧_core',sig_jp_core),('金牌狙击紧_full',sig_jp_tight)]

print('[3/4] 执行回测...')
results=[]
for name,fn in formulas:
    for etype,elabel in [('fixed','固定20天'),('wave','花女线+MA出场')]:
        r=run_exit(fn,name,etype)
        r['公式']=f"{name} ({elabel})"
        results.append(r)
        print(f'  {r["公式"]}: {r["交易数"]}笔 胜率{r["胜率"]}% 单均{r["单均净%"]} 年化{r["年化净%"]}')

print('\n'+'='*80)
print('花女线出场 vs 固定持仓20天')
print('='*80)
hdr=f'| {"公式":<32} | {"交易":>5} | {"胜率":>5} | {"单均净":>7} | {"年化":>7} |'
print(hdr); print('|'+'-'*34+'|'+'-'*7+'|'+'-'*7+'|'+'-'*9+'|'+'-'*9+'|')
for r in sorted(results,key=lambda x:x['年化净%'],reverse=True):
    print(f'| {r["公式"]:<32} | {r["交易数"]:>5} | {r["胜率"]:>5.1f} | {r["单均净%"]:>7.2f} | {r["年化净%"]:>7.1f} |')
print(f'\n总耗时: {time.time()-t0:.0f}s')

ts=pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
path=f'D:/Hermes/同中书门下/产出/jinpai_wave_exit_{ts}.md'
with open(path,'w',encoding='utf-8') as f:
    f.write('# 花女线下穿出场机制 回测报告\n\n')
    f.write(f'区间: {START}-{END} | top_k={TOPK}\n\n')
    f.write('## 出场规则\n')
    f.write('- 固定持仓：买入后满20天卖出\n')
    f.write('- 花女线出场：日线wave下穿avg 或 MA5下穿MA10（小时线代理）或 MA20止损\n\n')
    f.write('| 公式 | 交易数 | 胜率% | 单均净% | 年化净% |\n')
    f.write('|------|--------|-------|---------|----------|\n')
    for r in sorted(results,key=lambda x:x['年化净%'],reverse=True):
        f.write(f'| {r["公式"]} | {r["交易数"]} | {r["胜率"]:.1f} | {r["单均净%"]:.2f} | {r["年化净%"]:.1f} |\n')
    f.write(f'\n生成: {pd.Timestamp.now()}  耗时: {time.time()-t0:.0f}s\n')
print(f'\n报告已保存: {path}')
