"""CTP callbacks for one-contract inspection/execution; callbacks only enqueue data."""
from datetime import datetime
from queue import Queue
from pathlib import Path
import time

FIELDS = {
 'instrument': 'InstrumentID ExchangeID ProductID ProductClass PriceTick VolumeMultiple IsTrading ExpireDate',
 'margin': 'InstrumentID ExchangeID HedgeFlag LongMarginRatioByMoney LongMarginRatioByVolume',
 'commission': 'InstrumentID ExchangeID OpenRatioByMoney OpenRatioByVolume CloseRatioByMoney CloseRatioByVolume CloseTodayRatioByMoney CloseTodayRatioByVolume',
 'account': 'CurrencyID Balance Available CurrMargin FrozenMargin FrozenCash FrozenCommission Commission CloseProfit PositionProfit',
 'position': 'InstrumentID ExchangeID PosiDirection PositionDate Position TodayPosition YdPosition LongFrozen ShortFrozen',
 'order': 'InstrumentID ExchangeID OrderRef OrderSysID FrontID SessionID Direction CombOffsetFlag OrderStatus OrderSubmitStatus LimitPrice VolumeTotalOriginal VolumeTraded VolumeTotal InsertDate InsertTime CancelTime StatusMsg',
 'trade': 'InstrumentID ExchangeID OrderRef OrderSysID TradeID TradingDay TradeDate TradeTime Direction OffsetFlag Price Volume',
 'tick': 'InstrumentID ExchangeID TradingDay ActionDay UpdateTime UpdateMillisec LastPrice BidPrice1 AskPrice1 BidVolume1 AskVolume1 UpperLimitPrice LowerLimitPrice Volume',
 'status': 'InstrumentID ExchangeInstID ExchangeID InstrumentStatus EnterTime',
 'login': 'TradingDay FrontID SessionID MaxOrderRef',
}
FIELDS['insert_error']=FIELDS['order']
FIELDS['cancel_error']='InstrumentID ExchangeID OrderRef OrderSysID FrontID SessionID ActionFlag'
QUERIES = {
 'instrument':'reqQryInstrument', 'margin':'reqQryInstrumentMarginRate',
 'commission':'reqQryInstrumentCommissionRate', 'account':'reqQryTradingAccount',
 'position':'reqQryInvestorPosition', 'order':'reqQryOrder', 'trade':'reqQryTrade',
}

class Transport:
 def __init__(self, config, flow):
  from vnpy_ctp.api import MdApi,TdApi
  self.config=config; self.queue=Queue();self.seq=0;self.started=[]
  owner=self
  def emit(kind,data=None,error=None,reqid=0,last=True):
   data=data or {}; error=error or {}
   base=kind.removeprefix('qry_').removeprefix('rtn_')
   msg=str(error.get('ErrorMsg',''))
   for field in ('userid','password','auth_code'):
    msg=msg.replace(config[field],'[redacted]')
   clean={k:data[k] for k in FIELDS.get(base,'').split() if k in data}
   if 'StatusMsg' in clean:
    for field in ('userid','password','auth_code'):clean['StatusMsg']=clean['StatusMsg'].replace(config[field],'[redacted]')
   owner.queue.put(dict(kind=kind,data=clean,error_id=int(error.get('ErrorID',0)),error_message=msg,request_id=reqid,last=last,received_at=datetime.now().astimezone().isoformat(),received_mono=time.monotonic()))
  class Market(MdApi):
   def onFrontConnected(self):emit('md_connected')
   def onFrontDisconnected(self,reason):emit('md_disconnected',error={'ErrorID':reason})
   def onRspUserLogin(self,d,e,r,l):emit('md_login',d,e,r,l)
   def onRspSubMarketData(self,d,e,r,l):emit('subscription',d,e,r,l)
   def onRtnDepthMarketData(self,d):emit('tick',d)
   def onRspError(self,e,r,l):emit('error',error=e,reqid=r,last=l)
  class Trading(TdApi):
   def onFrontConnected(self):emit('td_connected')
   def onFrontDisconnected(self,reason):emit('td_disconnected',error={'ErrorID':reason})
   def onRspAuthenticate(self,d,e,r,l):emit('auth',d,e,r,l)
   def onRspUserLogin(self,d,e,r,l):emit('login',d,e,r,l)
   def onRspSettlementInfoConfirm(self,d,e,r,l):emit('settlement',d,e,r,l)
   def onRspQryInstrument(self,d,e,r,l):emit('qry_instrument',d,e,r,l)
   def onRspQryInstrumentMarginRate(self,d,e,r,l):emit('qry_margin',d,e,r,l)
   def onRspQryInstrumentCommissionRate(self,d,e,r,l):emit('qry_commission',d,e,r,l)
   def onRspQryTradingAccount(self,d,e,r,l):emit('qry_account',d,e,r,l)
   def onRspQryInvestorPosition(self,d,e,r,l):emit('qry_position',d,e,r,l)
   def onRspQryOrder(self,d,e,r,l):emit('qry_order',d,e,r,l)
   def onRspQryTrade(self,d,e,r,l):emit('qry_trade',d,e,r,l)
   def onRtnInstrumentStatus(self,d):emit('status',d)
   def onRtnOrder(self,d):emit('rtn_order',d)
   def onRtnTrade(self,d):emit('rtn_trade',d)
   def onRspOrderInsert(self,d,e,r,l):emit('insert_error',d,e,r,l)
   def onErrRtnOrderInsert(self,d,e):emit('insert_error',d,e)
   def onRspOrderAction(self,d,e,r,l):emit('cancel_error',d,e,r,l)
   def onErrRtnOrderAction(self,d,e):emit('cancel_error',d,e)
   def onRspError(self,e,r,l):emit('error',error=e,reqid=r,last=l)
  self.md=Market();self.td=Trading()
  self.md.createFtdcMdApi(str(Path(flow)/'md_'))
  self.td.createFtdcTraderApi(str(Path(flow)/'td_'))
  self.md.registerFront(config['md_address']);self.td.registerFront(config['td_address'])
  self.td.subscribePrivateTopic(2);self.td.subscribePublicTopic(0)
 def start(self):
  self.md.init();self.started.append(self.md)
  self.td.init();self.started.append(self.td)
 def close(self):
  for api in reversed(self.started):api.exit()
 def request(self, method, fields=None, market=False):
  self.seq+=1
  rc=getattr(self.md if market else self.td,method)(fields or {},self.seq)
  return self.seq,rc
 def login(self,market=False):
  c=self.config
  return self.request('reqUserLogin',{k:c[v] for k,v in [('BrokerID','brokerid'),('UserID','userid'),('Password','password')]},market)
 def authenticate(self):
  c=self.config
  return self.request('reqAuthenticate',dict(BrokerID=c['brokerid'],UserID=c['userid'],AppID=c['appid'],AuthCode=c['auth_code']))
 def settle(self):return self.request('reqSettlementInfoConfirm',self.identity())
 def identity(self):return dict(BrokerID=self.config['brokerid'],InvestorID=self.config['userid'])
 def query(self,kind,symbol):
  fields=self.identity()
  if kind=='account':fields['CurrencyID']='CNY'
  else:fields['InstrumentID']=symbol
  if kind=='margin':fields['HedgeFlag']='1'
  return self.request(QUERIES[kind],fields)
