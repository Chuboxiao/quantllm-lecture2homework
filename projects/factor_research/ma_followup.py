"""Second moving-average clue study: condition the MA relationship on its state.

Explore only 2008-2020 teacher data. The previously revealed 2021-2023 period is
never used in this study's screening. One selected candidate is evaluated on
2024-2025 BaoStock data for a frozen 2023-12-29 CSI300 cohort.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import polars as pl

from audit_stock_cache import MembershipReader, read_cache

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_OUT=ROOT/'reports/ma_followup'
TRAIN=(date(2008,1,2),date(2016,12,31))
VALID=(date(2017,1,1),date(2020,12,31))
FRESH=(date(2024,1,1),date(2025,12,31))
STEP=6
COST=0.003  # Sensitivity only, not an observed implementation cost.

ROUND_NAMES={
 1:['ma_gap_control','fresh_cross5_5','fresh_cross5_10','fresh_cross10_5','fresh_cross10_10',
    'persistent5_5','persistent5_10','persistent10_5','persistent10_10',
    'aligned_short_long','aligned_medium_long','both_slopes_up'],
 2:['gap_delta3','gap_delta5','gap_delta10','medium_gap_delta5','medium_gap_delta10',
    'gap_plus_delta5','gap_minus_delta5','slope_spread_short','slope_spread_medium',
    'gap_acceleration','widening_positive_gap','narrowing_positive_gap'],
 3:['long_ma_control','pullback_below_ma5','pullback_below_ma10','pullback_depth_ma5',
    'pullback_depth_ma10','pullback_depth_ma20','long_plus_pullback5',
    'long_plus_pullback10','long_plus_pullback20','recovering_above_ma20',
    'short_below_medium_long_up','short_above_medium_pullback'],
 4:['trend_broad_market','trend_weak_market','revert_broad_market','revert_weak_market',
    'widening_broad_market','widening_weak_market','vol_scaled_trend',
    'vol_scaled_revert','vol_scaled_widening','vol_scaled_narrowing',
    'trend_above_noise','revert_above_noise']}
CLUES={1:'MA cross recency, persistence, and slope alignment',
       2:'whether the MA gap is widening, slowing, or accelerating',
       3:'short pullbacks inside a rising long-term MA',
       4:'MA direction conditioned on market breadth or stock volatility'}

def base_features(df:pl.DataFrame)->pl.DataFrame:
    if 'day' not in df.columns:
        df=df.with_columns(pl.col('datetime').dt.date().alias('day'))
    if 'tradestatus' not in df.columns:
        df=df.with_columns(pl.lit(1).alias('tradestatus'),pl.lit(0).alias('isST'))
    df=df.sort(['vt_symbol','day'])
    df=df.with_columns([
        pl.col('close').rolling_mean(n).over('vt_symbol').alias(f'ma{n}') for n in (5,10,20,40,60)
    ]+[pl.col('close').shift(1).over('vt_symbol').alias('previous_close')])
    df=df.with_columns([
        (pl.col('ma5')/pl.col('ma20')-1).alias('gap'),
        (pl.col('ma10')/pl.col('ma40')-1).alias('medium_gap'),
        (pl.col('ma20')/pl.col('ma60')-1).alias('long_gap'),
        (pl.col('close')/pl.col('previous_close')-1).alias('daily_return'),
        (pl.col('close')/pl.col('ma5')-1).alias('close_ma5'),
        (pl.col('close')/pl.col('ma10')-1).alias('close_ma10'),
        (pl.col('close')/pl.col('ma20')-1).alias('close_ma20')])
    df=df.with_columns([
        pl.col('gap').shift(n).over('vt_symbol').alias(f'gap_lag{n}') for n in (1,3,5,10)
    ]+[pl.col('medium_gap').shift(n).over('vt_symbol').alias(f'medium_lag{n}') for n in (1,5,10)]
    +[pl.col('ma5').shift(n).over('vt_symbol').alias(f'ma5_lag{n}') for n in (3,5)]
    +[pl.col('ma20').shift(n).over('vt_symbol').alias(f'ma20_lag{n}') for n in (5,10)]
    +[pl.col('ma10').shift(5).over('vt_symbol').alias('ma10_lag5'),
      pl.col('ma40').shift(10).over('vt_symbol').alias('ma40_lag10')])
    df=df.with_columns([
        ((pl.col('gap')>0)&(pl.col('gap_lag1')<=0)).cast(pl.Int8).alias('cross_short'),
        ((pl.col('medium_gap')>0)&(pl.col('medium_lag1')<=0)).cast(pl.Int8).alias('cross_medium'),
        (pl.col('gap')>0).cast(pl.Int8).alias('positive_short'),
        (pl.col('medium_gap')>0).cast(pl.Int8).alias('positive_medium'),
        (pl.col('gap')-pl.col('gap_lag3')).alias('delta3'),
        (pl.col('gap')-pl.col('gap_lag5')).alias('delta5'),
        (pl.col('gap')-pl.col('gap_lag10')).alias('delta10'),
        (pl.col('medium_gap')-pl.col('medium_lag5')).alias('medium_delta5'),
        (pl.col('medium_gap')-pl.col('medium_lag10')).alias('medium_delta10'),
        (pl.col('ma5')/pl.col('ma5_lag3')-1).alias('short_slope'),
        (pl.col('ma20')/pl.col('ma20_lag5')-1).alias('long_slope'),
        (pl.col('ma10')/pl.col('ma10_lag5')-1).alias('medium_slope'),
        (pl.col('ma40')/pl.col('ma40_lag10')-1).alias('slow_slope'),
        pl.col('daily_return').rolling_std(20).over('vt_symbol').alias('return_vol20'),
        (pl.col('daily_return').abs()>0.25).fill_null(False).alias('large_jump')])
    df=df.with_columns([
        pl.col('cross_short').rolling_max(n).over('vt_symbol').alias(f'cross_short_{n}') for n in (5,10)
    ]+[pl.col('cross_medium').rolling_max(n).over('vt_symbol').alias(f'cross_medium_{n}') for n in (5,10)]
    +[pl.col('positive_short').rolling_sum(n).over('vt_symbol').alias(f'positive_short_{n}') for n in (5,10)]
    +[pl.col('positive_medium').rolling_sum(n).over('vt_symbol').alias(f'positive_medium_{n}') for n in (5,10)]
    +[pl.col('large_jump').cast(pl.Int8).rolling_max(60).over('vt_symbol').fill_null(0).alias('recent_jump'),
      pl.max_horizontal([pl.col('large_jump').cast(pl.Int8).shift(-n).over('vt_symbol').fill_null(0) for n in range(1,7)]).alias('future_jump'),
      pl.col('delta5').shift(5).over('vt_symbol').alias('delta5_lag5')])
    return df

def factor_batch(active:pl.DataFrame,round_number:int)->pl.DataFrame:
    g=pl.col('gap');mg=pl.col('medium_gap');lg=pl.col('long_gap')
    if round_number==1:
        exprs=[g.alias('ma_gap_control')]
        for k in (5,10):
            exprs += [(pl.when((g>0)&(pl.col(f'cross_short_{k}')==1)).then(g).otherwise(0.0)).alias(f'fresh_cross5_{k}')]
        for k in (5,10):
            exprs += [(pl.when((mg>0)&(pl.col(f'cross_medium_{k}')==1)).then(mg).otherwise(0.0)).alias(f'fresh_cross10_{k}')]
        for k in (5,10):
            exprs += [(pl.when(pl.col(f'positive_short_{k}')==k).then(g).otherwise(0.0)).alias(f'persistent5_{k}')]
        for k in (5,10):
            exprs += [(pl.when(pl.col(f'positive_medium_{k}')==k).then(mg).otherwise(0.0)).alias(f'persistent10_{k}')]
        exprs += [(pl.when((g>0)&(lg>0)).then(g).otherwise(0.0)).alias('aligned_short_long'),
                  (pl.when((mg>0)&(pl.col('ma40')>pl.col('ma60'))).then(mg).otherwise(0.0)).alias('aligned_medium_long'),
                  (pl.when((g>0)&(pl.col('short_slope')>0)&(pl.col('long_slope')>0)).then(g).otherwise(0.0)).alias('both_slopes_up')]
    elif round_number==2:
        exprs=[pl.col('delta3').alias('gap_delta3'),pl.col('delta5').alias('gap_delta5'),
               pl.col('delta10').alias('gap_delta10'),pl.col('medium_delta5').alias('medium_gap_delta5'),
               pl.col('medium_delta10').alias('medium_gap_delta10'),
               (g+pl.col('delta5')).alias('gap_plus_delta5'),
               (g-pl.col('delta5')).alias('gap_minus_delta5'),
               (pl.col('short_slope')-pl.col('long_slope')).alias('slope_spread_short'),
               (pl.col('medium_slope')-pl.col('slow_slope')).alias('slope_spread_medium'),
               (pl.col('delta5')-pl.col('delta5_lag5')).alias('gap_acceleration'),
               (pl.when((g>0)&(pl.col('delta5')>0)).then(g).otherwise(0.0)).alias('widening_positive_gap'),
               (pl.when((g>0)&(pl.col('delta5')<0)).then(g).otherwise(0.0)).alias('narrowing_positive_gap')]
    elif round_number==3:
        rising=lg>0
        exprs=[lg.alias('long_ma_control'),
               (pl.when(rising&(pl.col('close_ma5')<0)).then(lg).otherwise(0.0)).alias('pullback_below_ma5'),
               (pl.when(rising&(pl.col('close_ma10')<0)).then(lg).otherwise(0.0)).alias('pullback_below_ma10'),
               (pl.when(rising).then(-pl.col('close_ma5')).otherwise(0.0)).alias('pullback_depth_ma5'),
               (pl.when(rising).then(-pl.col('close_ma10')).otherwise(0.0)).alias('pullback_depth_ma10'),
               (pl.when(rising).then(-pl.col('close_ma20')).otherwise(0.0)).alias('pullback_depth_ma20'),
               (lg-0.5*pl.col('close_ma5')).alias('long_plus_pullback5'),
               (lg-0.5*pl.col('close_ma10')).alias('long_plus_pullback10'),
               (lg-0.5*pl.col('close_ma20')).alias('long_plus_pullback20'),
               (pl.when(rising&(pl.col('close_ma20')>0)&(pl.col('close_ma5')<0)).then(lg).otherwise(0.0)).alias('recovering_above_ma20'),
               (pl.when(rising&(g<0)).then(lg).otherwise(0.0)).alias('short_below_medium_long_up'),
               (pl.when(rising&(g>0)&(pl.col('close_ma5')<0)).then(g).otherwise(0.0)).alias('short_above_medium_pullback')]
    elif round_number==4:
        breadth=pl.col('breadth');vol=pl.col('return_vol20')
        exprs=[(pl.when(breadth>=0.5).then(g).otherwise(0.0)).alias('trend_broad_market'),
               (pl.when(breadth<0.5).then(g).otherwise(0.0)).alias('trend_weak_market'),
               (pl.when(breadth>=0.5).then(-g).otherwise(0.0)).alias('revert_broad_market'),
               (pl.when(breadth<0.5).then(-g).otherwise(0.0)).alias('revert_weak_market'),
               (pl.when(breadth>=0.5).then(pl.col('delta5')).otherwise(0.0)).alias('widening_broad_market'),
               (pl.when(breadth<0.5).then(pl.col('delta5')).otherwise(0.0)).alias('widening_weak_market'),
               (g/vol).alias('vol_scaled_trend'),(-g/vol).alias('vol_scaled_revert'),
               (pl.col('delta5')/vol).alias('vol_scaled_widening'),
               (-pl.col('delta5')/vol).alias('vol_scaled_narrowing'),
               (g-vol).alias('trend_above_noise'),(-g-vol).alias('revert_above_noise')]
    else:raise ValueError('round must be 1..4')
    assert len(exprs)==len(ROUND_NAMES[round_number])==12
    return active.with_columns(exprs)

def sample_frame(raw:pl.DataFrame,round_number:int,source:str,membership=None)->tuple[pl.DataFrame,dict]:
    df=base_features(raw)
    days=sorted(df['day'].unique().to_list())
    start=TRAIN[0] if source=='teacher' else FRESH[0]
    end=VALID[1] if source=='teacher' else FRESH[1]
    anchor=next(i for i,day in enumerate(days) if day>=start)
    if source=='teacher':
        ranges=[(s,a.date(),b.date()) for s,periods in membership.items() for a,b in periods]
        active=df.join(pl.DataFrame(ranges,schema=['vt_symbol','member_start','member_end'],orient='row'),on='vt_symbol')
        active=active.filter(pl.col('day').is_between(pl.col('member_start'),pl.col('member_end')))
        if active.unique(['vt_symbol','day']).height!=active.height:raise ValueError('overlapping membership')
    else:
        active=df  # Downloader already limited to a cohort frozen before the fresh period.
    active=active.with_columns((pl.col('gap')>0).cast(pl.Float64).mean().over('day').alias('breadth'))
    active=factor_batch(active,round_number)
    calendar=pl.DataFrame({'day':days[:-6],'entry_day':days[1:-5],'exit_day':days[6:]})
    calendar=calendar.with_columns(pl.Series('ordinal',range(len(calendar))))
    calendar=calendar.filter((pl.col('ordinal')>=anchor)&((pl.col('ordinal')-anchor)%STEP==0)&pl.col('day').is_between(start,end))
    active=active.join(calendar.select('day','entry_day','exit_day'),on='day')
    before=active.height
    bars=df.select('vt_symbol','day','open','volume','tradestatus')
    active=active.join(bars.rename({'day':'entry_day','open':'entry_open','volume':'entry_volume','tradestatus':'entry_status'}),on=['vt_symbol','entry_day'],how='left')
    active=active.join(bars.rename({'day':'exit_day','open':'exit_open','volume':'exit_volume','tradestatus':'exit_status'}),on=['vt_symbol','exit_day'],how='left')
    active=active.with_columns((pl.col('exit_open')/pl.col('entry_open')-1).alias('forward_return'))
    active=active.filter((pl.col('volume')>0)&(pl.col('entry_volume')>0)&(pl.col('exit_volume')>0)&
        (pl.col('tradestatus')==1)&(pl.col('entry_status')==1)&(pl.col('exit_status')==1)&
        (pl.col('isST')==0)&(pl.col('recent_jump')==0)&(pl.col('future_jump')==0)&
        pl.col('forward_return').is_finite())
    frame=active.select('day','exit_day','vt_symbol','forward_return',*ROUND_NAMES[round_number])
    return frame,{'source':source,'potential_signal_rows':before,'eligible_rows':frame.height,
                  'sample_dates':frame['day'].n_unique(),'factors':len(ROUND_NAMES[round_number]),
                  'historical_membership':source=='teacher','frozen_cohort':source=='fresh'}

def metrics(frame:pl.DataFrame,name:str,period:tuple[date,date])->dict:
    start,end=period
    x=frame.filter(pl.col('day').is_between(start,end)&(pl.col('exit_day')<=end)&pl.col(name).is_finite())
    if x.is_empty():return {'days':0,'signals':0,'error':'no rows'}
    x=x.with_columns(pl.col(name).rank('average').over('day').alias('score_rank'),
                     pl.col('forward_return').rank('average').over('day').alias('target_rank'))
    daily=x.group_by('day').agg(pl.len().alias('stocks'),(pl.col(name)>0).sum().alias('signals'),
        pl.col('forward_return').mean().alias('baseline_mean'),
        pl.col('forward_return').filter(pl.col(name)>0).mean().alias('signal_mean'),
        (pl.col('forward_return')>0).filter(pl.col(name)>0).mean().alias('signal_up_rate'),
        (pl.col('forward_return')>0).mean().alias('baseline_up_rate'),
        pl.corr('score_rank','target_rank').alias('rank_ic'))
    daily=daily.filter((pl.col('stocks')>=50)&(pl.col('signals')>=20)&pl.col('rank_ic').is_finite())
    if daily.is_empty():return {'days':0,'signals':0,'error':'insufficient daily sections'}
    daily=daily.with_columns((pl.col('signal_mean')-pl.col('baseline_mean')).alias('edge'))
    out=daily.select(pl.len().alias('days'),pl.col('signals').sum().alias('signals'),
        pl.col('stocks').mean().alias('stocks_per_day'),
        pl.col('signal_mean').mean().alias('signal_mean'),
        pl.col('baseline_mean').mean().alias('baseline_mean'),
        pl.col('edge').mean().alias('edge'),pl.col('edge').std().alias('edge_sd'),
        (pl.col('edge')>0).mean().alias('edge_positive_day_fraction'),
        pl.col('signal_up_rate').mean().alias('signal_up_rate'),
        pl.col('baseline_up_rate').mean().alias('baseline_up_rate'),
        pl.col('rank_ic').mean().alias('rank_ic')).row(0,named=True)
    out['after_0p3pct_cost_sensitivity']=out['signal_mean']-COST
    return out

def qualifies(x:dict)->bool:
    return all((m.get('days',0)>=60 and m.get('signals',0)>=500 and
                m['signal_mean']>COST and m['edge']>0.0015 and m['rank_ic']>0.01)
               for m in (x['train'],x['valid']))

def save(path:Path,obj:dict)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n')

def main()->None:
    parser=argparse.ArgumentParser()
    parser.add_argument('teacher_cache',type=Path)
    parser.add_argument('--stage',choices=['explore','finalize'],default='explore')
    parser.add_argument('--round',type=int,choices=[1,2,3,4],default=1)
    parser.add_argument('--fresh-parquet',type=Path,default=ROOT/'data/factor_research/ma_holdout_2024_2025.parquet')
    parser.add_argument('--output-dir',type=Path,default=DEFAULT_OUT)
    args=parser.parse_args()
    outdir=args.output_dir
    if (outdir/'final.json').exists():raise RuntimeError('Final holdout already viewed; study is closed')
    teacher_hashes={p.name:sha256(p.read_bytes()).hexdigest() for p in args.teacher_cache.glob('*.pkl')}
    if args.stage=='explore':
        path=outdir/f'round_{args.round:02}.json'
        if path.exists():raise RuntimeError('Round already saved; keep the audit trail')
        if args.round>1 and not (outdir/f'round_{args.round-1:02}.json').exists():raise RuntimeError('Rounds must be consecutive')
        df,members=read_cache(args.teacher_cache)
        frame,data=sample_frame(df,args.round,'teacher',members)
        rows=[]
        for name in ROUND_NAMES[args.round]:
            item={'name':name,'train':metrics(frame,name,TRAIN),'valid':metrics(frame,name,VALID)}
            item['qualifies']=qualifies(item)
            rows.append(item)
        out={'round':args.round,'clue':CLUES[args.round],
             'train':[str(x) for x in TRAIN],'valid':[str(x) for x in VALID],
             'target':'t+1 open to t+6 open (five market trading-day intervals)',
             'primary':'signal>0 daily mean raw return and excess vs same-day eligible cohort',
             'secondary':'same-day Spearman rank IC',
             'screen':'train and valid >=60 days, >=500 signals, gross>0.3%, edge>0.15pp, rank IC>0.01',
             'test_viewed':False,'source_hashes':teacher_hashes,'data':data,'results':rows}
        save(path,out)
        print('round',args.round,'candidates',len(rows),'qualifying',sum(x['qualifies'] for x in rows),'holdout untouched')
        for x in sorted(rows,key=lambda r:r['valid'].get('edge',-99),reverse=True):
            print(x['name'],'train_edge',round(x['train'].get('edge',0),5),
                  'valid_edge',round(x['valid'].get('edge',0),5),
                  'valid_IC',round(x['valid'].get('rank_ic',0),4),'qualifies',x['qualifies'])
    else:
        paths=[outdir/f'round_{n:02}.json' for n in range(1,5)]
        if not all(p.exists() for p in paths):raise RuntimeError('Complete four discovery rounds before opening new holdout')
        rounds=[json.loads(p.read_text()) for p in paths]
        if any(r['source_hashes']!=teacher_hashes for r in rounds):raise RuntimeError('Teacher data changed')
        if not args.fresh_parquet.exists():raise RuntimeError('Fresh holdout file missing')
        candidates=[(r['round'],x) for r in rounds for x in r['results'] if x['qualifies']]
        fallback=False
        if not candidates:
            fallback=True
            candidates=[(r['round'],x) for r in rounds for x in r['results']
                        if x['train'].get('days',0)>=60 and x['valid'].get('days',0)>=60
                        and x['train'].get('edge',-1)>0]
        if not candidates:
            fallback=True
            candidates=[(r['round'],x) for r in rounds for x in r['results'] if x['valid'].get('days',0)>=60]
        if not candidates:raise RuntimeError('No evaluable candidate; do not open holdout')
        chosen_round,chosen=max(candidates,key=lambda pair:pair[1]['valid']['edge'])
        fresh=pl.read_parquet(args.fresh_parquet)
        frame,data=sample_frame(fresh,chosen_round,'fresh')
        out={'selected':chosen['name'],'round':chosen_round,
             'selection':'highest validation edge among qualifiers; fallback to train-positive edge if none qualifies',
             'fallback_diagnostic_only':fallback,
             'train':chosen['train'],'valid':chosen['valid'],
             'holdout':metrics(frame,chosen['name'],FRESH),
             'holdout_period':[str(x) for x in FRESH],
             'fresh_parquet_sha256':sha256(args.fresh_parquet.read_bytes()).hexdigest(),
             'teacher_hashes':teacher_hashes,'data':data,'holdout_viewed_once':True}
        save(outdir/'final.json',out)
        print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
