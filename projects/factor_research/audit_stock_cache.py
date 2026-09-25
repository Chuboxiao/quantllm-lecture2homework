"""Inspect course data without importing/executing the teacher's project.

Usage: .venv/bin/python projects/factor_research/audit_stock_cache.py CACHE_DIRECTORY
Dependency: polars. Base pickle is parsed as opcodes; only its Arrow payload is read.
The small membership pickle permits only defaultdict/list/datetime constructors.
"""
import argparse
from collections import defaultdict, Counter
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import io
import json
import pickle
import pickletools
import polars as pl

ROOT = Path(__file__).resolve().parents[2]

class MembershipReader(pickle.Unpickler):
    def find_class(self, module, name):
        allowed = {('collections', 'defaultdict'): defaultdict,
                   ('builtins', 'list'): list, ('datetime', 'datetime'): datetime}
        if (module, name) not in allowed:
            raise pickle.UnpicklingError(f'Unexpected object: {module}.{name}')
        return allowed[module, name]

def read_cache(folder):
    raw = (folder / 'base_dataset.pkl').read_bytes()
    payloads = [arg for op, arg, _ in pickletools.genops(raw) if op.name == 'BINBYTES']
    if len(payloads) != 1:
        raise ValueError('Expected exactly one Arrow payload; inspect format before proceeding')
    df = pl.read_ipc_stream(io.BytesIO(payloads[0]))
    with (folder / 'filters.pkl').open('rb') as f:
        members = MembershipReader(f).load()
    for symbol, intervals in members.items():
        assert isinstance(symbol, str)
        assert all(isinstance(a, datetime) and isinstance(b, datetime) and a <= b for a,b in intervals)
    return df, members

def audit(folder):
    df, members = read_cache(folder)
    prices = ['open', 'high', 'low', 'close']
    numeric = [c for c,t in df.schema.items() if t.is_numeric()]
    df = df.with_columns(pl.col('datetime').dt.date().alias('_date'))
    symbols = set(df['vt_symbol'].unique().to_list())
    intervals = [(s,a.date(),b.date()) for s,v in members.items() for a,b in v]
    ranges = pl.DataFrame(intervals, schema=['vt_symbol','_start','_end'], orient='row')
    active = df.join(ranges, on='vt_symbol').filter(pl.col('_date').is_between(pl.col('_start'),pl.col('_end'))).drop('_start','_end')
    dates = sorted(df['_date'].unique().to_list())
    first = min(a for _,a,b in intervals); last = max(b for _,a,b in intervals)
    dates = [d for d in dates if first <= d <= last]
    expected = {d:sum(a<=d<=b for _,a,b in intervals) for d in dates}
    actual = dict(active.group_by('_date').agg(pl.col('vt_symbol').n_unique()).iter_rows())
    daily = [{'date':str(d), 'members':expected[d], 'with_bars':actual.get(d,0), 'missing_bars':expected[d]-actual.get(d,0)} for d in dates]
    ordered = df.sort(['vt_symbol','datetime']).with_columns((pl.col('close')/pl.col('close').shift(1).over('vt_symbol')-1).alias('_return'))
    jumps = ordered.filter(pl.col('_return').abs()>0.25)
    invalid_ohlc = (pl.col('high') < pl.max_horizontal('open','low','close')) | (pl.col('low') > pl.min_horizontal('open','high','close'))
    checks = {
        'first_close_equals_one_symbols':df.sort(['vt_symbol','datetime']).group_by('vt_symbol').agg(pl.col('close').first()).filter((pl.col('close')-1).abs()<1e-12).height,
        'duplicate_symbol_datetime_rows':df.height-df.unique(['vt_symbol','datetime']).height,
        'duplicate_symbol_date_rows':df.height-df.unique(['vt_symbol','_date']).height,
        'nulls':df.null_count().row(0,named=True),
        'nonfinite':{c:df.select((~pl.col(c).is_finite()).sum()).item() for c in numeric},
        'nonpositive_prices':{c:df.select((pl.col(c)<=0).sum()).item() for c in prices},
        'ohlc_inconsistent_rows':df.filter(invalid_ohlc).height,
        'zero_volume_rows':df.filter(pl.col('volume')==0).height,
        'zero_volume_active_rows':active.filter(pl.col('volume')==0).height,
        'negative_volume_rows':df.filter(pl.col('volume')<0).height,
        'negative_turnover_rows':df.filter(pl.col('turnover')<0).height,
        'weekend_rows':df.filter(pl.col('_date').dt.weekday()>5).height,
    }
    if 'vwap' in df.columns:
        valid_vwap=df.filter((pl.col('volume')>0)&pl.col('vwap').is_finite())
        checks['vwap_outside_low_high_rows']=valid_vwap.filter((pl.col('vwap')<pl.col('low')-0.011)|(pl.col('vwap')>pl.col('high')+0.011)).height
        checks['vwap_outside_check_denominator']=valid_vwap.height
    coverage = df.group_by('vt_symbol').agg(pl.len().alias('rows'),pl.col('_date').min().alias('start'),pl.col('_date').max().alias('end')).sort('rows')
    missing = []
    for item in daily:
        if item['missing_bars']:
            day = datetime.fromisoformat(item['date']).date()
            expected_symbols = {s for s,a,b in intervals if a<=day<=b}
            actual_symbols = set(df.filter(pl.col('_date')==day)['vt_symbol'].to_list())
            missing.extend({'date':str(day),'vt_symbol':s} for s in sorted(expected_symbols-actual_symbols))
    result = {
        'audited_at':datetime.now().isoformat(timespec='seconds'), 'polars_version':pl.__version__,
        'source_directory':'/'.join(folder.parts[-5:]),
        'files':{f.name:{'bytes':f.stat().st_size,'sha256':sha256(f.read_bytes()).hexdigest()} for f in [folder/'base_dataset.pkl',folder/'filters.pkl']},
        'shape':[df.height,df.width-1], 'schema':{c:str(t) for c,t in df.schema.items() if c!='_date'},
        'start':str(df['_date'].min()),'end':str(df['_date'].max()),'symbols':len(symbols),
        'membership':{'symbols':len(members),'intervals':len(intervals),'start':str(first),'end':str(last),
            'members_without_bars':sorted(set(members)-symbols),'bars_without_membership':sorted(symbols-set(members)),
            'active_rows':active.height,'active_duplicate_symbol_date_rows':active.height-active.unique(['vt_symbol','_date']).height,
            'member_count_distribution':dict(Counter(d['members'] for d in daily)),
            'dates_not_300_members':[d for d in daily if d['members']!=300],
            'missing_bars':missing,
            'dates_with_missing_bars':sum(d['missing_bars']>0 for d in daily),
            'missing_member_day_bars':sum(d['missing_bars'] for d in daily),
            'largest_missing_dates':sorted(daily,key=lambda d:d['missing_bars'],reverse=True)[:10]},
        'checks':checks,
        'yearly_bars':df.group_by(pl.col('_date').dt.year().alias('year')).agg(pl.len().alias('rows'),pl.col('vt_symbol').n_unique().alias('symbols')).sort('year').to_dicts(),
        'shortest_series':coverage.head(10).to_dicts(),
        'largest_close_changes':jumps.sort(pl.col('_return').abs(),descending=True).select('datetime','vt_symbol','open','high','low','close','volume','_return').head(12).to_dicts(),
        'absolute_close_change_above_25pct_count':jumps.height,
        'limits':['Prices adjustment, data vendor/version and membership accuracy not independently verified.',
                  'Bundled AlphaLab.load_bar_df divides OHLC by each stock first close; VWAP is not divided. Different units, not an OHLC error.',
                  'Missing bars may reflect suspensions or source gaps; no exchange calendar/suspension table supplied.',
                  'Data-only inspection; no factor selection or test-period performance examined.']
    }
    out=ROOT/'reports/stock-data-audit.json'
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cache_directory',type=Path)
    audit(p.parse_args().cache_directory)
