"""Event dates for the market workspace from the issuing organizations."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit
from xml.etree import ElementTree

import sources

FED = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
NVDA_RSS = 'https://investor.nvidia.com/rss/pressrelease.aspx'
NVDA_HISTORY = [{
    'date': '2026-08-26', 'kind': 'nvda', 'title': 'Отчёт NVIDIA · Q2 FY2027',
    'url': 'https://investor.nvidia.com/files/content_files/TRANSCRIPT_-NVIDIA-Corp-NVDA-US-Q2-2027-Earnings-Call-26-August-2026-5_00-PM-ET.pdf',
    'afterClose': True,
}]


def event(date, kind, title, url, after_close=False):
    return dict(date=date.isoformat(), kind=kind, title=title, url=url, afterClose=after_close)


def fred_dates(text, release_id, kind, title):
    url = f'https://fred.stlouisfed.org/releases/calendar?rid={release_id}'
    return [event(dt.date.fromisoformat(row['date']), kind, title, url)
            for row in json.loads(text)['release_dates'] if row['release_id'] == release_id]


def fed_dates(text):
    month_names = 'january february march april may june july august september october november december'
    months = {name: n for n, name in enumerate(month_names.split(), start=1)}
    years = re.split(r'<h4>\s*<a[^>]*>(\d{4}) FOMC Meetings</a>', text)
    meetings = []
    for year, block in zip(years[1::2], years[2::2]):
        rows = re.findall(
            r'class="[^"]*\bfomc-meeting__month\b[^"]*"[^>]*>(.*?)</div>\s*'
            r'<div class="[^"]*\bfomc-meeting__date\b[^"]*"[^>]*>(.*?)</div>',
            block, re.S,
        )
        for month, days in rows:
            parts = re.findall(r'[A-Za-z]+', re.sub('<[^>]*>', '', html.unescape(month)))
            numbers = re.findall(r'\d+', re.sub('<[^>]*>', '', html.unescape(days)))
            if parts and numbers and parts[-1].lower() in months:
                date = dt.date(int(year), months[parts[-1].lower()], int(numbers[-1]))
                meetings.append(event(date, 'fed', 'Заседание FOMC', FED))
    return meetings


def nvidia_dates(text):
    results = []
    for item in ElementTree.fromstring(text).findall('./channel/item'):
        title = item.findtext('title', '')
        link = item.findtext('link', '')
        if 'Announces Financial Results for' not in title or urlsplit(link).netloc != 'investor.nvidia.com':
            continue
        stamp = parsedate_to_datetime(item.findtext('pubDate', ''))
        match = re.search(r'(First|Second|Third|Fourth) Quarter Fiscal (\d{4})', title)
        quarter = {'First': 1, 'Second': 2, 'Third': 3, 'Fourth': 4}
        label = f'Отчёт NVIDIA · Q{quarter[match[1]]} FY{match[2]}' if match else 'Отчёт NVIDIA'
        results.append(event(stamp.date(), 'nvda', label, link, stamp.hour >= 16))
    return results


def load(name, url, parse):
    cache = sources.RAW / f'events_{name}.json'
    cached = []
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            pass
    if sources.OFFLINE or not url or (cached and sources._fresh(cache)):
        return cached
    try:
        parsed = parse(sources._get(url, timeout=15, retries=1))
        if not parsed:
            return cached
        if name == 'nvda':
            parsed = list({row['date']: row for row in [*cached, *parsed]}.values())
        pending = cache.with_suffix('.tmp')
        pending.write_text(json.dumps(parsed, ensure_ascii=False), encoding='utf-8')
        pending.replace(cache)
        return parsed
    except (OSError, ValueError, RuntimeError, KeyError, ElementTree.ParseError) as exc:
        sources._log('CALENDAR', name, 'warning', f'Не обновлён календарь. {exc}')
        return cached


def build():
    today = dt.date.today()
    earliest = (today - dt.timedelta(days=400)).isoformat()
    rows = [*load('fed', FED, fed_dates), *NVDA_HISTORY, *load('nvda', NVDA_RSS, nvidia_dates)]
    key = sources.fred_key()
    for release, kind, title in [(10, 'cpi', 'Инфляция США · CPI'), (50, 'jobs', 'Рынок труда США · NFP')]:
        query = urlencode(dict(release_id=release, api_key=key, file_type='json', limit=26,
                               sort_order='desc', include_release_dates_with_no_data='true'))
        url = 'https://api.stlouisfed.org/fred/release/dates?' + query if key else ''
        rows.extend(load(kind, url, lambda text: fred_dates(text, release, kind, title)))
    unique = {(row['kind'], row['date']): row for row in rows if row['date'] >= earliest}
    return {'asof': today.isoformat(), 'events': sorted(unique.values(), key=lambda row: (row['date'], row['kind']))}
