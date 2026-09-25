import copy
from datetime import datetime,timedelta
import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from trade_rules import TZ,check_quote,entry_checks,seconds_to_break,Crossing
from trade_journal import Journal
from trade import Experiment

NOW=datetime(2026,9,24,1,5,tzinfo=TZ)
PLAN=dict(symbol='au2612',exchange='SHFE',direction='buy',volume=1,threshold=1000,max_loss=100000,hold_seconds=60,valid_until='2026-09-24T02:00:00+08:00')
INS=dict(InstrumentID='au2612',ProductID='au',ExchangeID='SHFE',ProductClass='1',IsTrading=1,ExpireDate='20261215',PriceTick=1,VolumeMultiple=10)
MARGIN=dict(LongMarginRatioByMoney=.14,LongMarginRatioByVolume=0)
FEES=dict(OpenRatioByMoney=0,OpenRatioByVolume=2,CloseTodayRatioByMoney=0,CloseTodayRatioByVolume=0)
ACCOUNT=dict(CurrencyID='CNY',Balance=10000000,Available=10000000)

def quote(now=NOW,mono=100,price=1000):
 return dict(InstrumentID='au2612',TradingDay='20260924',ActionDay=now.strftime('%Y%m%d'),UpdateTime=now.strftime('%H:%M:%S'),UpdateMillisec=now.microsecond//1000,LastPrice=price,BidPrice1=price-1,AskPrice1=price+1,BidVolume1=1,AskVolume1=1,LowerLimitPrice=900,UpperLimitPrice=1100,received_mono=mono)

class Rules(unittest.TestCase):
 def test_two_clocks_and_bad_values(self):
  q=quote();self.assertEqual(check_quote(q,NOW,100,'20260924',1)[0],'')
  for update in [dict(received_mono=97),dict(UpdateTime='01:04:57'),dict(ActionDay='20260923'),dict(LastPrice=0),dict(LastPrice=float('nan')),dict(AskPrice1=None),dict(AskVolume1=0),dict(BidVolume1=0),dict(UpperLimitPrice=float('inf')),dict(TradingDay='20260923')]:
   with self.subTest(update=update):self.assertTrue(check_quote(q|update,NOW,100,'20260924',1)[0])
  self.assertTrue(check_quote(q,NOW,100,'20260924',0)[0])
 def test_price_limit_spread_and_tick(self):
  for update in [dict(LastPrice=1099,AskPrice1=1100),dict(AskPrice1=1006),dict(LastPrice=1000.5),dict(BidPrice1=1002),dict(LowerLimitPrice=1200)]:
   self.assertTrue(check_quote(quote()|update,NOW,100,'20260924',1)[0])
 def test_exit_can_use_bid_without_ask(self):
  q=quote()|dict(AskPrice1=0,AskVolume1=0,LastPrice=900,BidPrice1=900)
  self.assertTrue(check_quote(q,NOW,100,'20260924',1)[0])
  self.assertEqual(check_quote(q,NOW,100,'20260924',1,False)[0],'')
 def test_closed_sessions_and_weekend(self):
  for h,m in [(8,59),(10,20),(12,0),(15,1),(20,58),(2,31)]:
   self.assertEqual(seconds_to_break(NOW.replace(hour=h,minute=m)),0)
  self.assertGreater(seconds_to_break(NOW),0)
  self.assertEqual(seconds_to_break(datetime(2026,9,27,1,5,tzinfo=TZ)),0)
 def test_capital_and_existing_exposure(self):
  args=[INS,MARGIN,FEES,ACCOUNT,[],[],quote(),100000]
  self.assertEqual(entry_checks(*args)[0],'')
  for i,value in [(3,ACCOUNT|{'Available':100}),(3,ACCOUNT|{'Balance':100}),(3,ACCOUNT|{'Available':float('nan')}),(4,[{'Position':1}]),(4,[{'Position':0,'LongFrozen':1}]),(5,[{'OrderStatus':'a'}]),(1,{}),(2,{})]:
   a=copy.deepcopy(args);a[i]=value;self.assertTrue(entry_checks(*a)[0])
 def test_crossing_start_above_and_reset(self):
  c=Crossing();self.assertFalse(c.update(1001,NOW,1000))
  self.assertFalse(c.update(999,NOW+timedelta(seconds=1),1000))
  self.assertFalse(c.update(1002,NOW,1000))
  self.assertTrue(c.update(1001,NOW+timedelta(seconds=2),1000))
  c.reset();self.assertFalse(c.update(1001,NOW+timedelta(seconds=3),1000))

class FakeApi:
 def __init__(self,journal):self.journal=journal;self.calls=[];self.seq=0;self.config={'userid':'test'}
 def identity(self):return {'BrokerID':'9999','InvestorID':'test'}
 def request(self,method,fields=None,market=False):
  self.seq+=1;self.calls.append((method,fields))
  if method=='reqOrderInsert':
   role='open' if fields['CombOffsetFlag']=='0' else 'close'
   assert self.journal.intents()[role]['OrderRef']==fields['OrderRef'],'Intent must be durable before API call'
  return self.seq,0
 def query(self,kind,symbol):return self.request('query_'+kind,{})

class Execution(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.sqlite';self.j=Journal(self.path)
  self.api=FakeApi(self.j);self.log=[];self.now=NOW;self.mono=100
  self.clock=patch('trade.time.monotonic',side_effect=lambda:self.mono);self.clock.start()
  self.dt=patch('trade.datetime');dt=self.dt.start();dt.now.side_effect=lambda tz:self.now;dt.fromisoformat.side_effect=datetime.fromisoformat
  self.e=self.engine(True)
 def tearDown(self):self.dt.stop();self.clock.stop();self.j.close();self.tmp.cleanup()
 def engine(self,execute):
  e=Experiment(self.api,copy.deepcopy(PLAN),self.j,self.log.append,execute)
  e.md_ready=e.td_ready=e.settled=True;e.status='2'
  e.login=dict(TradingDay='20260924',FrontID=1,SessionID=2,MaxOrderRef='0')
  e.tables=dict(instrument=[INS],margin=[MARGIN],commission=[FEES],account=[ACCOUNT],position=[],order=[],trade=[])
  e.table_times={k:self.mono for k in e.tables};e.last_refresh=self.mono;e.quote=quote(self.now,self.mono)
  return e
 def advance(self,seconds,price=1001):
  self.now+=timedelta(seconds=seconds);self.mono+=seconds;self.e.quote=quote(self.now,self.mono,price)
 def cross(self):self.e.step();self.advance(.5);self.e.step()
 def fill(self,role,tradeid):
  i=self.j.intents()[role]
  return dict(InstrumentID='au2612',ExchangeID='SHFE',OrderRef=i['OrderRef'],OrderSysID='sys-'+role,TradeID=tradeid,TradingDay='20260924',Direction='0' if role=='open' else '1',OffsetFlag='0' if role=='open' else '3',Price=1002 if role=='open' else 1000,Volume=1)
 def test_threshold_anchors_once_after_risk_checks(self):
  self.e.plan['threshold']=None;self.e.plan['threshold_offset_ticks']=2
  self.e.settled=False;self.e.step();self.assertIsNone(self.e.plan['threshold'])
  self.e.settled=True;self.e.step();self.assertEqual(self.e.plan['threshold'],1002)
  self.assertFalse(self.j.intents())
  self.advance(1,1003);self.e.step();self.assertEqual(self.e.plan['threshold'],1002);self.assertIn('open',self.j.intents())
 def test_two_valid_ticks_above_fixed_threshold(self):
  self.e.plan['trigger_mode']='two_valid_ticks'
  self.e.step();self.advance(.5,1001);self.e.step()
  self.assertFalse(self.j.intents())
  self.advance(.5,1001);self.e.step()
  self.assertIn('open',self.j.intents())
 def test_inspection_never_sends(self):
  self.e=self.engine(False);self.cross();self.assertFalse(self.j.intents());self.assertFalse(self.api.calls)
 def test_unknown_session_or_no_settlement_blocks(self):
  self.e.status=None;self.cross();self.assertFalse(self.api.calls)
  self.e.status='2';self.e.settled=False;self.cross();self.assertFalse(self.api.calls)
 def test_stale_account_or_invalid_tick_resets_crossing(self):
  self.e.step();self.e.quote['LastPrice']=0;self.e.step();self.advance(.5);self.e.step();self.assertFalse(self.j.intents())
  self.e.table_times['account']=0;self.e.step();self.assertEqual(self.e.last_gate,'account_snapshot_stale')
 def test_single_open_durable_timeout_and_restart(self):
  self.cross();self.assertEqual(len(self.j.intents()),1)
  self.advance(4);self.e.step();self.assertTrue(self.e.frozen)
  self.e.step();self.assertEqual(sum(k=='reqOrderInsert' for k,_ in self.api.calls),1)
  with self.assertRaises(RuntimeError):self.engine(True)
  with self.assertRaises(sqlite3.IntegrityError):self.j.reserve('open',{})
 def test_parallel_run_excluded(self):
  with self.assertRaises(RuntimeError):Journal(self.path)
 def test_disconnect_permanently_disarms(self):
  self.cross();self.e.handle(dict(kind='td_disconnected',data={},error_id=1,error_message='disconnected'))
  self.e.md_ready=self.e.td_ready=self.e.settled=True;self.e.status='2'
  self.advance(1);self.e.step();self.assertTrue(self.e.frozen);self.assertEqual(len(self.j.intents()),1)
 def test_auto_close_after_sixty_seconds_and_dedup(self):
  self.cross();d=self.fill('open','t1');self.e.trade_update(d,self.mono);self.e.trade_update(d,self.mono)
  self.assertEqual(self.e.phase,'holding');self.advance(61);self.e.step()
  self.assertEqual(set(self.j.intents()),{'open','close'})
  close=[d for k,d in self.api.calls if k=='reqOrderInsert'][-1]
  self.assertEqual(close['CombOffsetFlag'],'3');self.assertEqual(close['VolumeTotalOriginal'],1)
  self.e.trade_update(self.fill('close','t2'),self.mono)
  self.e.todo.clear();self.e.step();self.assertEqual(self.e.phase,'closed')
 def test_stop_loss_closes_before_timer(self):
  self.e.plan['max_loss']=50;self.cross();self.e.trade_update(self.fill('open','t1'),self.mono)
  self.advance(1,price=995);self.e.step();self.assertEqual(self.e.close_signal,'stop_loss');self.assertIn('close',self.j.intents())
 def test_no_bid_defers_exit_without_guessing_price(self):
  self.cross();self.e.trade_update(self.fill('open','t1'),self.mono);self.advance(61)
  self.e.quote['BidVolume1']=0;self.e.step();self.assertNotIn('close',self.j.intents());self.assertEqual(self.e.last_gate,'empty_book')
 def test_confirmed_pending_order_cancelled_once(self):
  self.cross();i=self.j.intents()['open']
  self.e.order_update(dict(InstrumentID='au2612',OrderRef=i['OrderRef'],FrontID=1,SessionID=2,OrderSysID='sys-open',OrderStatus='3',VolumeTraded=0),self.mono)
  self.advance(11);self.e.step();self.e.step()
  self.assertEqual(sum(k=='reqOrderAction' for k,_ in self.api.calls),1)
 def test_post_close_query_failure_cannot_claim_flat(self):
  self.e.phase='verifying_flat';self.e.freeze('query failed');self.e.step();self.assertFalse(self.e.done)

if __name__=='__main__':unittest.main()
