"""重建指标缓存 + 跑回测"""
import struct, os, time, pandas as pd, numpy as np, pickle
from collections import defaultdict

TDX='D:/TDX/vipdoc'; DIV={'sh':1000,'sz':10,'bj':100}
t0=time.time(); data={}
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
            if len(df)>=60: data[f'{market.upper()}{code6}']=df
print(f'load {len(data)} in {time.time()-t0:.0f}s')

def calc(df):
    C,H,L,O,V=df.c,df.h,df.l,df.o,df.v
    ind=pd.DataFrame(index=df.index)
    ind['c']=C;ind['h']=H;ind['l']=L;ind['v']=V
    for p in [5,10,13,20,21,30,34,45,55,60,89,90,120,144,233]:
        ind[f'ma{p}']=C.rolling(p).mean()
    ind['ema3']=C.ewm(span=3,adjust=False).mean();ind['ema7']=C.ewm(span=7,adjust=False).mean()
    ind['dif']=C.ewm(span=12,adjust=False).mean()-C.ewm(span=26,adjust=False).mean()
    ind['dea']=ind['dif'].ewm(span=9,adjust=False).mean()
    ind['vma5']=V.rolling(5).mean();ind['vrat']=V/(ind['vma5']+0.01)
    L10=L.rolling(10).min();H25=H.rolling(25).max()
    wave=((C-L10)/(H25-L10+0.001)*4).ewm(span=4,adjust=False).mean()
    ind['wave']=wave;ind['avg']=wave.ewm(span=3,adjust=False).mean()
    ind['r0']=((C-C.shift(1))/(C.shift(1)+0.001)*100)*ind['vrat']
    L60=L.rolling(60).min();H60=H.rolling(60).max();ind['pos60']=(C-L60)/(H60-L60+0.001)*100
    L120=L.rolling(120).min();H120=H.rolling(120).max();ind['pos120']=(C-L120)/(H120-L120+0.001)*100
    ind['dcz']=C.rolling(20).median();ind['pct']=C.pct_change()*100;ind['ent']=(C-L)/(H-L+0.001);ind['rs50']=C.pct_change(periods=50)
    # atr: 用 H-L 当代理
    ind['atr20']=((H-L).rolling(20).mean()).fillna(0)
    ind['h15']=H.rolling(15).max();ind['l15']=L.rolling(15).min();ind['v15_max']=V.rolling(15).max()
    return ind

t1=time.time();inds={}
for i,(c,df) in enumerate(data.items()):
    inds[c]=calc(df)
    if (i+1)%2000==0: print(f'  {i+1}/{len(data)}',end='\r')
print(f'calc {len(inds)} in {time.time()-t1:.0f}s, total {time.time()-t0:.0f}s')
pickle.dump(inds,open('/tmp/inds.pkl','wb'))
print('saved /tmp/inds.pkl')
