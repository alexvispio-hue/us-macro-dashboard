"""Market workspaces: public OHLCV, Treasury curves and managed-money COT."""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
import sources
import derive as D

TENORS = [('1M','DGS1MO'),('3M','DGS3MO'),('6M','DGS6MO'),('1Y','DGS1'),
          ('2Y','DGS2'),('3Y','DGS3'),('5Y','DGS5'),('7Y','DGS7'),
          ('10Y','DGS10'),('20Y','DGS20'),('30Y','DGS30')]

def bars(name, symbol):
    sources.fetch_yahoo(name, symbol)
    path = sources.RAW / f'yahoo_{name}.json'
    try:
        r = json.loads(path.read_text(encoding='utf-8'))['chart']['result'][0]
        q = r['indicators']['quote'][0]
        frame = pd.DataFrame({k:q[k] for k in ['open','high','low','close','volume']},
                             index=pd.to_datetime(r['timestamp'], unit='s', utc=True).tz_localize(None).normalize())
        frame = frame.dropna(subset=['open','high','low','close']).sort_index()
        frame = frame[~frame.index.duplicated(keep='last')]
        frame = frame[(frame.index >= D.DISPLAY_START) & (frame.high >= frame.low)]
        frame['volume'] = frame.volume.fillna(0).clip(lower=0)
        return frame
    except Exception as exc:
        sources._log('OHLCV', name, 'fail', str(exc))
        return pd.DataFrame(columns=['open','high','low','close','volume'])

def cot():
    path = sources.RAW / 'cot_gold.json'
    try:
        if not sources._fresh(path) and not sources.OFFLINE:
            url = ('https://publicreporting.cftc.gov/resource/72hh-3qpy.json'
                   '?$where=cftc_contract_market_code%3D%27088691%27'
                   '&$order=report_date_as_yyyy_mm_dd&$limit=50000')
            text = sources._get(url, timeout=30, retries=1)
            parse_cot(text)  # Validate before replacing a usable cache.
            path.write_text(text, encoding='utf-8')
        frame = parse_cot(path.read_text(encoding='utf-8'))
        sources._log('CFTC','GOLD MM','cache' if sources.OFFLINE else 'ok', f'n={len(frame)}; {frame.index[-1].date()}')
        return frame
    except Exception as exc:
        if path.exists():
            try:
                frame = parse_cot(path.read_text(encoding='utf-8'))
                sources._log('CFTC','GOLD MM','cache','Старый кэш: ' + str(exc))
                return frame
            except Exception:
                pass
        sources._log('CFTC','GOLD MM','fail',str(exc))
        return pd.DataFrame(columns=['long','short','oi'])

def parse_cot(text):
    frame = pd.DataFrame(json.loads(text))
    idx = pd.to_datetime(frame['report_date_as_yyyy_mm_dd']).dt.normalize()
    cols = {'long':'m_money_positions_long_all','short':'m_money_positions_short_all','oi':'open_interest_all'}
    out = pd.DataFrame({k:pd.to_numeric(frame[v], errors='coerce').values for k,v in cols.items()}, index=idx)
    out = out.dropna().sort_index()
    out = out[~out.index.duplicated(keep='last')]
    if out.empty:
        raise ValueError('Пустой отчёт CFTC Gold 088691')
    return out

def normalized(s, window=156):
    lo, hi = s.rolling(window, min_periods=26).min(), s.rolling(window, min_periods=26).max()
    return 200 * (s-lo) / (hi-lo).replace(0, np.nan) - 100

def rsi(s, n=14):
    delta = s.diff()
    def wilder(values):
        values = values.copy()
        if len(values) > n:
            values.iloc[n] = values.iloc[1:n+1].mean()
        values.iloc[:n] = np.nan
        return values.ewm(alpha=1/n, adjust=False).mean()
    up = wilder(delta.clip(lower=0))
    down = wilder(-delta.clip(upper=0))
    out = 100 - 100 / (1 + up/down.replace(0,np.nan))
    return out.mask((down == 0) & (up > 0), 100).mask((up == 0) & (down == 0), 50)

def price_panel(pid, title, frame):
    close = frame.close
    series = D._s(title, close, '#e4e8ef', 'candles')
    series['data'] = [dict(time=t.strftime('%Y-%m-%d'), **{k:float(v) for k,v in row.items()}) for t,row in frame.iterrows()]
    p = D._p(pid,title,[series],height=3.5,
        sub='Yahoo Finance · профиль видимого диапазона: оценка по дневным OHLCV · EMA 50/200')
    p['profile'] = True
    p['band'] = {'fast':D.to_points(close.ewm(span=50,adjust=False).mean()),
                 'slow':D.to_points(close.ewm(span=200,adjust=False).mean())}
    p['series'] += [D._s('EMA 50',close.ewm(span=50,adjust=False).mean(),'#50ba70'),
                    D._s('EMA 200',close.ewm(span=200,adjust=False).mean(),'#218c49')]
    return p

def build(raw):
    spy, gold, mm = bars('SPY','SPY'), bars('GOLD','GC=F'), cot()
    sp = price_panel('spy','SPY · S&P 500',spy)
    gp = price_panel('gold','GOLD · COMEX futures',gold)
    def panel(pid,title,series,**kw): return D._p(pid,title,series,**kw)
    def s(name,data,color,kind=None): return D._s(name,data,color,kind)
    vix = raw.get('VIXCLS',pd.Series(dtype=float))
    stress = vix.rolling(252,min_periods=60).rank(pct=True)*100
    stressp = panel('systemstress','System Stress · VIX percentile',[s('VIX percentile',stress,'#36ccc2','area')],
                    sub='Аналог: процентиль VIX за 252 наблюдения; COR1M не включён',height=1.1)
    stressp['levels'] = [80,95]
    sp['zones'] = D.to_points((stress >= 80).astype(float))
    r = panel('rsi','RSI · SPY · 14',[s('RSI',rsi(spy.close),'#e3ce62')],height=.8)
    r['levels'] = [30,70]
    net = mm.long-mm.short
    flow = pd.DataFrame({'Long':mm.long.diff(),'Short':mm.short.diff(),'Net':net.diff()})
    flowz = (flow-flow.rolling(52,min_periods=13).mean())/flow.rolling(52,min_periods=13).std().replace(0,np.nan)
    cotpanels = [panel('cotflow','MM COT Flow · z-score',[s(k,flowz[k],c,'scatter') for k,c in zip(flowz,['#2ed1ac','#ef647a','#e7be53'])],zero=True,sub='Изменение позиций за неделю; z-score за 52 отчёта. CFTC Futures Only.'),
        panel('cotnet','MM COT Net Index',[s('Net',normalized(net),'#63c259','baseline')],zero=True,sub='200 × (net − min) / (max − min) − 100; окно 156 недель'),
        panel('cotls','MM COT Long / Short Index',[s('Long',normalized(mm.long),'#2ed1ac'),s('Short',normalized(mm.short),'#ef647a')],zero=True,sub='Индексы позиций: диапазон −100…100 за 156 недель'),
        panel('cotoi','MM COT OI Index',[s('Open interest',normalized(mm.oi),'#e2c166')],zero=True,sub='Индекс общего open interest рынка Gold, 156 недель')]
    rows=[]
    for label,sid in TENORS:
        data=raw.get(sid)
        if data is None: data=sources.fetch_fred(sid)
        rows.append((label,data))
    nonempty=[a for _,a in rows if len(a)]
    anchor=min(a.index.max() for a in nonempty) if nonempty else pd.Timestamp.today().normalize()
    curves=[]
    for label,offset,color in [('Сейчас',pd.Timedelta(0),'#a39cf6'),('Неделю назад',pd.Timedelta(days=7),'#9bc377'),('Месяц назад',pd.DateOffset(months=1),'#df9f6c')]:
        date=anchor-offset
        values=[]
        for tenor,data in rows:
            a=data.loc[:date].dropna()
            valid=len(a) and (date-a.index[-1]).days <= 7
            values.append({'tenor':tenor,'value':float(a.iloc[-1]) if valid else None,
                           'asof':a.index[-1].strftime('%Y-%m-%d') if valid else None})
        curves.append(dict(name=label,date=date.strftime('%Y-%m-%d'),color=color,values=values))
    # Available raw positions and weekly changes shown next to the gold workspace.
    summary=[]
    for name,a in [('Long',mm.long),('Short',mm.short),('Net',net)]:
        summary.append(dict(name=name,value=D.last_val(a),change=D.last_val(a.diff()),asof=str(a.index[-1].date()) if len(a) else None))
    volume=panel('spyvolume','SPY · Volume',[s('Объём',spy.volume,'#5f98c3','volume')],height=.7)
    return dict(columns=[{'title':'S&P 500 · ЦЕНА И СТРЕСС','panels':[r,sp,volume,stressp,
        panel('marketvix','VIX',[s('VIX',vix,'#6c9fe8')],height=.7)]},
        {'title':'GOLD · MANAGED MONEY','panels':[gp]+cotpanels}], curves=curves,cot=summary)
