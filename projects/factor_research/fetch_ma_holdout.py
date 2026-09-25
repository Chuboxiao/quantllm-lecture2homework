"""Read BaoStock's adjusted daily bars for a frozen 2023-12-29 CSI300 cohort.

Anonymous market-data login only; never connects to SimNow or submits orders.
Raw data and temporary per-symbol resumable parts are Git-ignored under data/.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
import argparse
import json
import time

import baostock as bs
import polars as pl

from audit_stock_cache import MembershipReader

ROOT = Path(__file__).resolve().parents[2]
CUTOFF = datetime(2023, 12, 29)
DEFAULT_OUT = ROOT / 'data/factor_research/ma_holdout_2024_2025.parquet'
DEFAULT_SUMMARY = ROOT / 'reports/ma_followup_data.json'
FIELDS = 'date,code,open,high,low,close,volume,tradestatus,isST'


def query_symbol(symbol: str, begin: str, end: str) -> list[dict]:
    number, exchange = symbol.split('.')
    if len(number)!=6 or exchange not in {'SSE','SZSE'}:
        raise ValueError(f'invalid symbol {symbol}')
    bs_code=f'{"sh" if exchange=="SSE" else "sz"}.{number}'
    q=bs.query_history_k_data_plus(bs_code,FIELDS,
            start_date=begin,end_date=end,frequency='d',adjustflag='2')
    if q.error_code!='0':raise RuntimeError(f'{symbol}: {q.error_code} {q.error_msg}')
    rows=[]
    while q.next():
        day,_,open_,high,low,close,volume,status,is_st=q.get_row_data()
        if not all((day,open_,high,low,close,volume,status)):
            continue
        rows.append({'day':day,'vt_symbol':symbol,
                     'open':float(open_),'high':float(high),'low':float(low),'close':float(close),
                     'volume':float(volume),'tradestatus':int(status),
                     'isST':int(is_st) if is_st else -1})
    if len(rows)<60:raise RuntimeError(f'{symbol}: only {len(rows)} rows')
    return rows


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('teacher_cache',type=Path)
    parser.add_argument('--begin',default='2023-09-01')
    parser.add_argument('--end',default='2026-01-15')
    parser.add_argument('--out',type=Path,default=DEFAULT_OUT)
    parser.add_argument('--summary',type=Path,default=DEFAULT_SUMMARY)
    parser.add_argument('--parts-dir',type=Path)
    args=parser.parse_args()
    begin=datetime.fromisoformat(args.begin).date()
    end=datetime.fromisoformat(args.end).date()
    if not begin<end:raise ValueError('begin must precede end')
    parts=args.parts_dir or args.out.with_suffix('').with_name(args.out.stem+'_parts')
    with (args.teacher_cache/'filters.pkl').open('rb') as f:membership=MembershipReader(f).load()
    universe=sorted(s for s,periods in membership.items() if any(a<=CUTOFF<=b for a,b in periods))
    if len(universe)!=300:raise ValueError(f'expected 300 frozen members, got {len(universe)}')
    parts.mkdir(parents=True,exist_ok=True)
    pending=[s for s in universe if not (parts/f'{s}.json').exists()]
    print('frozen universe',len(universe),'already fetched',len(universe)-len(pending),'pending',len(pending),flush=True)
    login=bs.login()
    if login.error_code!='0':raise RuntimeError(f'BaoStock login: {login.error_code} {login.error_msg}')
    errors=[]
    try:
        for index,symbol in enumerate(pending,1):
            try:
                rows=query_symbol(symbol,args.begin,args.end)
                (parts/f'{symbol}.json').write_text(json.dumps(rows,separators=(',',':')))
            except Exception as exc:
                errors.append(f'{symbol}: {type(exc).__name__}: {str(exc)[:120]}')
            if index%30==0 or index==len(pending):
                print('processed',index,'of',len(pending),'errors',len(errors),flush=True)
            time.sleep(0.1)
    finally:
        bs.logout()
    if errors:
        print('failed',errors[:12],flush=True)
        raise RuntimeError(f'{len(errors)} symbols failed; successful parts retained for retry')
    rows=[r for s in universe for r in json.loads((parts/f'{s}.json').read_text())]
    df=pl.DataFrame(rows).with_columns(pl.col('day').str.to_date()).sort(['vt_symbol','day'])
    if df.unique(['vt_symbol','day']).height!=df.height or df['vt_symbol'].n_unique()!=300:
        raise ValueError('duplicate symbol-day or incomplete universe')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    df.write_parquet(args.out)
    fresh=df.filter(pl.col('day').is_between(datetime(2024,1,1).date(),datetime(2025,12,31).date()))
    forward=df.filter(pl.col('day').dt.year()==2026)
    summary={'provider':'BaoStock','api':'query_history_k_data_plus',
             'provider_url':'https://github.com/zxygithub/baostock',
             'retrieved_at':datetime.now().isoformat(timespec='seconds'),
             'adjustflag':'2 (forward adjusted, as retrieved in 2026)',
             'begin':args.begin,'end':args.end,
             'universe':'CSI300 members on 2023-12-29, frozen, from teacher membership cache',
             'symbols':df['vt_symbol'].n_unique(),'rows':df.height,
             'first':str(df['day'].min()),'last':str(df['day'].max()),
             'fresh_symbols':fresh['vt_symbol'].n_unique(),'fresh_rows':fresh.height,
             'zero_volume_fresh_rows':fresh.filter(pl.col('volume')==0).height,
             'nontrading_fresh_rows':fresh.filter(pl.col('tradestatus')!=1).height,
             'st_fresh_rows':fresh.filter(pl.col('isST')==1).height,
             'forward_2026_rows':forward.height,
             'forward_2026_dates':forward['day'].n_unique(),
             'parquet_sha256':sha256(args.out.read_bytes()).hexdigest(),
             'source_membership_sha256':sha256((args.teacher_cache/'filters.pkl').read_bytes()).hexdigest()}
    args.summary.parent.mkdir(parents=True,exist_ok=True)
    args.summary.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
