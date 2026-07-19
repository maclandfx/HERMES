"""金牌狙击紧 回测实验：把选股器逻辑翻译成回测信号"""
import struct, os, time, pandas as pd, numpy as np
from collections import defaultdict

TDX='D:/TDX/vipdoc'; DIV={'sh':1000,'sz':10,'bj':100}
START, END, HOLD, TOPK = 20230101, 20251231, 20, 5

t0=time.time()
print(f'=== 金牌狙击紧 回测实验  区间:{START}→{END}  持仓:{HOLD}天  top_k:{TOPK} ===')

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
    ind['dif']=C.ewm(span=12,adjust=False).mean()-C.ewm(span=26,adjust=False).mean()
    ind['vma5']=V.rolling(5).mean();ind['vrat']=V/(ind['vma5']+0.01)
    L10=L.rolling(10).min();H25=H.rolling(25).max()
    wave=((C-L10)/(H25-L10+0.001)*4).ewm(span=4,adjust=False).mean()
    ind['wave']=wave;ind['avg']=wave.ewm(span=3,adjust=False).mean()
    ind['r0']=((C-C.shift(1))/(C.shift(1)+0.001)*100)*ind['vrat']
    ind['dcz']=C.rolling(20).median()
    ind['pct']=C.pct_change()*100
    # 60日范围，筹码集中代理指标
    L60=L.rolling(60).min();H60=H.rolling(60).max()
    ind['conc_proxy']=(H60-L60)/(H60+0.001)*100  # 越小越集中
    ind['rs50']=C.pct_change(periods=50)
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
    """主进20稳健（基准对照）"""
    abs5=sum(abs(ind['r0'].shift(n)) for n in range(1,6))
    att=(ind['r0']-abs5/2>0)&(ind['avg']>ind['avg'].shift(1))
    return att&(ind['c']>ind['c'].rolling(20).mean().shift(0))

def sig_jp_core(ind):
    """金牌狙击紧_core: 主力进场 + 量价齐升（无筹码集中）"""
    # 主力进场
    abs5=sum(abs(ind['r0'].shift(n)) for n in range(1,6))/5
    main=(ind['r0']>abs5)&(ind['avg']>ind['avg'].shift(1))&(ind['avg'].shift(1)<ind['avg'].shift(2))
    # 量价齐升
    vol_up=ind['vrat']>1.5
    price_up=ind['pct']>3
    return main&vol_up&price_up

def sig_jp_tight(ind):
    """金牌狙击紧_full: 主力进场 + 量价齐升 + 筹码集中(代理<25%)"""
    return sig_jp_core(ind)&(ind['conc_proxy']<25)

def sig_jp_ab(ind):
    """金牌狙击紧_AB: 主力进场 + (量价齐升 OR 筹码集中) + 至少涨幅>1%"""
    abs5=sum(abs(ind['r0'].shift(n)) for n in range(1,6))/5
    main=(ind['r0']>abs5)&(ind['avg']>ind['avg'].shift(1))&(ind['avg'].shift(1)<ind['avg'].shift(2))
    vol_up=ind['vrat']>1.5; conc_ok=ind['conc_proxy']<25; price_up=ind['pct']>1
    # A级或B级：主进 + 至少量价齐升或筹码集中一项 + 涨幅>1
    return main&((vol_up|conc_ok)&price_up)

# 5. 回测引擎
def run(fn,name):
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
        ind=inds[code];entry=ind.loc[t,'c'];cd=t+1;days=0;ex=None
        while cd not in ind.index and cd<END+300: cd+=1
        if cd>=END+300: continue
        while days<HOLD and cd in ind.index:
            days+=1;cd+=1
            while cd not in ind.index and cd<END+300: cd+=1
        ex=ind.loc[cd,'c'] if cd in ind.index else None
        if ex is None or ex<=0: continue
        net=ex/entry-1-0.00232-0.002
        holdings.append({'net':net})
    if not holdings: return {'公式':name,'交易数':0,'胜率':0,'单均净%':0,'年化净%':0}
    df=pd.DataFrame(holdings);win=(df.net>0).mean()*100;mn=df.net.mean()*100
    span=(END-START)/365;nyr=len(df)/span;annual=((1+df.net.mean())**nyr-1)*100
    return {'公式':name,'交易数':len(df),'胜率':round(win,1),'单均净%':round(mn,2),'年化净%':round(annual,1)}

formulas=[
    ('主进20稳健(基准)',sig_base20),
    ('金牌狙击紧_core(主进+量价)',sig_jp_core),
    ('金牌狙击紧_full(+筹码集中)',sig_jp_tight),
    ('金牌狙击紧_AB级',sig_jp_ab),
]

print('[3/4] 执行回测...')
results=[]
for name,fn in formulas:
    r=run(fn,name);results.append(r)
    print(f'  {name}: {r["交易数"]}笔 胜率{r["胜率"]}% 单均{r["单均净%"]} 年化{r["年化净%"]}')

print('\n'+'='*75)
print('金牌狙击紧 横向对比')
print('='*75)
print(f'| {"公式":<30} | {"交易":>5} | {"胜率":>5} | {"单均净":>7} | {"年化":>7} |')
print('|'+'-'*32+'|'+'-'*7+'|'+'-'*7+'|'+'-'*9+'|'+'-'*9+'|')
for r in sorted(results,key=lambda x:x['年化净%'],reverse=True):
    print(f'| {r["公式"]:<30} | {r["交易数"]:>5} | {r["胜率"]:>5.1f} | {r["单均净%"]:>7.2f} | {r["年化净%"]:>7.1f} |')
print(f'\n总耗时: {time.time()-t0:.0f}s')

ts=pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
path=f'D:/Hermes/同中书门下/产出/jinpai_tight_backtest_{ts}.md'
with open(path,'w',encoding='utf-8') as f:
    f.write('# 金牌狙击紧 回测报告\n\n')
    f.write(f'区间: {START}-{END} | 持仓: {HOLD}天 | top_k={TOPK}\n\n')
    f.write('| 公式 | 交易数 | 胜率% | 单均净% | 年化净% |\n')
    f.write('|------|--------|-------|---------|----------|\n')
    for r in sorted(results,key=lambda x:x['年化净%'],reverse=True):
        f.write(f'| {r["公式"]} | {r["交易数"]} | {r["胜率"]:.1f} | {r["单均净%"]:.2f} | {r["年化净%"]:.1f} |\n')
    f.write(f'\n生成: {pd.Timestamp.now()}  耗时: {time.time()-t0:.0f}s\n')
print(f'\n报告已保存: {path}')
