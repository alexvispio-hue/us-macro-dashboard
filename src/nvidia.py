"""NVIDIA share short interest and NVDAUSDT perpetual positioning."""
from __future__ import annotations

import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import requests

import derive as D
import market
import sources

NASDAQ = 'https://www.nasdaq.com/market-activity/stocks/nvda/short-interest'
BINANCE = 'https://www.binance.com/en/futures/NVDAUSDT'
FUTURES_DATA = 'https://fapi.binance.com/futures/data/'
FUTURES_QUERY = '?symbol=NVDAUSDT&period=1d&limit=30'


def cached_at(filename):
    path = sources.RAW / filename
    if path.is_file():
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    return None


def parse_short_interest(text):
    data = json.loads(text)['data']
    if data['symbol'].upper() != 'NVDA':
        raise ValueError('Неверный символ Nasdaq')
    rows = pd.DataFrame(data['shortInterestTable']['rows'])
    dates = pd.to_datetime(rows['settlementDate'], format='%m/%d/%Y')
    shares = pd.to_numeric(rows['interest'].str.replace(',', '', regex=False))
    return pd.DataFrame({'shares': shares.to_numpy()}, index=pd.DatetimeIndex(dates))


def parse_futures(text, columns):
    rows = pd.DataFrame(json.loads(text))
    if not rows['symbol'].eq('NVDAUSDT').all():
        raise ValueError('Неверный символ Binance')
    dates = pd.to_datetime(rows['timestamp'], unit='ms', utc=True).dt.tz_localize(None).dt.normalize()
    values = rows[list(columns)].apply(pd.to_numeric).rename(columns=columns)
    values.index = pd.DatetimeIndex(dates)
    return values


def parse_position_share(text):
    frame = parse_futures(text, {'longAccount': 'long', 'shortAccount': 'short'})
    if not ((frame <= 1).all(axis=1) & np.isclose(frame.sum(axis=1), 1, atol=.0002)).all():
        raise ValueError('Некорректные доли лонг и шорт')
    return frame * 100


def load(cache_name, provider, url, parse, retrieve=sources._get):
    """Validate a fresh download before replacing the last usable response."""
    cache = sources.RAW / cache_name

    def checked(text):
        frame = parse(text).sort_index()
        if (frame.empty or frame.index.hasnans or frame.index.has_duplicates
                or frame.index[-1] > pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()
                or not np.isfinite(frame.to_numpy()).all() or (frame < 0).any().any()):
            raise ValueError('Пустой или некорректный ряд')
        return frame

    try:
        if not sources.OFFLINE and not sources._fresh(cache):
            text = retrieve(url)
            result = checked(text)
            if cache.exists():
                try:
                    previous = checked(cache.read_text(encoding='utf-8'))
                except (ValueError, KeyError, TypeError, AttributeError, OSError):
                    previous = None
                if previous is not None and result.index[-1] < previous.index[-1]:
                    raise ValueError('Источник вернул более старый снимок')
            pending = cache.with_suffix('.tmp')
            pending.write_text(text, encoding='utf-8')
            pending.replace(cache)
            sources._log(provider, cache.stem, 'ok', f'last={result.index[-1].date()}')
            return result
        return checked(cache.read_text(encoding='utf-8'))
    except (ValueError, KeyError, TypeError, AttributeError, OSError, sources.HostBlocked) as exc:
        if not sources.OFFLINE:
            sources._log(provider, cache.stem, 'warning', str(exc))
        try:
            return checked(cache.read_text(encoding='utf-8'))
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            return pd.DataFrame()


def fetch_nasdaq(url):
    response = sources.SESSION.get(url, headers={
        'Accept': 'application/json, */*',
        'Origin': 'https://www.nasdaq.com',
        'Referer': NASDAQ,
    }, timeout=15)
    response.raise_for_status()
    return response.text


def build():
    bars = market.bars('NVDA', 'NVDA')
    price = market.price_panel('nvda-price', 'NVDA · Акции NVIDIA', bars)
    price['sub'] += ' · POC — цена максимального объёма. Светлая зона содержит около 70% объёма'
    price['profileUnit'] = ' акций'
    price['sources'] = [dict(id='NVDA', provider='Yahoo Finance',
                             url='https://finance.yahoo.com/quote/NVDA/',
                             frequency='День', asof=price['series'][0]['asof'],
                             cached=cached_at('yahoo_NVDA.json'))]

    def positioning_panel(pid, title, provider, link, frequency, cache, data, specs, note):
        panel = D._p(pid, title, [
            D._s(label, data[column], color, suffix=unit) if column in data
            else D._s(label, pd.Series(dtype=float), color, suffix=unit)
            for column, label, color, unit in specs
        ], sub=note)
        panel['sources'] = [dict(id=title, provider=provider, url=link, frequency=frequency,
                                 asof=panel['series'][0]['asof'], cached=cached_at(cache))]
        # These independent market feeds can be temporarily unavailable. The
        # panel still shows the source and the dashboard can update other rows.
        panel['allowUnavailable'] = True
        return panel

    short = load('nasdaq_nvda_short.json', 'Nasdaq',
                 'https://api.nasdaq.com/api/quote/NVDA/short-interest?assetclass=stocks',
                 parse_short_interest, retrieve=fetch_nasdaq)
    share = load('binance_nvda_position.json', 'Binance',
                 FUTURES_DATA + 'topLongShortPositionRatio' + FUTURES_QUERY, parse_position_share)
    interest = load('binance_nvda_oi.json', 'Binance',
                    FUTURES_DATA + 'openInterestHist' + FUTURES_QUERY,
                    lambda text: parse_futures(text, {'sumOpenInterest': 'quantity',
                                                      'sumOpenInterestValue': 'notional'}))
    if 'notional' in interest:
        interest['notional'] /= 1_000_000
    panels = [
        positioning_panel('nvda-position', 'NVDAUSDT · Доли лонг / шорт', 'Binance', BINANCE, 'День · UTC',
                          'binance_nvda_position.json', share,
                          [('long', 'Лонг', '#2ed1ac', '%'), ('short', 'Шорт', '#ef647a', '%')],
                          'Доли объёма позиций у 20% трейдеров с наибольшим маржинальным балансом на Binance'),
        positioning_panel('nvda-oi', 'NVDAUSDT · Открытый интерес', 'Binance', BINANCE, 'День · UTC',
                          'binance_nvda_oi.json', interest,
                          [('notional', 'Открытый интерес', '#e2c166', ' млн USDT'),
                           ('quantity', 'Открытый интерес в NVDA', '#90aaff', ' NVDA')],
                          'Открытый интерес Binance. Слева — объём в NVDA, справа — номинал в млн USDT'),
        positioning_panel('nvda-short', 'NVDA · Short Interest', 'Nasdaq', NASDAQ, 'Дважды в месяц',
                          'nasdaq_nvda_short.json', short, [('shares', 'Акций в шорте', '#ef647a', '')],
                          'Количество акций NVDA в открытых коротких позициях на дату отчёта Nasdaq'),
    ]
    panels[1]['series'][1]['scale'] = 'left'
    return dict(id='nvidia', family='EQUITIES', title='NVIDIA · NVDA',
                note='Профиль объёма акции показывает, где торговалась NVIDIA. Позиции фьючерса NVDAUSDT на Binance показаны за последние 30 дней. Short Interest относится к самой акции.',
                columns=[dict(title='АКЦИИ · ЦЕНА И ПРОФИЛЬ ОБЪЁМА', panels=[price]),
                         dict(title='ПОЗИЦИОНИРОВАНИЕ', panels=panels)])
