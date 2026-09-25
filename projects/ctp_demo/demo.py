"""Read-only SimNow demo using vnpy_ctp.api.MdApi/TdApi; runs until Ctrl+C."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from queue import Queue, Empty
import signal
import sys
import threading
import time

from logic import candidates, rank_active, valid_price

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'configs/local/simnow.json')
    parser.add_argument('--duration', type=float, default=0, help='0 = continuous (default); >0 = validation run seconds')
    parser.add_argument('--products', default='au,ag,cu,rb')
    parser.add_argument('--symbols', default='', help='explicit comma-separated symbols, bypass automatic ranking')
    parser.add_argument('--discovery-seconds', type=float, default=20)
    parser.add_argument('--output', type=Path, help='new output directory; default reports/local/ctp_<timestamp>')
    args = parser.parse_args()
    if args.duration < 0 or args.discovery_seconds <= 0:
        parser.error('duration must be >=0; discovery-seconds must be >0')
    try:
        cfg = json.loads(args.config.read_text())
    except (OSError, ValueError):
        parser.error('Cannot read config JSON. Copy configs/simnow.example.json to configs/local/simnow.json and fill locally.')
    for key in ('userid','password','brokerid','td_address','md_address','appid','auth_code'):
        if not isinstance(cfg.get(key), str) or not cfg[key]:
            parser.error('Missing/non-string config field: '+key)
    # Explicit environment label; the operator must supply SimNow endpoints.
    if cfg.get('environment') != 'simnow':
        parser.error('Set environment=simnow in the local config.')
    products = [s.strip() for s in args.products.split(',') if s.strip()]
    explicit = [s.strip() for s in args.symbols.split(',') if s.strip()]
    output = (args.output or ROOT/'reports/local'/('ctp_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))).resolve()
    output.mkdir(parents=True, exist_ok=False)
    flow = output/'flow'
    flow.mkdir()
    # vnpy imports may select a trader directory: keep side effects inside the project.
    import os
    os.chdir(ROOT)
    (ROOT/'.vntrader').mkdir(exist_ok=True)
    from vnpy_ctp.api import MdApi, TdApi

    messages = Queue()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    def emit(kind, **fields):
        messages.put({'received_at':datetime.now().astimezone().isoformat(), 'kind':kind, **fields})
    def err(error):
        return int((error or {}).get('ErrorID', 0))
    def error_message(error):
        message=str((error or {}).get('ErrorMsg', ''))
        for key in ('userid','password','auth_code'):
            if cfg.get(key): message=message.replace(cfg[key], '[redacted]')
        return message
    def login_fields():
        return {'UserID':cfg['userid'],'Password':cfg['password'],'BrokerID':cfg['brokerid']}

    class Market(MdApi):
        def onFrontConnected(self): emit('md_connected')
        def onFrontDisconnected(self, reason): emit('md_disconnected', reason=reason)
        def onRspUserLogin(self, data, error, reqid, last): emit('md_login', error_id=err(error))
        def onRspSubMarketData(self, data, error, reqid, last):
            emit('subscription',symbol=data.get('InstrumentID',''),error_id=err(error))
        def onRspUnSubMarketData(self, data, error, reqid, last):
            emit('unsubscription',symbol=data.get('InstrumentID',''),error_id=err(error))
        def onRspError(self, error, reqid, last): emit('md_error',error_id=err(error),request_id=reqid)
        def onRtnDepthMarketData(self, data):
            emit('tick',symbol=data.get('InstrumentID',''),trading_day=data.get('TradingDay',''),
                 action_day=data.get('ActionDay',''),market_time=data.get('UpdateTime',''),
                 millisec=data.get('UpdateMillisec',0),last_price=valid_price(data.get('LastPrice')),
                 bid=valid_price(data.get('BidPrice1')),ask=valid_price(data.get('AskPrice1')),
                 volume=data.get('Volume',0),open_interest=data.get('OpenInterest',0))

    class Trading(TdApi):
        def onFrontConnected(self): emit('td_connected')
        def onFrontDisconnected(self, reason): emit('td_disconnected',reason=reason)
        def onRspAuthenticate(self, data, error, reqid, last): emit('td_auth',error_id=err(error))
        def onRspUserLogin(self, data, error, reqid, last): emit('td_login',error_id=err(error),error_message=error_message(error))
        def onRspSettlementInfoConfirm(self, data, error, reqid, last): emit('td_settlement',error_id=err(error))
        def onRspQryInstrument(self, data, error, reqid, last):
            keys=('InstrumentID','ProductID','ProductClass','ExpireDate','IsTrading','ExchangeID','PriceTick','VolumeMultiple')
            emit('contract',data={k:data[k] for k in keys if k in data},error_id=err(error),last=last)
        def onRspError(self, error, reqid, last): emit('td_error',error_id=err(error),request_id=reqid)
        # This quote-only demo ignores order details and never submits orders.
        def onRtnOrder(self, data): emit('external_order_notice')
        def onRtnTrade(self, data): emit('external_trade_notice')

    md, td = Market(), Trading()
    reqid=0
    def request(api, method, data):
        nonlocal reqid
        reqid += 1
        rc=getattr(api,method)(data,reqid)
        emit('request',method=method,return_code=rc,request_id=reqid)
        return rc

    summary={'started_at':datetime.now().astimezone().isoformat(),'orders_sent':0,
             'mode':'read_only','md_logins':0,'td_logins':0,'td_auths':0,
             'subscriptions':[],'selected':[],'ticks':{},'errors':[], 'products':products}
    counts=Counter()
    contracts={}
    stats={}
    desired=set(explicit)
    md_ready=False
    td_ready=False
    query_due=None
    query_attempts=0
    pending_products=[]
    query_product=None
    discovery_start=None
    selected=None
    started=[]
    started_clock=time.monotonic()
    next_heartbeat=started_clock+15
    events=(output/'events.jsonl').open('w')
    try:
        md.createFtdcMdApi(str(flow/'md_'))
        td.createFtdcTraderApi(str(flow/'td_'))
        md.registerFront(cfg['md_address'])
        td.registerFront(cfg['td_address'])
        td.subscribePrivateTopic(2)
        td.subscribePublicTopic(2)
        md.init(); started.append(md)
        td.init(); started.append(td)
        print('正在连接 SimNow；默认持续运行，按 Ctrl+C 停止。输出目录：'+str(output),flush=True)
        while not stop.is_set():
            now=time.monotonic()
            if args.duration and now-started_clock>=args.duration: break
            if query_due and now>=query_due and td_ready:
                query_attempts+=1
                rc=request(td,'reqQryInstrument',{'ProductID':query_product})
                query_due = now+2 if rc and query_attempts<5 else None
                if rc and query_attempts>=5: emit('query_exhausted')
            if md_ready and discovery_start and selected is None and now-discovery_start>=args.discovery_seconds:
                selected=explicit or rank_active(contracts,stats,products)
                summary['selected']=selected
                emit('selection',symbols=selected,criterion='one updating contract per product, highest cumulative volume among sampled nearest six expiries',candidates=sorted(desired))
                if selected:
                    for symbol in desired-set(selected):
                        md.unSubscribeMarketData(symbol)
                    desired=set(selected)
                else:
                    # Keep observing candidates and retry, instead of silently showing nothing.
                    selected=None
                    discovery_start=now
            if now>=next_heartbeat:
                emit('heartbeat',md_ready=md_ready,td_ready=td_ready,total_ticks=counts['tick'])
                next_heartbeat=now+15
            try: e=messages.get(timeout=0.2)
            except Empty: continue
            kind=e['kind']; counts[kind]+=1
            if e.get('error_id'):
                summary['errors'].append(e)
            if kind=='md_connected':
                request(md,'reqUserLogin',login_fields())
            elif kind=='md_disconnected': md_ready=False
            elif kind=='td_disconnected': td_ready=False; query_due=None
            elif kind=='td_connected':
                request(td,'reqAuthenticate',{'UserID':cfg['userid'],'BrokerID':cfg['brokerid'],'AppID':cfg['appid'],'AuthCode':cfg['auth_code']})
            elif kind=='td_auth' and not e['error_id']:
                summary['td_auths']+=1
                request(td,'reqUserLogin',login_fields())
            elif kind=='td_login' and not e['error_id']:
                summary['td_logins']+=1; td_ready=True
                request(td,'reqSettlementInfoConfirm',{'BrokerID':cfg['brokerid'],'InvestorID':cfg['userid']})
            elif kind=='td_settlement' and not e['error_id']:
                if not explicit:
                    contracts.clear(); pending_products=list(products)
                    query_product=pending_products.pop(0) if pending_products else None
                    query_due=now+1 if query_product else None; query_attempts=0
            elif kind=='md_login' and not e['error_id']:
                summary['md_logins']+=1; md_ready=True
                for symbol in sorted(desired): md.subscribeMarketData(symbol)
                if desired and not discovery_start: discovery_start=now
            elif kind=='subscription' and not e['error_id']:
                if e['symbol'] not in summary['subscriptions']: summary['subscriptions'].append(e['symbol'])
            elif kind=='contract':
                d=e['data']
                if d.get('InstrumentID'): contracts[d['InstrumentID']]=d
                if e['last'] and not e['error_id']:
                    emit('contract_query_done',product=query_product,total=len(contracts))
                    if pending_products:
                        query_product=pending_products.pop(0); query_due=now+1; query_attempts=0
                    elif not desired:
                        desired=set(candidates(contracts,products))
                        for symbol in sorted(desired):
                            if md_ready: md.subscribeMarketData(symbol)
                        if md_ready and desired: discovery_start=now
                    if desired: emit('contracts_ready',total=len(contracts),candidates=sorted(desired))
            elif kind=='tick':
                symbol=e['symbol']; price=e['last_price']
                sig=(e['action_day'],e['market_time'],e['millisec'],e['volume'],price,e['bid'],e['ask'])
                if symbol not in stats:
                    stats[symbol]={'ticks':0,'changes':0,'volume':0,'last_price':None,'first_received':e['received_at']}
                s=stats[symbol]
                if s.get('_signature') is not None and tuple(s['_signature'])!=sig: s['changes']+=1
                s.update(ticks=s['ticks']+1,volume=e['volume'],last_price=price,last_received=e['received_at'],market_time=e['market_time'],_signature=sig)
            if kind!='contract':
                events.write(json.dumps(e,ensure_ascii=False,allow_nan=False)+'\n');events.flush()
                if kind=='tick':
                    if selected is None or e['symbol'] in selected:
                        print(f"{e['market_time']}.{e['millisec']:03d} {e['symbol']:10} 最新={e['last_price']} 买一={e['bid']} 卖一={e['ask']} 累计量={e['volume']}",flush=True)
                else: print(json.dumps(e,ensure_ascii=False),flush=True)
    finally:
        for api in reversed(started): api.exit()
        summary.update(ended_at=datetime.now().astimezone().isoformat(),elapsed_seconds=round(time.monotonic()-started_clock,2),event_counts=dict(counts),
                       ticks={k:{a:b for a,b in v.items() if not a.startswith('_')} for k,v in stats.items()})
        summary['verified_streams']=[s for s in summary['selected'] if stats.get(s, {}).get('changes', 0)>0]
        events.close()
        (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
        print('已停止。报告：'+str(output/'summary.json'),flush=True)
    return 0 if summary['md_logins'] and summary['verified_streams'] else 2


if __name__=='__main__':
    sys.exit(main())
