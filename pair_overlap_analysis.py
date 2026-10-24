"""Offline comparison of previously chosen pairs; no exchange connection."""
import ast, json, os
from pathlib import Path
import numpy as np
import pandas as pd

src=Path(__file__).with_name('two_pair_investigation.py')
tree=ast.parse(src.read_text(encoding='utf-8'))
module=ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef)],type_ignores=[])
idx=pd.date_range('2026-03-19','2026-10-05 15:00',freq='h',tz='UTC')
env={'np':np,'pd':pd,'idx':idx}
exec(compile(module,str(src),'exec'),env)
run=env['run']
root=Path(os.environ.get('HISTORY_DIR', 'C:/Users/kimbu/Desktop/history/history'))
if not root.exists():
 raise FileNotFoundError('Set HISTORY_DIR to the folder containing BTC.csv, ETH.csv, and EWY.csv.')
data={s:pd.read_csv(root/(s+'.csv'),parse_dates=['time']).set_index('time').sort_index().reindex(idx) for s in ['BTC','ETH','EWY']}
cuts=[0,idx.searchsorted(pd.Timestamp('2026-07-14 08:00',tz='UTC')),idx.searchsorted(pd.Timestamp('2026-08-24 23:00',tz='UTC')),len(idx)]
cfgs={'ETH':(72,.7,3,.015,.5,.5,24,0),'EWY':(24,.7,12,.015,1.,1.,12,0)}
alltr={}; allret={}; active={}; btcs={}
for sym,cfg in cfgs.items():
 a,b=data['BTC'],data[sym]; ra=np.log(a.close).diff();rb=np.log(b.close).diff(); w,_,l,*_=cfg
 c=ra.rolling(w,min_periods=w).corr(rb); beta=ra.rolling(w,min_periods=w).cov(rb)/ra.rolling(w,min_periods=w).var(); gap=np.log(b.close/b.close.shift(l))-beta*np.log(a.close/a.close.shift(l));vol=ra.rolling(24,min_periods=24).std()
 feat={(w,l):(c.to_numpy(),beta.to_numpy(),gap.to_numpy(),vol.to_numpy())}
 trades=[]; ret=np.zeros(len(idx)); act=np.zeros(len(idx),bool); btc=np.zeros(len(idx))
 for k in range(3):
  tt=run(a,b,feat,cfg,cuts[k],cuts[k+1]);trades+=tt
  for trade in tt:
   e=idx.get_loc(pd.Timestamp(trade['entry'])); x=idx.get_loc(pd.Timestamp(trade['exit'])); d=np.sign(gap.iloc[e-1]); da=d*np.sign(beta.iloc[e-1]); db=-d
   pa=a.open.iloc[e:x+1].to_numpy()/a.open.iloc[e];pb=b.open.iloc[e:x+1].to_numpy()/b.open.iloc[e]
   ret[e+1:x+1]+=.25*(da*np.diff(pa)+db*np.diff(pb))*100
   ret[e]-=.0014*.5*100; ret[x]-=.0014*.25*(pa[-1]+pb[-1])*100
   act[e:x]=True;btc[e:x]=da
   assert abs(ret[e:x+1].sum()-trade['pnl'])<1e-8 or e>0 and act[e-1], 'overlap or accounting mismatch'
 alltr[sym]=trades;allret[sym]=ret;active[sym]=act;btcs[sym]=btc
for j in range(3):
 a,b=cuts[j:j+2]; x=allret['ETH'][a:b];y=allret['EWY'][a:b]; u=active['ETH'][a:b];v=active['EWY'][a:b]; both=u&v
 end=idx[b] if b<len(idx) else idx[-1]+pd.Timedelta(hours=1)
 print('SPLIT',j,'ntrades',len([t for t in alltr['ETH'] if idx[a]<=pd.Timestamp(t['entry'])<end]),len([t for t in alltr['EWY'] if idx[a]<=pd.Timestamp(t['entry'])<end]),'active hours',int(u.sum()),int(v.sum()),'both',int(both.sum()),'same btc',int((both&(btcs['ETH'][a:b]==btcs['EWY'][a:b])).sum()),'opposite btc',int((both&(btcs['ETH'][a:b]!=btcs['EWY'][a:b])).sum()),'returns',round(x.sum(),4),round(y.sum(),4),'correlation',round(float(np.corrcoef(x,y)[0,1]),4),'std',round(float(x.std()),6),round(float(y.std()),6),round(float(((x+y)/2).std()),6),'signs',int(((x>0)&(y>0)&both).sum()),int(((x<0)&(y<0)&both).sum()),int(((x*y<0)&both).sum()))
 for t in alltr['ETH']:
  e=pd.Timestamp(t['entry']);z=pd.Timestamp(t['exit'])
  for s in alltr['EWY']:
   f=pd.Timestamp(s['entry']);q=pd.Timestamp(s['exit'])
   if idx[a]<=max(e,f)<end and max(e,f)<min(z,q): print('OVERLAP',json.dumps({'eth':t,'ewy':s},default=lambda v:v.item()))
