"""日线公式回测 v3 - 从缓存跑信号"""
import pickle, time, pandas as pd, numpy as np, struct, os
from collections import defaultdict

inds = pickle.load(open('/tmp/inds.pkl','rb'))
print(f'loaded {len(inds)} stocks')

def parse_day():
    p='D:/TDX/vipdoc/sh/lday/sh000001.day'
    with open(p,'rb') as f: raw=f.read()
    rows=[]
    for i in range(0,len(raw)-31,32):
        try:
            d=struct.unpack('<I',raw[i:i+4])[0]
            c=struct.unpack('<I',raw[i+16:i+20])[0]/1000
            rows.append((d,c))
        except: break
    return pd.DataFrame(rows,columns=['d','c']).set_index('d').sort_index()

idx=parse_day()
ma60=idx.c.rolling(60).mean()
bull=((idx.c>ma60)&(ma60>ma60.shift(5))).astype(int)
bull_dates=set(bull[bull==1].index.astype(int))
print(f'bull dates: {len(bull_dates)}')

def _max(a,b): return a.clip(lower=b)

def sig_yaogu(ind): return (ind['wave']*25>80)
def sig_huangjin_yan(ind):
    p60=ind['pos60']; retail=p60.rolling(6).mean()
    return (p60>retail)&(retail>=retail.shift(1))&(p60<35)&(ind['pos120']<25)
def sig_wushuang5(ind):
    return (ind['rs50']>0.03)&(ind['wave']<3.5)&(ind['c']>ind['dcz']*0.98)&(ind['ent']>0.5)&(ind['dif']>-0.15)
def sig_zj20wj(ind):
    abs5=abs(ind['r0'].shift(1))+abs(ind['r0'].shift(2))+abs(ind['r0'].shift(3))+abs(ind['r0'].shift(4))+abs(ind['r0'].shift(5))
    att=(ind['r0']-abs5/2>0)&(ind['avg']>ind['avg'].shift(1))
    return att&(ind['ma20']>ind['ma20'].shift(1))&(ind['c']>ind['ma20'])
def sig_zj20g(ind):
    return sig_zj20wj(ind)&(ind['avg']<0.8)&(ind['c']>ind['ma5'])&(ind['v']>ind['vma5'])&(ind['ema3']>ind['ema7'])&(ind['l']<=ind['ma20']*1.015)
def sig_huangjin(ind):
    C=ind['c'];ma60=ind['ma60'];ma120=ind['ma120'];ma45=ind['ma45'];ma90=ind['ma90'];ma30=ind['ma30']
    layers=(C>ma60)&(C>=ma120)&(C>_max(ma45,ma90))&(C>_max(ma30,ma60))
    if not layers.any(): return layers
    ma_arr=[C>ind[f'ma{p}'] for p in [5,13,21,34,55,89,144,233]]
    qx=sum(ma_arr)-3.8
    pct=ind['pct'];dcz=ind['dcz'];vat=ind['vrat']
    att=(pct>5)&(dcz>dcz.shift(1))&(vat>1.5)&(ind['ma20']>ind['ma20'].shift(1))&(C>ind['ma20'])
    main=(ind['r0']>0)&(ind['avg']>ind['avg'].shift(1))
    return layers&(qx>0)&att&main&(ind['avg']<2.5)
def sig_jinpai(ind): return sig_huangjin(ind)
def sig_4wei(ind):
    C=ind['c'];ma60=ind['ma60'];ma120=ind['ma120'];ma45=ind['ma45'];ma90=ind['ma90'];ma30=ind['ma30']
    layers=(C>ma60)&(C>=ma120)&(C>_max(ma45,ma90))&(C>_max(ma30,ma60))
    if not layers.any(): return layers
    ma_arr=[C>ind[f'ma{p}'] for p in [5,13,21,34,55,89,144,233]]
    qx=sum(ma_arr)-3.8
    r0=ind['r0'];avg=ind['avg'];m20=ind['ma20'];vat=ind['vrat'];dcz=ind['dcz']
    A=(r0>0)&(avg>avg.shift(1))&(m20>m20.shift(1))&(C>m20)&(vat>1.5)&(C>dcz)
    B=(r0>0)&(avg>avg.shift(1))&(dcz>=dcz.shift(1))&(avg<2.3)&(~A)
    return layers&(qx>0)&(A|B)
def sig_dczzc(ind):
    C=ind['c'];m20=ind['ma20'];rs50=ind['rs50'];rs120=ind['pos120']
    low=ind['l'];vat=ind['vrat'];pct=ind['pct'];dcz=ind['dcz']
    strong=(rs50>0.05)|(rs120>0.08)
    overlap=abs(m20-dcz)/(dcz+0.001)*100<8
    ma20u=m20>=m20.shift(1)*0.995;c_above=C>m20*0.98;dczu=C>dcz*0.98
    ldn=(low<=m20*1.015)&(C>=dcz*0.96);fund=(pct>1)&(pct<8.5)&(vat>0.9)
    sub=(C>ind['ema3'])&(ind['ema3']>ind['ma5'])
    return strong&overlap&ma20u&c_above&dczu&ldn&fund&sub
def sig_qzjs(ind):
    r0=ind['r0'];avg=ind['avg'];dcz=ind['dcz'];vat=ind['vrat'];C=ind['c']
    main=(r0>0)&(avg>=avg.shift(1))&(avg.shift(1)<avg.shift(2))
    return main&(dcz>dcz.shift(5))&(C>=dcz)&(vat>1.5)&(ind['ema3']>ind['ema7'])
def sig_tiemu(ind):
    C=ind['c'];dif=ind['dif'];m20=ind['ma20'];atr=ind['atr20']
    ma45=ind['ma45'];ma90=ind['ma90'];ma30=ind['ma30'];ma60=ind['ma60']
    core=50+20*(dif-m20)/(atr+0.0001)
    core_p=50+20*(dif.shift(1)-m20.shift(1))/(atr.shift(1)+0.0001)
    core_p2=50+20*(dif.shift(2)-m20.shift(2))/(atr.shift(2)+0.0001)
    hook=(core>core_p)&(core_p<=core_p2)
    mid=(C>_max(ma45,ma90))&(C>_max(ma30,ma60))
    a15=((ind['pct']>5)&(ind['ent']>0.04)&(ind['vrat']>1.5)).rolling(15).sum()>0
    act=atr/(C+0.001)>0.04
    return (core<42)&hook&mid&a15&act
def sig_obv(ind):
    C=ind['c'];m20=ind['ma20'];dcz=ind['dcz'];dif=ind['dif'];dea=ind['dea']
    jc=(dif>dea)&(dif.shift(1)<=dea.shift(1))
    zls=(ind['vrat']>1.1)&(ind['pct']>1.0)
    m20o=(C>m20)&(m20>=m20.shift(1))
    return jc&zls&m20o&(C>dcz)

formulas=[
    ('妖股爆发',sig_yaogu),('黄金右侧严',sig_huangjin_yan),('终极无双5',sig_wushuang5),
    ('主进20稳健',sig_zj20wj),('主进20改',sig_zj20g),('黄金右侧',sig_huangjin),
    ('金牌狙击主力',sig_jinpai),('四维共振主起',sig_4wei),('20日DCZ双回踩',sig_dczzc),
    ('主进OBV共振',sig_obv),('铁血埋伏',sig_tiemu),('强主进精选',sig_qzjs),
]

def run(fn,name,start,end,hold=20,topk=5):
    pool=defaultdict(list)
    for code,ind in inds.items():
        s=fn(ind)
        for ts in s[s].index:
            t=int(ts)
            if t<start or t>end or t not in bull_dates: continue
            c=ind.loc[ts,'c'];cp=ind.loc[ts-1,'c'] if ts-1 in ind.index else 0
            if cp>0 and c>=cp*1.095: continue
            r0v=ind.loc[ts,'r0'] if pd.notna(ind.loc[ts,'r0']) else 0
            rs50v=ind.loc[ts,'rs50'] if pd.notna(ind.loc[ts,'rs50']) else 0
            pool[t].append((code,r0v+abs(rs50v)*100))
    sel=set()
    for t in pool:
        pool[t].sort(key=lambda x:x[1],reverse=True)
        for code,score in pool[t][:topk]: sel.add((code,t))
    holdings=[]
    for code,t in sel:
        ind=inds[code];entry=ind.loc[t,'c'];m20s=ind['ma20'];cd=t+1;days=0;ex=None
        while cd not in ind.index and cd<end+300: cd+=1
        if cd>=end+300: continue
        while days<hold and cd in ind.index:
            c=ind.loc[cd,'c'];mv=m20s.loc[cd] if pd.notna(m20s.loc[cd]) else 0
            if mv>0 and c<mv*0.98: ex=c;break
            days+=1;cd+=1
            while cd not in ind.index and cd<end+300: cd+=1
        if ex is None:
            if cd in ind.index: ex=ind.loc[cd,'c']
            else: continue
        if ex<=0: continue
        net=ex/entry-1-0.00232-0.002
        holdings.append({'code':code,'T':t,'ex':ex,'net':net})
    if not holdings: return {'公式':name,'交易数':0,'胜率':0,'单均净%':0,'年化净%':0}
    df=pd.DataFrame(holdings);win=(df.net>0).mean()*100;mn=df.net.mean()*100
    span=(end-start)/365;nyr=len(df)/span;annual=((1+df.net.mean())**nyr-1)*100
    return {'公式':name,'交易数':len(df),'胜率':round(win,1),'单均净%':round(mn,2),'年化净%':round(annual,1)}

t0=time.time();start=20230101;end=20251231;results=[]
for name,fn in formulas:
    r=run(fn,name,start,end,20,5);results.append(r)
    print(f'  {name}: {r["交易数"]}笔 胜率{r["胜率"]}% 单均{r["单均净%"]} 年化{r["年化净%"]}')
print()
print('| 公式 | 交易 | 胜率 | 单均净 | 年化 |')
print('|------|------|------|--------|------|')
for r in sorted(results,key=lambda x:x['年化净%'],reverse=True):
    print(f'| {r["公式"]} | {r["交易数"]} | {r["胜率"]} | {r["单均净%"]} | {r["年化净%"]} |')
print(f'总耗时: {time.time()-t0:.0f}s')
