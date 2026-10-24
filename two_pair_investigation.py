"""Offline research only. Hourly proxy data; next open execution."""
from pathlib import Path
import itertools, json
import numpy as np
import pandas as pd

root=Path('C:/Users/kimbu/Desktop/history/history')
idx=pd.date_range('2026-03-19','2026-10-05 15:00',freq='h',tz='UTC')
cuts=[0,idx.searchsorted(pd.Timestamp('2026-07-14 08:00',tz='UTC')),idx.searchsorted(pd.Timestamp('2026-08-24 23:00',tz='UTC')),len(idx)]
raw={s:pd.read_csv(root/(s+'.csv'),parse_dates=['time']).set_index('time').sort_index().reindex(idx) for s in ['BTC','ETH','EWY']}

def run(A,B,feat,cfg,a,b,fee=.0014):
 win,cut,look,thr,profit,stop,hold,filt=cfg
 corr,beta,gap,vol=feat[win,look]; ao=A.open.to_numpy();bo=B.open.to_numpy();ac=A.close.to_numpy();bc=B.close.to_numpy()
 out=[];t=a
 while t<b-2:
  if not (np.isfinite(gap[t]) and corr[t]>=cut and abs(gap[t])>=thr and (filt==0 or vol[t]>=filt) and np.isfinite([ao[t+1],bo[t+1]]).all()): t+=1;continue
  e=t+1;g=gap[t];bt=beta[t];da=np.sign(g)*np.sign(bt);db=-np.sign(g);x=e+1;reason='time'
  while x<b-1:
   if not np.isfinite([ac[x-1],bc[x-1],ao[x],bo[x]]).all(): x+=1;continue
   move=np.log(bc[x-1]/bo[e])-bt*np.log(ac[x-1]/ao[e]);recovery=-np.sign(g)*move/abs(g)
   if recovery>=profit: reason='recovery';break
   if recovery<=-stop: reason='widen';break
   if x-e>=hold: break
   x+=1
  if x>=b-1: break
  pa=ao[x]/ao[e];pb=bo[x]/bo[e];gross=.25*(da*(pa-1)+db*(pb-1));cost=fee*(.5+.25*(pa+pb))
  out.append(dict(entry=str(idx[e]),exit=str(idx[x]),pnl=100*(gross-cost),gross=100*gross,cost=100*cost,btc=100*da*(pa-1),other=100*db*(pb-1),gap=100*g,corr=corr[t],vol=100*vol[t],reason=reason,h=x-e))
  t=x
 return out

def summary(tr):
 p=np.array([x['pnl'] for x in tr]); cum=np.r_[0,np.cumsum(p)]; return dict(n=len(p),total=round(float(p.sum()),4),wins=int((p>0).sum()),worst=round(float(p.min()),4) if len(p) else None,best=round(float(p.max()),4) if len(p) else None,without_best=round(float(p.sum()-p.max()),4) if len(p) else None,drawdown=round(float(np.max(np.maximum.accumulate(cum)-cum)),4))

for sym in ['ETH','EWY']:
 A=raw['BTC']; B=raw[sym];ra=np.log(A.close).diff();rb=np.log(B.close).diff();feat={}
 for w in (24,72,168):
  c=ra.rolling(w,min_periods=w).corr(rb); beta=ra.rolling(w,min_periods=w).cov(rb)/ra.rolling(w,min_periods=w).var();vol=ra.rolling(24,min_periods=24).std()
  for l in (3,6,12): feat[w,l]=(c.to_numpy(),beta.to_numpy(),(np.log(B.close/B.close.shift(l))-beta*np.log(A.close/A.close.shift(l))).to_numpy(),vol.to_numpy())
 base=(72,.7,3,.015,.5,.5,24,0) if sym=='ETH' else (24,.7,12,.015,1.,1.,12,0)
 # BTC volatility gates fixed ex ante (hourly standard deviation 0, .3%, .6%).
 candidates=list(itertools.product((24,72,168),(.7,.8),(3,6,12),(.003,.007,.015),(.5,1.),(.5,1.),(6,12,24),(0,.003,.006)))
 ranked=[]
 for cfg in candidates:
  tr=run(A,B,feat,cfg,cuts[0],cuts[1]);
  if len(tr)>=10: ranked.append((sum(x['pnl'] for x in tr),cfg))
 ranked.sort(key=lambda x:x[0],reverse=True)
 print('PAIR',sym,'rows',len(A),'nonmissing',int((A.close.notna() & B.close.notna()).sum()),'candidates',len(candidates),'eligible',len(ranked),flush=True)
 for name,cfg in [('baseline',base),('best_train',ranked[0][1])]:
  results=[run(A,B,feat,cfg,cuts[i],cuts[i+1]) for i in range(3)]
  print('MODEL',name,'config',cfg,'stats',json.dumps([summary(t) for t in results]),flush=True)
  for i,t in enumerate(results):
   print('EXTREMES',name,i,json.dumps(sorted(t,key=lambda x:x['pnl'])[:2]+sorted(t,key=lambda x:x['pnl'],reverse=True)[:2],default=lambda v:v.item()),flush=True)
  print('HIGH_COST',name,json.dumps([summary(run(A,B,feat,cfg,cuts[i],cuts[i+1],.0028)) for i in range(3)]),flush=True)
