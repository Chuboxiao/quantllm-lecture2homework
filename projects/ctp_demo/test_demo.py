import unittest
import json
import tempfile
import subprocess
import sys
import os
import time
from pathlib import Path
from logic import candidates, rank_active, valid_price

HERE=Path(__file__).resolve().parent
FAKE='''
import threading,time,os
class Base:
 def createFtdcMdApi(self,*a): pass
 def createFtdcTraderApi(self,*a): pass
 def registerFront(self,*a): pass
 def subscribePrivateTopic(self,*a): pass
 def subscribePublicTopic(self,*a): pass
 def init(self): self.running=True; self.onFrontConnected()
 def exit(self):
  self.running=False
  if hasattr(self,'thread'): self.thread.join(timeout=2)
 def reqUserLogin(self,d,r): self.onRspUserLogin({}, {'ErrorID':3 if os.getenv('FAIL_LOGIN') else 0},r,True); return 0
class MdApi(Base):
 def subscribeMarketData(self,s):
  self.onRspSubMarketData({'InstrumentID':s},{'ErrorID':0},1,True)
  if os.getenv('NO_TICKS'): return 0
  def stream():
   i=0
   while self.running:
    i+=1
    self.onRtnDepthMarketData({'InstrumentID':s,'UpdateTime':'21:01:00','UpdateMillisec':i,'LastPrice':100+i,'Volume':i,'BidPrice1':100,'AskPrice1':101})
    time.sleep(.05)
  self.thread=threading.Thread(target=stream);self.thread.start();return 0
 def unSubscribeMarketData(self,s): return 0
class TdApi(Base):
 def reqAuthenticate(self,d,r): self.onRspAuthenticate({},{'ErrorID':0},r,True);return 0
 def reqSettlementInfoConfirm(self,d,r): self.onRspSettlementInfoConfirm({},{'ErrorID':0},r,True);return 0
 def reqQryInstrument(self,d,r):
  self.onRspQryInstrument({'InstrumentID':'au9999','ProductID':'au','ProductClass':'1','IsTrading':1,'ExpireDate':'20991231'},{'ErrorID':0},r,True);return 0
 def reqOrderInsert(self,*a): raise AssertionError('No order placement is allowed in this phase')
'''
class Tests(unittest.TestCase):
 def test_invalid_prices(self):
  for p in [0,-1,float('nan'),float('inf'),1.7976931348623157e308,None]: self.assertIsNone(valid_price(p))
  self.assertEqual(valid_price(123.4),123.4)
 def test_selection(self):
  c={s:{'InstrumentID':s,'ProductID':'au','ProductClass':'1','IsTrading':1,'ExpireDate':d} for s,d in [('old','20200101'),('a','20261001'),('b','20261201')]}
  self.assertEqual(candidates(c,['au'],today='20260923'),['a','b'])
  stats={'a':{'volume':100,'ticks':1,'changes':0,'last_price':10},'b':{'volume':20,'ticks':4,'changes':3,'last_price':11}}
  self.assertEqual(rank_active(c,stats,['au']),['b'])
 def run_fake(self,fail=False,no_ticks=False,automatic=False):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);pkg=root/'vnpy_ctp';pkg.mkdir();(pkg/'__init__.py').write_text('');(pkg/'api.py').write_text(FAKE)
   config={k:'test' for k in ['userid','password','brokerid','td_address','md_address','appid','auth_code']};config['environment']='simnow'
   (root/'cfg.json').write_text(json.dumps(config))
   env={**os.environ,'PYTHONPATH':t}
   if fail:env['FAIL_LOGIN']='1'
   if no_ticks:env['NO_TICKS']='1'
   cmd=[sys.executable,str(HERE/'demo.py'),'--config',str(root/'cfg.json'),'--symbols','au9999','--discovery-seconds','.2','--output',str(root/'out')]
   if automatic:
    at=cmd.index('--symbols'); del cmd[at:at+2]; cmd+=['--products','au']
   if fail or no_ticks:cmd+=['--duration','1']
   with (root/'stdout').open('w') as out:
    p=subprocess.Popen(cmd,env=env,stdout=out,stderr=subprocess.STDOUT)
    try:
     if not (fail or no_ticks):
      time.sleep(2.0);self.assertIsNone(p.poll(),'default mode should still run')
      p.terminate()
     p.wait(timeout=6)
    finally:
     if p.poll() is None:p.kill();p.wait()
   self.assertEqual(p.returncode,2 if fail or no_ticks else 0,(root/'stdout').read_text())
   result=json.loads((root/'out/summary.json').read_text())
   self.assertEqual(result['orders_sent'],0)
   if automatic:self.assertEqual(result['selected'],['au9999']);self.assertEqual(result['td_logins'],1)
   if fail:self.assertEqual(result['md_logins'],0);self.assertTrue(result['errors'])
   elif no_ticks:self.assertEqual(result['verified_streams'],[]);self.assertEqual(result['ticks'],{})
   else:self.assertGreater(result['ticks']['au9999']['ticks'],2)
   self.assertNotIn('password',(root/'out/events.jsonl').read_text())
 def test_automatic_discovery(self):self.run_fake(automatic=True)
 def test_continuous_and_clean_shutdown(self):self.run_fake()
 def test_login_failure_not_success(self):self.run_fake(True)
 def test_subscribed_without_ticks_not_success(self):self.run_fake(no_ticks=True)
if __name__=='__main__':unittest.main()
