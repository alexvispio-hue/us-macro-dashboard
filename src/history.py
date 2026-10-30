"""Snapshot comparisons and source provenance; never exports credentials."""
from __future__ import annotations
from pathlib import Path
import datetime as dt
import pandas as pd
import sources
import config as C
import catalogue

BASE = {
 'tlt':['TLT'],'move':['MOVE'],'vix':['VIXCLS'],'marketvix':['VIXCLS'],'dxy':['DXY'],
 'ffr':['DFF'],'t5yie':['T5YIE'],'real10':['DFII10'],'real10b':['DFII10'],'stance':['DFF','DGS2'],
 'curve':['T10Y3M','T10Y2Y'],'curve3':['T10Y3M','T10Y2Y'],'risk':['HYG','LQD'],'nfci':['NFCI'],
 'carry':['DGS30','JP30Y'],'ffr3m':['DFF','DTB3'],'gm2':['M2SL','M2EU','M2JP','M2CN','M2UK'],
 'gli':['WALCL','ECBASSETSW','JPNASSETS'],'cbparts':['WALCL','ECBASSETSW','JPNASSETS'],
 'netliq':['WALCL','WTREGEN','RRPONTSYD'],'rrp':['RRPONTSYD'],
 'stress':['VIXCLS','MOVE','BAMLH0A0HYM2','NFCI','STLFSI4'],'sahm':['SAHMREALTIME'],
 'spx3':['SPX','USREC'],'rspx':['SPX','CPIAUCSL'],'spxhgx':['SPX','HGX'],
 'exhs':['HSN1F'],'permit':['PERMIT'],'cs':['CSUSHPINSA'],
 'spy':['SPY'],'rsi':['SPY'],'spyvolume':['SPY'],'systemstress':['VIXCLS'],
 'gold':['GOLD'],'cotflow':['CFTC'],'cotnet':['CFTC'],'cotls':['CFTC'],'cotoi':['CFTC'],
 'broker-m2':['BOGZ1FL663067003Q','M2SL'],'payroll-change':['PAYEMS'],'sofr-iorb':['SOFR','IORB'],
}

def panels(payload):
    result={}
    for col in payload['columns']+payload['markets']['columns']+[c for w in payload.get('workspaces',[]) for c in w['columns']]:
        for panel in col['panels']:result[panel['id']]=panel
    return result

def annotate(payload, raw):
    for panel in panels(payload).values():
        ids=panel.get('source_ids') or BASE.get(panel['id']) or [s['name'] for s in panel['series'] if s['name'] in raw]
        items=[]
        for sid in ids:
            series=raw.get(sid,pd.Series(dtype=float))
            if sid in C.FRED or sid in catalogue.FRED or sid.startswith('DGS'):
                provider='FRED';url='https://fred.stlouisfed.org/series/'+sid;cache=sources.RAW/f'fred_{sid}.csv'
            elif sid in C.YAHOO or sid in catalogue.YAHOO or sid=='GOLD':
                symbol=(C.YAHOO|catalogue.YAHOO|{'GOLD':'GC=F'}).get(sid,sid)
                provider='Yahoo Finance';url='https://finance.yahoo.com/quote/'+symbol+'/';cache=sources.RAW/f'yahoo_{sid}.json'
            else:
                provider,url,filename={
                  'M2EU':('ECB / DBnomics','https://db.nomics.world/ECB/BSI','dbnomics_M2EU.json'),
                  'M2JP':('Bank of Japan','https://www.boj.or.jp/en/statistics/money/ms/index.htm','boj_M2JP.html'),
                  'M2CN':('PBOC / East Money','https://data.eastmoney.com/cjsj/hbgyl.html','eastmoney_M2CN.json'),
                  'M2UK':('Bank of England','https://www.bankofengland.co.uk/statistics/money-and-credit','boe_M2UK.csv'),
                  'JP30Y':('Japan Ministry of Finance','https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/','jgb_cur.csv'),
                  'CFTC':('CFTC','https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm','cot_gold.json'),
                }.get(sid,('Public source','', ''))
                cache=sources.RAW/filename
            cadence=float(pd.Series(series.index).diff().dt.days.dropna().median()) if len(series)>2 else None
            freq='Неделя' if sid=='CFTC' else 'День' if provider=='Yahoo Finance' else 'День' if cadence is not None and cadence<4 else 'Неделя' if cadence is not None and cadence<15 else 'Месяц' if cadence is not None and cadence<60 else 'Квартал' if cadence is not None else 'См. источник'
            stamp=series.dropna().index[-1].strftime('%Y-%m-%d') if len(series.dropna()) else None
            items.append(dict(id=sid,provider=provider,url=url,frequency=freq,asof=stamp,
                cached=dt.datetime.fromtimestamp(cache.stat().st_mtime,dt.timezone.utc).isoformat() if cache.is_file() else None))
        panel['sources']=items
    return payload

def snapshot_change(previous,current):
    oldpanels=panels(previous) if previous else {}
    rows=[]
    for pid,panel in panels(current).items():
        oldrows={s['name']:s for s in oldpanels.get(pid,{}).get('series',[])}
        for row in panel['series']:
            old=oldrows.get(row['name']); data=row.get('data',[])
            if not data:
                if old and old.get('data'):
                    rows.append(dict(panel=pid,title=panel['title'],series=row['name'],kind='Данные недоступны',before=old.get('lastRaw'),after=None,delta=None,previousDate=old.get('asof'),date=None,revisions=0))
                continue
            olddata={r['time']:r for r in old.get('data',[])} if old else {}
            revisions=sum(1 for r in data if r['time'] in olddata and r!=olddata[r['time']])
            kind='Добавлен ряд' if old is None else 'Новое наблюдение' if (row.get('asof') or '')>(old.get('asof') or '') else 'Пересчёт / уточнение' if revisions or row.get('lastRaw')!=old.get('lastRaw') else None
            if kind:
                before=old.get('lastRaw') if old else None;after=row.get('lastRaw')
                rows.append(dict(panel=pid,title=panel['title'],series=row['name'],kind=kind,before=before,after=after,
                    delta=after-before if after is not None and before is not None else None,
                    previousDate=old.get('asof') if old else None,date=row.get('asof'),revisions=revisions))
    # Offline rebuilds with identical data keep the last meaningful comparison.
    if not rows and previous and previous.get('changes'):
        return previous['changes']
    return dict(previous=previous.get('generated') if previous else None,current=current['generated'],rows=rows,
        note='Сравнение сборок. Уточнение истории может отражать пересмотр источника или изменение расчёта; это не оценка неожиданности публикации.')
