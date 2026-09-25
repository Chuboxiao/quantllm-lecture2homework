"""One-contract preflight (default) or explicitly enabled one-lot SimNow experiment."""
import argparse
from collections import deque
from datetime import datetime
import hashlib,json,math,os
from pathlib import Path
from queue import Empty
import signal,time

from trade_rules import TZ,TERMINAL,seconds_to_break,check_quote,entry_checks,Crossing,on_grid
from trade_journal import Journal

ROOT=Path(__file__).resolve().parents[2]
QUERY_ORDER=['instrument','margin','commission','account','position','order','trade']

class Experiment:
 def __init__(self,transport,plan,journal,log,execute=False):
  self.api=transport;self.plan=plan;self.journal=journal;self.log=log;self.execute=execute
  self.symbol=plan['symbol'];self.product=''.join(c for c in self.symbol if c.isalpha())
  self.md_ready=False;self.td_ready=False;self.settled=False;self.login={};self.status=None
  self.tables={};self.table_times={};self.todo=deque();self.query=None;self.query_rows=[];self.next_query=0
  self.quote=None;self.cross=Crossing();self.above_count=0;self.above_timestamp=None;self.orders={};self.fills={};self.open_fill=None;self.close_fill=None
  self.phase='waiting';self.dispatch_count=0;self.frozen=False;self.stop_requested=False;self.done=False;self.last_gate=None
  self.risk={};self.last_refresh=0;self.close_signal=None;self.cancel_sent={};self.seen_trade_ids=set();self.query_results=0
  if execute and journal.intents():raise RuntimeError('Persistent order intent already exists: inspect and reconcile; never automatically re-arm')
 def record(self,kind,**fields):self.log(dict(kind=kind,recorded_at=datetime.now(TZ).isoformat(),**fields))
 def freeze(self,reason):
  if not self.frozen:self.record('MANUAL_REVIEW_REQUIRED',reason=reason,phase=self.phase)
  self.frozen=True;self.cross.reset()
  if self.execute:self.journal.put('frozen',reason)
 def request(self,method,fields=None,market=False):
  rid,rc=self.api.request(method,fields,market)
  self.record('request_result',method=method,request_id=rid,return_code=rc)
  if rc:self.freeze('immediate request failure: '+method)
  return rid,rc
 def queue_refresh(self):
  if not self.query and not self.todo:
   self.todo.extend(['account','position','order']);self.last_refresh=time.monotonic()
 def ready_gate(self,now,mono,opening=True):
  if not (self.md_ready and self.td_ready and self.settled):return 'connection_or_settlement_not_ready'
  if self.frozen:return 'manual_review_required'
  if self.status!='2' or seconds_to_break(now)<=0:return 'not_continuous_trading'
  if opening and seconds_to_break(now)<120:return 'less_than_120_seconds_to_break'
  if 'instrument' not in self.tables:return 'missing_contract'
  ins=self.tables['instrument'][0] if self.tables['instrument'] else {}
  if not self.quote:return 'missing_quote'
  reason,_=check_quote(self.quote,now,mono,self.login.get('TradingDay'),ins.get('PriceTick',0),opening)
  if reason:return reason
  if not opening:return ''
  threshold=self.plan.get('threshold')
  if threshold is not None and (not on_grid(threshold,ins['PriceTick']) or not self.quote['LowerLimitPrice']<threshold<self.quote['UpperLimitPrice']):return 'threshold_outside_limits_or_tick'
  if ins.get('ExpireDate','')<self.login.get('TradingDay',''):return 'expired_contract'
  if self.execute:
   deadline=datetime.fromisoformat(self.plan['valid_until'])
   if now>deadline:return 'approved_parameters_expired'
  if any(k not in self.tables for k in QUERY_ORDER):return 'preflight_queries_incomplete'
  if any(mono-self.table_times[k]>20 for k in ['account','position','order']):return 'account_snapshot_stale'
  if not self.tables['margin'] or not self.tables['commission'] or not self.tables['account']:return 'risk_rates_or_funds_missing'
  reason,self.risk=entry_checks(ins,self.tables['margin'][0],self.tables['commission'][0],self.tables['account'][0],self.tables['position'],self.tables['order'],self.quote,self.plan['max_loss'])
  return reason
 def owns(self,d):
  if d.get('InstrumentID')!=self.symbol:return None
  for role,intent in self.journal.intents().items():
   if d.get('OrderRef')!=intent['OrderRef']:continue
   if 'FrontID' in d and (d['FrontID']!=intent['FrontID'] or d['SessionID']!=intent['SessionID']):continue
   known=self.orders.get(role,{})
   if known.get('OrderSysID') and d.get('OrderSysID')!=known['OrderSysID']:continue
   return role
  return None
 def handle(self,e):
  now=time.monotonic();kind=e['kind'];d=e['data']
  if kind=='tick':
   if d.get('InstrumentID')==self.symbol:
    self.quote={**d,'received_mono':e['received_mono']}
    self.log(e)
   return
  if kind=='status':
   self.log(e)
   if (d.get('InstrumentID') in (self.symbol,self.product) or d.get('ExchangeInstID') in (self.symbol,self.product)) and d.get('ExchangeID')=='SHFE':
    self.status=d['InstrumentStatus']
    if self.status!='2':self.cross.reset()
   return
  self.log(e)
  if e['error_id']:
   self.freeze(kind+': '+e.get('error_message','')+' ('+str(e['error_id'])+')')
  if kind in ('md_disconnected','td_disconnected'):
   self.md_ready=False;self.td_ready=False;self.settled=False;self.status=None
   self.freeze('disconnected; reconnect may inspect only')
  elif kind=='md_connected':self.api.login(market=True)
  elif kind=='td_connected':self.api.authenticate()
  elif kind=='md_login' and not e['error_id']:
   self.md_ready=True;rc=self.api.md.subscribeMarketData(self.symbol)
   self.record('subscribe_request',symbol=self.symbol,return_code=rc)
   if rc:self.freeze('subscribe request failed')
  elif kind=='auth' and not e['error_id']:self.api.login()
  elif kind=='login' and not e['error_id']:
   self.td_ready=True;self.login=d;self.api.settle()
  elif kind=='settlement' and not e['error_id']:
   self.settled=True;self.todo=deque(QUERY_ORDER);self.query=None;self.tables={};self.table_times={};self.next_query=now+1
  elif kind.startswith('qry_'):
   name=kind[4:]
   if not self.query or e['request_id']!=self.query['id']:return
   if d and (name=='account' or d.get('InstrumentID')==self.symbol):self.query_rows.append(d)
   if e['last']:
    self.tables[name]=self.query_rows;self.table_times[name]=now;self.query=None;self.next_query=now+1;self.query_results+=1
    if name=='order':
     for row in self.tables[name]:self.order_update(row,now,query=True)
    elif name=='trade':
     for row in self.tables[name]:self.trade_update(row,now)
  elif kind=='rtn_order':self.order_update(d,now)
  elif kind=='rtn_trade':self.trade_update(d,now)
 def order_update(self,d,now,query=False):
  if not self.execute:return
  role=self.owns(d)
  if not role:
   if not query and self.execute:self.freeze('external order activity during exclusive experiment')
   return
  previous=self.orders.get(role,{})
  self.orders[role]={**d,'first_report_mono':previous.get('first_report_mono',now)}
  self.journal.put(role+'_order',d)
  if d.get('OrderSubmitStatus')=='4':self.freeze('order rejected')
  status=d.get('OrderStatus')
  if status in ('2','4','5'):
   if int(d.get('VolumeTraded',0)) and not self.fills.get(role):self.freeze('terminal order indicates missing trade callback')
   elif role=='open' and not self.open_fill:self.phase='canceled';self.done=True
   elif role=='close' and not self.close_fill:self.freeze('close order terminated without complete fill')
 def trade_update(self,d,now):
  if not self.execute:return
  role=self.owns(d)
  if not role:
   return
  identity='|'.join(str(d.get(k,'')) for k in ('ExchangeID','TradingDay','TradeID'))
  if not d.get('TradeID'):self.freeze('trade missing identity');return
  if not self.journal.fill(identity,d):return
  intent=self.journal.intents()[role]
  if d.get('TradingDay')!=intent['TradingDay'] or d.get('Direction')!=intent['Direction'] or d.get('OffsetFlag')!=intent['CombOffsetFlag']:
   self.freeze('trade identity/direction/offset mismatch');return
  if int(d.get('Volume',0))!=1 or self.fills.get(role):self.freeze('unexpected fill quantity');return
  self.fills[role]=d;self.journal.put(role+'_fill',d)
  if role=='open':
   self.open_fill={**d,'filled_mono':now};self.phase='holding'
  else:
   self.close_fill=d;self.phase='verifying_flat';self.todo.clear();self.todo.extend(['position','order','trade','account'])
 def send(self,role,price):
  if not self.execute:raise RuntimeError('Inspection cannot send orders')
  if self.frozen or not (self.md_ready and self.td_ready and self.settled):raise RuntimeError('Order dispatch while not ready')
  now=time.monotonic();q=self.quote;ins=self.tables['instrument'][0]
  existing=self.journal.intents()
  if role in existing:self.freeze('attempt to repeat order intent');return
  if role=='close' and (not self.open_fill or self.open_fill.get('TradingDay')!=self.login.get('TradingDay')):
   self.freeze('no confirmed same-day own fill; close offset requires reconciliation');return
  ref=max(int(self.login.get('MaxOrderRef') or 0)+1,int(time.time()*1000)%1000000000000)
  if existing:ref=max(ref,max(int(v['OrderRef']) for v in existing.values())+1)
  request=dict(InstrumentID=self.symbol,ExchangeID='SHFE',OrderRef=str(ref),Direction='0' if role=='open' else '1',CombOffsetFlag='0' if role=='open' else '3',LimitPrice=price,VolumeTotalOriginal=1,OrderPriceType='2',CombHedgeFlag='1',ContingentCondition='1',ForceCloseReason='0',IsAutoSuspend=0,TimeCondition='3',VolumeCondition='1',MinVolume=1)
  intent={**request,'FrontID':self.login['FrontID'],'SessionID':self.login['SessionID'],'TradingDay':self.login['TradingDay'],'sent_mono':now,'created_at':datetime.now(TZ).isoformat(),'quote':q,'plan':self.plan}
  self.journal.reserve(role,intent)
  self.record('order_intent_committed',role=role,request=request,quote=q,risk=self.risk)
  self.phase=role+'_pending'
  self.dispatch_count+=1
  self.request('reqOrderInsert',{**self.api.identity(),'UserID':self.api.config['userid'],**request})
 def cancel(self,role):
  if role in self.cancel_sent or not self.td_ready or not self.settled:return
  order=self.orders.get(role)
  if not order or order.get('OrderStatus') not in ('1','3'):return
  intent=self.journal.intents()[role]
  fields={**self.api.identity(),'InstrumentID':self.symbol,'ExchangeID':'SHFE','OrderRef':intent['OrderRef'],'FrontID':intent['FrontID'],'SessionID':intent['SessionID'],'ActionFlag':'0'}
  self.journal.put(role+'_cancel_intent',fields|{'InvestorID':'[redacted]','BrokerID':'[redacted]'})
  self.cancel_sent[role]=time.monotonic();self.record('cancel_intent',role=role,OrderRef=intent['OrderRef'],OrderSysID=order.get('OrderSysID'))
  self.request('reqOrderAction',fields)
 def step(self):
  mono=time.monotonic();now=datetime.now(TZ)
  if self.query and mono-self.query['started']>10:
   self.freeze('query response timeout');self.query=None;self.todo.clear()
  if self.settled and not self.query and self.todo and mono>=self.next_query:
   name=self.todo.popleft();rid,rc=self.api.query(name,self.symbol)
   self.record('query_request',query=name,request_id=rid,return_code=rc)
   if rc:self.freeze('query request failed')
   else:self.query=dict(kind=name,id=rid,started=mono);self.query_rows=[]
  if self.phase=='verifying_flat' and not self.query and not self.todo and not self.frozen:
   positions=self.tables.get('position',[]);orders=self.tables.get('order',[])
   if any(p.get('Position',0) for p in positions) or any(o.get('OrderStatus') not in TERMINAL for o in orders):self.freeze('post-close position/order is not flat')
   else:self.phase='closed';self.done=True;self.journal.put('completed',True)
  if self.phase=='waiting':
   if mono-self.last_refresh>10 and 'trade' in self.tables:self.queue_refresh()
   gate=self.ready_gate(now,mono)
   if gate!=self.last_gate:self.record('entry_gate',reason=gate or 'ready',risk=self.risk);self.last_gate=gate
   if gate or self.stop_requested:
    self.cross.reset();self.above_count=0;self.above_timestamp=None
    return
   if self.plan.get('threshold') is None:
    if not self.execute or self.plan.get('threshold_offset_ticks')!=2:return
    step=self.tables['instrument'][0]['PriceTick']
    self.plan['threshold']=round((round(self.quote['LastPrice']/step)+2)*step,8)
    self.journal.put('fixed_threshold',self.plan['threshold'])
    self.record('threshold_fixed_once',threshold=self.plan['threshold'],reference_quote=self.quote)
    # Start below the fixed threshold; never move it again on later ticks.
    self.cross.reset();self.above_count=0;self.above_timestamp=None
   reason,ts=check_quote(self.quote,now,mono,self.login['TradingDay'],self.tables['instrument'][0]['PriceTick'])
   crossed=self.cross.update(self.quote['LastPrice'],ts,self.plan['threshold'])
   if self.plan.get('trigger_mode','crossing')=='two_valid_ticks':
    if self.above_timestamp is None or ts>self.above_timestamp:
     self.above_timestamp=ts
     self.above_count=self.above_count+1 if self.quote['LastPrice']>self.plan['threshold'] else 0
    triggered=self.above_count>=2
   else:triggered=crossed
   if triggered:
    self.record('price_crossed',quote=self.quote,threshold=self.plan['threshold'])
    if self.execute:self.send('open',self.quote['AskPrice1'])
  elif self.phase in ('open_pending','close_pending'):
   role=self.phase.split('_')[0];intent=self.journal.intents()[role];order=self.orders.get(role)
   age=mono-intent['sent_mono']
   acknowledged=order and order.get('OrderStatus') in TERMINAL|{'1','3'}
   if not acknowledged and not self.fills.get(role) and age>3:
    self.freeze('3 seconds without order acknowledgement; no resend')
    if not self.query and not self.todo:self.todo.extend(['order','trade','position'])
   if order and order.get('OrderStatus') in ('1','3') and (age>10 or self.stop_requested):self.cancel(role)
   if role in self.cancel_sent and mono-self.cancel_sent[role]>5 and order.get('OrderStatus') not in TERMINAL:self.freeze('cancel acknowledgement timeout')
   if order and order.get('OrderStatus')=='0' and not self.fills.get(role) and age>5:self.freeze('filled order without trade details')
  elif self.phase=='holding':
   if self.frozen:return
   ins=self.tables['instrument'][0]
   if self.quote:
    reason,ts=check_quote(self.quote,now,mono,self.login['TradingDay'],ins['PriceTick'],opening=False)
    if not reason:
     pnl=(self.quote['BidPrice1']-self.open_fill['Price'])*ins['VolumeMultiple']-self.risk.get('fee_reserve',0)
     if pnl<=-self.plan['max_loss']:self.close_signal='stop_loss'
   if mono-self.open_fill['filled_mono']>=self.plan['hold_seconds']:self.close_signal=self.close_signal or '60_second_exit'
   if self.stop_requested:self.close_signal=self.close_signal or 'user_stop'
   if seconds_to_break(now)<30:self.close_signal=self.close_signal or 'session_ending'
   if self.close_signal:
    gate=self.ready_gate(now,mono,opening=False)
    if not gate:
     self.record('close_trigger',reason=self.close_signal,quote=self.quote)
     self.send('close',round(max(self.quote['LowerLimitPrice'],self.quote['BidPrice1']-2*ins['PriceTick']),8))
    elif gate!=self.last_gate:self.record('close_blocked',reason=gate);self.last_gate=gate
 def summary(self):
  return dict(orders_sent_this_run=self.dispatch_count,mode='execute' if self.execute else 'inspect',symbol=self.symbol,phase=self.phase,frozen=self.frozen,md_ready=self.md_ready,td_ready=self.td_ready,settled=self.settled,trading_day=self.login.get('TradingDay'),instrument_status=self.status,entry_gate=self.last_gate,risk=self.risk,tables=self.tables,latest_quote=self.quote,own_orders=self.orders,own_fills=self.fills,persistent_intents=self.journal.intents(),opening_orders_sent=len([k for k in self.journal.intents() if k=='open']),closing_orders_sent=len([k for k in self.journal.intents() if k=='close']))

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--plan',type=Path,default=ROOT/'configs/trade.example.json')
 parser.add_argument('--config',type=Path,default=ROOT/'configs/local/simnow.json')
 parser.add_argument('--execute',action='store_true',help='Enable approved order parameters; default inspection never sends orders')
 parser.add_argument('--duration',type=float,default=None,help='inspection seconds / entry observation deadline; defaults 45 / 300')
 args=parser.parse_args()
 if args.duration is None:args.duration=300 if args.execute else 45
 if not math.isfinite(args.duration) or args.duration<=0:parser.error('duration must be positive')
 plan=json.loads(args.plan.read_text());cfg=json.loads(args.config.read_text())
 if cfg['environment']!='simnow' or cfg['brokerid']!='9999':parser.error('SimNow only')
 allowed={'tcp://182.254.243.31:30001','tcp://180.168.146.187:10201','tcp://180.168.146.187:10202'}
 if cfg['td_address'] not in allowed:parser.error('Unreviewed trading endpoint')
 if plan['exchange']!='SHFE' or plan['volume']!=1 or plan['direction']!='buy' or not plan['symbol'].startswith(('au','ag')):parser.error('This experiment supports one SHFE gold/silver long lot only')
 if plan.get('trigger_mode','crossing') not in ('crossing','two_valid_ticks'):parser.error('Unknown trigger mode')
 if not math.isfinite(plan['max_loss']) or plan['max_loss']<=0 or plan['hold_seconds']!=60:parser.error('Explicit positive max_loss and hold_seconds=60 required')
 if args.execute:
  anchored=plan.get('threshold') is None and plan.get('threshold_offset_ticks')==2
  if not anchored and (not isinstance(plan.get('threshold'),(float,int)) or not math.isfinite(plan['threshold']) or plan['threshold']<=0):parser.error('Execution needs a fixed threshold or first-ready quote + 2 ticks')
  try:deadline=datetime.fromisoformat(plan['valid_until'])
  except (KeyError,ValueError,TypeError):parser.error('Execution needs valid_until with timezone')
  if deadline.tzinfo is None or not datetime.now(TZ)<deadline:parser.error('Approved parameter validity expired')
 os.chdir(ROOT);(ROOT/'.vntrader').mkdir(exist_ok=True)
 output=ROOT/'reports/local'/('trade_'+datetime.now(TZ).strftime('%Y%m%d_%H%M%S_%f'));output.mkdir();(output/'flow').mkdir()
 statekey=hashlib.sha256((cfg['brokerid']+':'+cfg['userid']).encode()).hexdigest()[:16]
 journal=Journal(ROOT/'data/trade_state'/f'{statekey}.sqlite')
 if args.execute and journal.intents():
  journal.close();parser.error('Existing persistent intent: execution refused before connecting; inspect/reconcile first')
 from trade_transport import Transport
 api=Transport(cfg,output/'flow')
 events=(output/'events.jsonl').open('w')
 def log(e):
  events.write(json.dumps(e,ensure_ascii=False)+'\n');events.flush()
  if e['kind']!='tick':print(json.dumps(e,ensure_ascii=False),flush=True)
 engine=Experiment(api,plan,journal,log,args.execute)
 stopping=False
 def signal_stop(*_):
  nonlocal stopping
  stopping=True;engine.stop_requested=True
 signal.signal(signal.SIGINT,signal_stop);signal.signal(signal.SIGTERM,signal_stop)
 start=time.monotonic();end=start+args.duration;exit_deadline=None
 print('Mode: '+('EXECUTE' if args.execute else 'INSPECT (no orders)')+'; '+str(output),flush=True)
 try:
  api.start()
  while not engine.done:
   now=time.monotonic()
   if not args.execute and (now>=end or stopping):break
   if args.execute and now>=end and engine.phase=='waiting':break
   if args.execute and (stopping or now>=end+120):
    engine.stop_requested=True
    if engine.phase in ('waiting','canceled','closed'):break
    if exit_deadline is None:exit_deadline=now+20
    if now>=exit_deadline:engine.freeze('shutdown cannot verify flat state');break
   engine.step()
   try:engine.handle(api.queue.get(timeout=.05))
   except Empty:pass
   if engine.frozen and args.execute:
    if exit_deadline is None:exit_deadline=time.monotonic()+15;engine.todo.extend(['order','trade','position'])
    elif time.monotonic()>=exit_deadline:break
 finally:
  api.close();summary=engine.summary();summary['elapsed_seconds']=round(time.monotonic()-start,2)
  (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
  events.close();journal.close();print('Summary: '+str(output/'summary.json'),flush=True)
 return 0 if (engine.phase=='closed' if args.execute else engine.md_ready and engine.td_ready and engine.settled and not engine.frozen) else 2
if __name__=='__main__':raise SystemExit(main())
