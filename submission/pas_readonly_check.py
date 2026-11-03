"""Public PAS order books and public wallet state, no signing or orders."""
import datetime,json,time,urllib.request,urllib.error
URL='https://api.hyperliquid-testnet.xyz/info'
W='0x1cFBf2754D107E60fcC820174fe4e38612C54Fa3'
def query(payload):
 req=urllib.request.Request(URL,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
def report(label,payload,handler=lambda x:x):
 try:print(label,json.dumps(handler(query(payload)),default=str),flush=True)
 except Exception as ex:print(label,'ERROR',type(ex).__name__,str(ex),flush=True)
def book(v):
 levels=v['levels']; bids,asks=levels
 def depth(a):
  left=18750.;qty=0.;spent=0.
  for z in a:
   p=float(z['px']);sz=float(z['sz']); take=min(left,p*sz);spent+=take;qty+=take/p;left-=take
   if left<.000001:break
  return {'depth_usd':round(sum(float(z['px'])*float(z['sz']) for z in a),2),'requested_18750_filled':round(spent,2),'vwap':round(spent/qty,6) if qty else None}
 bid=float(bids[0]['px']) if bids else None;ask=float(asks[0]['px']) if asks else None
 return {'time_ms':v.get('time'),'best_bid':bid,'best_ask':ask,'spread_pct':round(100*(ask-bid)/((ask+bid)/2),4) if bid and ask else None,'bid':depth(bids),'ask':depth(asks)}
def select_spot(v):return [b for b in v.get('balances',[]) if b.get('coin') in ('USDP','USDPR')]
def select_state(v):return {'marginSummary':v.get('marginSummary'),'crossMarginSummary':v.get('crossMarginSummary'),'withdrawable':v.get('withdrawable'),'positions':v.get('assetPositions')}
report('time',{'type':'metaAndAssetCtxs','dex':'pas'},lambda v:{'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'markets':[{**x,'context':{'markPx':y.get('markPx'),'oraclePx':y.get('oraclePx'),'funding':y.get('funding'),'openInterest':y.get('openInterest')}} for x,y in zip(v[0]['universe'],v[1]) if x['name'] in ('pas:BTC','pas:ETH','pas:EWY')]})
for s in ('BTC','ETH','EWY'):report('book_'+s,{'type':'l2Book','coin':'pas:'+s},book)
report('spot',{'type':'spotClearinghouseState','user':W},select_spot)
report('positions',{'type':'clearinghouseState','dex':'pas','user':W},select_state)
report('openorders',{'type':'openOrders','dex':'pas','user':W})
report('agents',{'type':'extraAgents','user':W})
report('mode',{'type':'userAbstraction','user':W})
