"""Fail-closed rules for a one-lot SHFE gold/silver teaching experiment."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import math
from logic import valid_price

TZ=ZoneInfo('Asia/Shanghai')
TERMINAL={'0','2','4','5'}

def seconds_to_break(now):
 now=now.astimezone(TZ); seconds=now.hour*3600+now.minute*60+now.second+now.microsecond/1e6
 # Holiday/temporary closure is additionally gated by current CTP instrument status.
 windows=[(9*3600,10*3600+900),(10*3600+1800,11*3600+1800),(13*3600+1800,15*3600)] if now.weekday()<5 else []
 if now.weekday()<5:windows.append((21*3600,24*3600+9000))
 if (now-timedelta(days=1)).weekday()<5:windows.append((0,9000))
 return next((end-seconds for start,end in windows if start<=seconds<end),0)

def on_grid(price,tick):return abs(price/tick-round(price/tick))<1e-6

def check_quote(q,now,mono,day,step,opening=True):
 """Returns reason and exchange timestamp. Both wall clock and receive age matter."""
 try:
  if valid_price(step) is None:return 'invalid_tick_size',None
  age=mono-q['received_mono']
  if not 0<=age<=2:return 'receive_stale',None
  if q['TradingDay']!=day:return 'wrong_trading_day',None
  ts=datetime.strptime(q['ActionDay']+q['UpdateTime'],'%Y%m%d%H:%M:%S').replace(tzinfo=TZ)+timedelta(milliseconds=int(q['UpdateMillisec']))
  if not -.5<=(now-ts).total_seconds()<=2:return 'exchange_stale_or_future',None
  needed=['LastPrice','BidPrice1','LowerLimitPrice','UpperLimitPrice']+(['AskPrice1'] if opening else [])
  if any(valid_price(q.get(k)) is None for k in needed):return 'invalid_price',None
  lower,upper=q['LowerLimitPrice'],q['UpperLimitPrice']
  if lower>=upper:return 'invalid_limits',None
  if int(q.get('BidVolume1',0))<1 or (opening and int(q.get('AskVolume1',0))<1):return 'empty_book',None
  if any(not lower<=q[k]<=upper or not on_grid(q[k],step) for k in needed[:2]+(['AskPrice1'] if opening else [])):return 'price_outside_limits_or_tick',None
  if opening:
   if q['BidPrice1']>q['AskPrice1']:return 'crossed_book',None
   if q['AskPrice1']-q['BidPrice1']>5*step+1e-8:return 'spread_too_wide',None
   if min(q['LastPrice']-lower,upper-q['LastPrice'],q['BidPrice1']-lower,upper-q['AskPrice1'])<2*step-1e-8:return 'near_price_limit',None
  return '',ts
 except (KeyError,ValueError,TypeError,OverflowError):return 'incomplete_quote',None

def costs(instrument,margin,commission,q):
 mult=instrument['VolumeMultiple'];price=q['UpperLimitPrice']
 def rate(key,source):
  value=float(source[key])
  if not math.isfinite(value) or value<0:raise ValueError('Invalid rate: '+key)
  return value
 required=price*mult*rate('LongMarginRatioByMoney',margin)+rate('LongMarginRatioByVolume',margin)
 fees=price*mult*(rate('OpenRatioByMoney',commission)+rate('CloseTodayRatioByMoney',commission))+rate('OpenRatioByVolume',commission)+rate('CloseTodayRatioByVolume',commission)
 if not required>0:raise ValueError('Missing positive margin requirement')
 return required,fees

def entry_checks(instrument,margin,commission,account,positions,orders,q,max_loss):
 try:
  if instrument['ExchangeID']!='SHFE' or instrument['ProductID'] not in ('au','ag') or instrument['ProductClass']!='1' or not instrument['IsTrading']:return 'unsupported_contract',{}
  if not valid_price(instrument['PriceTick']) or not valid_price(instrument['VolumeMultiple']):return 'invalid_contract',{}
  if any(int(p.get('Position',0)) or int(p.get('LongFrozen',0)) or int(p.get('ShortFrozen',0)) for p in positions):return 'existing_position_or_frozen',{}
  if any(o.get('OrderStatus') not in TERMINAL for o in orders):return 'existing_working_order',{}
  if account.get('CurrencyID')!='CNY':return 'wrong_currency',{}
  balance,available=float(account['Balance']),float(account['Available'])
  if not all(math.isfinite(v) and v>0 for v in (balance,available,max_loss)):return 'invalid_funds',{}
  required,fees=costs(instrument,margin,commission,q)
  details=dict(estimated_margin=required,fee_reserve=fees,required_available=1.2*required+2*fees+max_loss)
  if required>.1*balance:return 'margin_exceeds_10_percent_equity',details
  if available<details['required_available']:return 'insufficient_available',details
  if max_loss<fees+2*instrument['PriceTick']*instrument['VolumeMultiple']:return 'loss_budget_below_cost_buffer',details
  return '',details
 except (KeyError,ValueError,TypeError,OverflowError):return 'incomplete_risk_data',{}

class Crossing:
 def __init__(self):self.previous=None;self.timestamp=None
 def reset(self):self.previous=None;self.timestamp=None
 def update(self,price,timestamp,threshold):
  if self.timestamp is not None and timestamp<=self.timestamp:return False
  fire=self.previous is not None and self.previous<=threshold<price
  self.previous=price;self.timestamp=timestamp
  return fire
