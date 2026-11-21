"""Daily market overview and Nasdaq advances/declines."""
from __future__ import annotations

import datetime as dt
from io import StringIO

import numpy as np
import pandas as pd

import derive as D
import sources

NASDAQ_FILES = 'https://nasdaqtrader.com/Trader.aspx?id=DailyMarketFiles'
NASDAQ_COUNTS = ['Advances', 'Declines', 'Unchanged']


def parse_breadth(text, year):
    data = pd.read_csv(StringIO(text), usecols=['Date', *NASDAQ_COUNTS])
    dates = pd.to_datetime(data.pop('Date'), format='%m/%d/%Y %H:%M:%S', errors='coerce')
    data = data.apply(pd.to_numeric, errors='coerce')
    valid = (dates.dt.year.eq(year) & dates.le(pd.Timestamp(dt.date.today()))
             & np.isfinite(data).all(axis=1) & data.ge(0).all(axis=1)
             & data.mod(1).eq(0).all(axis=1) & data.sum(axis=1).gt(0))
    data = data.loc[valid].set_index(pd.DatetimeIndex(dates[valid]))
    return data.loc[~data.index.duplicated(keep='last')].sort_index()


def fetch_breadth():
    year = dt.date.today().year
    frames = []
    for file_year in (year - 1, year):
        cache = sources.RAW / f'nasdaq_market_{file_year}.csv'
        cached = pd.DataFrame(columns=NASDAQ_COUNTS, dtype=float)
        if cache.is_file():
            try:
                cached = parse_breadth(cache.read_text(encoding='utf-8-sig'), file_year)
            except (OSError, ValueError):
                pass
        if file_year == year and not sources.OFFLINE and (cached.empty or not sources._fresh(cache)):
            try:
                text = sources._get(f'https://nasdaqtrader.com/dynamic/dailyfiles/daily{file_year}.csv',
                                    timeout=15, retries=2)
                refreshed = parse_breadth(text, file_year)
                if refreshed.empty or (not cached.empty and refreshed.index[-1] < cached.index[-1]):
                    raise ValueError('нет актуальных наблюдений')
                staged = cache.with_suffix('.tmp')
                staged.write_text(text, encoding='utf-8')
                staged.replace(cache)
                cached = refreshed
                sources._log('NASDAQ', 'Breadth', 'ok', f'last={cached.index[-1].date()}')
            except (OSError, ValueError, RuntimeError) as exc:
                sources._log('NASDAQ', 'Breadth', 'warning',
                             f'{file_year}: {exc}. ' + ('Показан кэш.' if not cached.empty else 'Данные недоступны.'))
        if not cached.empty:
            frames.append(cached)
    return pd.concat(frames) if frames else pd.DataFrame(columns=NASDAQ_COUNTS, dtype=float)


def clean(series):
    return series.replace([np.inf, -np.inf], np.nan).dropna().sort_index()


def close_change(series, sessions):
    closes = series.reindex(sessions)
    if len(closes) != 2 or closes.isna().any() or closes.iloc[0] <= 0:
        return None
    return float((closes.iloc[1] / closes.iloc[0] - 1) * 100)


def build(raw, workspaces):
    series = lambda key: clean(raw.get(key, pd.Series(dtype=float)))
    spx = series('SPX')
    sessions = spx.index[-2:]
    sector_workspace = next(w for w in workspaces if w['id'] == 'sectors')
    sectors = []
    # SOXX is an industry ETF. Use the 11 sector funds for the sector ranking.
    for col in sector_workspace['columns']:
        for panel in col['panels']:
            ticker = panel['source_ids'][0]
            if ticker != 'SOXX':
                sectors.append(dict(panel=panel['id'], ticker=ticker, title=panel['title'],
                                    delta=close_change(series(ticker), sessions)))
    sectors.sort(key=lambda row: (row['delta'] is None, -(row['delta'] or 0)))

    breadth = fetch_breadth()
    share = breadth.Advances.div(breadth.sum(axis=1)).mul(100)
    breadth_panel = D._p('nasdaq-breadth', 'Доля выросших бумаг Nasdaq',
                        [D._s('Выросли', share, '#5bd8c0', suffix='%')],
                        sub='Выросшие / (выросшие + снизившиеся + без изменений). Nasdaq Trader.')
    breadth_panel['allowUnavailable'] = True
    breadth_panel['sources'] = [dict(id='Advances / Declines / Unchanged', provider='Nasdaq Trader',
                                    url=NASDAQ_FILES, frequency='День',
                                    asof=breadth_panel['series'][0]['asof'], cached=None)]

    extra = [breadth_panel]
    for pid, title, sid, suffix, color in [
        ('today-spx', 'S&P 500', 'SPX', '', '#90aaff'),
        ('today-hy-oas', 'Кредитный спред High Yield', 'BAMLH0A0HYM2', ' б.п.', '#e8c47a'),
        ('today-ig-oas', 'Кредитный спред Investment Grade', 'BAMLC0A0CM', ' б.п.', '#90aaff'),
        ('today-stlfsi', 'Финансовый стресс STLFSI', 'STLFSI4', '', '#e38ca9'),
    ]:
        data = series(sid)
        if suffix:
            data *= 100  # FRED reports OAS in percentage points.
        panel = D._p(pid, title, [D._s(sid, data, color, suffix=suffix)])
        panel['source_ids'] = [sid]
        panel['allowUnavailable'] = True
        extra.append(panel)

    metrics = []
    for panel_id, title, data, unit, change_unit, is_price in [
        ('today-spx', 'S&P 500', spx, '', '%', True),
        ('us-QQQ', 'Nasdaq 100 · ETF QQQ', series('QQQ'), ' $', '%', True),
        ('vix', 'VIX', D.vix_series(raw), '', ' п.', False),
        ('move', 'MOVE', series('MOVE'), '', ' п.', False),
        ('today-hy-oas', 'Спред High Yield', series('BAMLH0A0HYM2') * 100, ' б.п.', ' б.п.', False),
        ('today-ig-oas', 'Спред Investment Grade', series('BAMLC0A0CM') * 100, ' б.п.', ' б.п.', False),
        ('nfci', 'Финансовые условия NFCI', series('NFCI'), '', ' п.', False),
        ('today-stlfsi', 'Финансовый стресс STLFSI', series('STLFSI4'), '', ' п.', False),
    ]:
        stamp = D.asof(data)
        delta = close_change(data, data.index[-2:]) if is_price else D.last_val(data.diff().iloc[-1:])
        metrics.append(dict(panel=panel_id, title=title, value=D.last_val(data), delta=delta,
                            unit=unit, changeUnit=change_unit, date=stamp.strftime('%Y-%m-%d') if stamp is not None else None,
                            previousDate=data.index[-2].strftime('%Y-%m-%d') if len(data) > 1 else None,
                            marketSession=is_price))

    breadth_summary = dict(share=D.last_val(share), date=breadth_panel['series'][0]['asof'],
                           counts={name: int(breadth.iloc[-1][name]) for name in NASDAQ_COUNTS}
                           if not breadth.empty else {})
    return dict(id='market-today', kind='marketToday', family='WORKSPACE', title='Рынок сегодня',
                note='Последний снимок рынка США. У рыночных индикаторов и макрорядов свои даты наблюдений.',
                columns=[dict(title='РЫНОК США', panels=extra)], metrics=metrics,
                sectors=sectors, session=sessions[-1].strftime('%Y-%m-%d') if len(sessions) else None,
                breadth=breadth_summary)
