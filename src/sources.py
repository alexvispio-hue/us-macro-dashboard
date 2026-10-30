# -*- coding: utf-8 -*-
"""Загрузка сырых рядов. Каждый источник кэшируется в data/raw/."""

from __future__ import annotations

import io
import os
import re
import sys
import time
import datetime as dt
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import requests

import config as C

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "*/*"})

# сколько часов кэш считается свежим
CACHE_HOURS = 6

DIAG: list[dict] = []

# ------------------------------------------------------- ключ FRED
def fred_key() -> str:
    """Ключ берём из переменной окружения или из файла fred_key.txt рядом с run.bat."""
    k = os.environ.get("FRED_API_KEY", "").strip()
    if k:
        return k
    f = ROOT / "fred_key.txt"
    if f.exists():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return ""


def _scrub(text: str) -> str:
    """Не даём ключу утечь в лог."""
    k = fred_key()
    t = str(text)
    if k:
        t = t.replace(k, "***")
    return re.sub(r"(api_key=)[^&\s]+", r"\1***", t)


def _log(kind: str, name: str, status: str, detail: str = "") -> None:
    detail = _scrub(detail)
    DIAG.append({"kind": kind, "name": name, "status": status, "detail": detail})
    mark = {"ok": "  ok  ", "cache": " cache", "fail": " FAIL ", "skip": " skip "}.get(status, status)
    print(f"[{mark}] {kind:6s} {name:16s} {detail}", flush=True)


# ------------------------------------------------- блокировка хоста
class HostBlocked(RuntimeError):
    """Хост не отвечает на сетевом уровне — дальше долбиться в него бессмысленно."""


NET_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.SSLError,
    requests.exceptions.ChunkedEncodingError,
)

HOST_FAILS: dict[str, int] = {}
DEAD_HOSTS: set[str] = set()
DEAD_AFTER = 6          # подряд неудачных попыток к хосту -> считаем его недоступным


def _fresh(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    age_h = (time.time() - path.stat().st_mtime) / 3600.0
    return age_h < CACHE_HOURS


def _save_bad(cache: Path, text: str) -> None:
    """Ответ, который не разобрался, кладём рядом для диагностики."""
    try:
        cache.with_name(cache.name + ".bad").write_text(text, encoding="utf-8")
    except Exception:                                         # noqa: BLE001
        pass


def _get(url: str, timeout: int = 60, retries: int = 3) -> str:
    """GET с ретраями. Если хост уже признан мёртвым — сразу выходим, не ждём таймаут."""
    if OFFLINE:
        raise HostBlocked('offline: нет данных в кэше')
    host = urlsplit(url).netloc
    if host in DEAD_HOSTS:
        raise HostBlocked(host)

    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=timeout)
            r.raise_for_status()
            HOST_FAILS[host] = 0
            return r.text
        except NET_ERRORS as e:
            last = e
            HOST_FAILS[host] = HOST_FAILS.get(host, 0) + 1
            if HOST_FAILS[host] >= DEAD_AFTER:
                DEAD_HOSTS.add(host)
                raise HostBlocked(host) from e
            time.sleep(1.5 * (attempt + 1))
        except requests.HTTPError:
            raise            # 4xx/5xx — не блокировка, ретраить нечего
    raise last if last else RuntimeError("не удалось получить " + host)


# --------------------------------------------------------------------- FRED

def _fred_url(series_id: str) -> str:
    """
    С ключом — официальный API на api.stlouisfed.org.
    Без ключа — CSV с сайта fred.stlouisfed.org.

    Это важно: в некоторых странах сайт fred.stlouisfed.org недоступен
    (соединение рвётся), а api.stlouisfed.org при этом работает. Если
    загрузка падает с ConnectionReset — заведи бесплатный ключ, см. README.
    """
    key = fred_key()
    if key:
        return (f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id={series_id}&api_key={key}&file_type=json"
                f"&observation_start={C.START_DATE}&limit=100000")
    return f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def _parse_fred(series_id: str, text: str) -> pd.Series:
    text = text.lstrip()
    if text.startswith("{"):                       # ответ официального API
        import json
        obs = json.loads(text)["observations"]
        idx = [o["date"] for o in obs]
        val = [None if o["value"] in (".", "") else float(o["value"]) for o in obs]
        s = pd.Series(val, index=pd.to_datetime(idx), dtype="float64")
    else:                                          # fredgraph.csv
        df = pd.read_csv(io.StringIO(text))
        date_col = df.columns[0]
        val_col = df.columns[1]
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        vals = pd.to_numeric(df[val_col].replace(".", pd.NA), errors="coerce")
        s = pd.Series(vals.values, index=df[date_col], dtype="float64")
    s = s[~s.index.isna()].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s.name = series_id
    return s.dropna()


def fetch_fred(series_id: str) -> pd.Series:
    cache = RAW / f"fred_{series_id}.csv"
    if _fresh(cache):
        try:
            s = _parse_fred(series_id, cache.read_text(encoding="utf-8", errors="replace"))
            _log("FRED", series_id, "cache", f"n={len(s)}")
            return s
        except Exception:                                     # noqa: BLE001
            pass          # битый кэш не должен ронять сборку — идём в сеть
    try:
        text = _get(_fred_url(series_id))
        try:
            s = _parse_fred(series_id, text)
        except Exception:                                     # noqa: BLE001
            _save_bad(cache, text)
            raise
        if len(s) == 0:
            raise ValueError("пустой ряд")
        cache.write_text(text, encoding="utf-8")
        _log("FRED", series_id, "ok", f"n={len(s)}  last={s.index[-1].date()} {s.iloc[-1]:,.4g}")
        return s
    except Exception as e:                                    # noqa: BLE001
        if cache.exists():
            try:
                s = _parse_fred(series_id, cache.read_text(encoding="utf-8"))
                _log("FRED", series_id, "cache", f"сеть упала, старый кэш n={len(s)}")
                return s
            except Exception:                                 # noqa: BLE001
                pass
        if isinstance(e, HostBlocked):
            _log("FRED", series_id, "skip", f"хост {e} недоступен")
        else:
            _log("FRED", series_id, "fail", f"{type(e).__name__}: {e}")
        return pd.Series(dtype="float64", name=series_id)


# -------------------------------------------------------------------- Yahoo

def _parse_yahoo(name: str, text: str) -> pd.Series:
    import json
    j = json.loads(text)
    res = j.get("chart", {}).get("result")
    if not res:
        raise ValueError(str(j.get("chart", {}).get("error")))
    r = res[0]
    ts = r.get("timestamp") or []
    closes = r["indicators"]["quote"][0].get("close") or []
    idx = pd.to_datetime([dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts])
    s = pd.Series(closes, index=idx, dtype="float64").dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s.name = name
    return s


def fetch_yahoo(name: str, symbol: str) -> pd.Series:
    cache = RAW / f"yahoo_{name}.json"
    if _fresh(cache):
        try:
            s = _parse_yahoo(name, cache.read_text(encoding="utf-8"))
            _log("YAHOO", name, "cache", f"n={len(s)}")
            return s
        except Exception:                                     # noqa: BLE001
            pass
    p1 = int(dt.datetime.fromisoformat(C.START_DATE).timestamp())
    p2 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol)}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit")
    try:
        text = _get(url)
        s = _parse_yahoo(name, text)
        if len(s) == 0:
            raise ValueError("пустой ряд")
        cache.write_text(text, encoding="utf-8")
        _log("YAHOO", name, "ok", f"{symbol}  n={len(s)}  last={s.index[-1].date()} {s.iloc[-1]:,.4g}")
        return s
    except Exception as e:                                    # noqa: BLE001
        if cache.exists():
            try:
                s = _parse_yahoo(name, cache.read_text(encoding="utf-8"))
                _log("YAHOO", name, "cache", f"сеть упала, старый кэш n={len(s)}")
                return s
            except Exception:                                 # noqa: BLE001
                pass
        alt = fetch_stooq(name)
        if len(alt):
            return alt
        if isinstance(e, HostBlocked):
            _log("YAHOO", name, "skip", f"хост {e} недоступен")
        else:
            _log("YAHOO", name, "fail", f"{symbol}: {type(e).__name__}: {e}")
        return pd.Series(dtype="float64", name=name)


# ------------------------------------------------------------------- Stooq

def fetch_stooq(name: str) -> pd.Series:
    """Запасной источник котировок. Покрывает не все тикеры (см. config.STOOQ)."""
    sym = C.STOOQ.get(name)
    if not sym:
        return pd.Series(dtype="float64", name=name)
    cache = RAW / f"stooq_{name}.csv"
    try:
        if _fresh(cache):
            text = cache.read_text(encoding="utf-8")
        else:
            text = _get(f"https://stooq.com/q/d/l/?s={requests.utils.quote(sym)}&i=d", timeout=45)
            if "Date,Open" not in text:
                raise ValueError("stooq вернул не CSV")
            cache.write_text(text, encoding="utf-8")
        df = pd.read_csv(io.StringIO(text))
        s = pd.Series(pd.to_numeric(df["Close"], errors="coerce").values,
                      index=pd.to_datetime(df["Date"]), dtype="float64").dropna().sort_index()
        s.name = name
        _log("STOOQ", name, "ok", f"{sym}  n={len(s)}  (Yahoo не ответил)")
        return s
    except Exception as e:                                    # noqa: BLE001
        _log("STOOQ", name, "fail", f"{sym}: {type(e).__name__}: {e}")
        return pd.Series(dtype="float64", name=name)


# ---------------------------------------------------------------- Japan JGB

def _parse_jgb(text: str) -> pd.DataFrame:
    """CSV Минфина Японии. Шапка занимает 2 строки, даты в формате S/H/R (эры)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    head_i = next(i for i, ln in enumerate(lines) if ln.split(",")[0].strip().lower() == "date")
    df = pd.read_csv(io.StringIO("\n".join(lines[head_i:])))
    df.columns = [c.strip() for c in df.columns]

    def conv(v):
        """Минфин отдаёт даты двух видов: '2026/9/1' и японские эры 'S49.9.24'."""
        v = str(v).strip()
        if not v:
            return pd.NaT
        if v[0].isdigit():                       # 2026/9/1 или 2026-09-01
            return pd.to_datetime(v, errors="coerce")
        try:                                     # S=Сёва, H=Хэйсэй, R=Рэйва
            base = {"S": 1925, "H": 1988, "R": 2018}[v[0].upper()]
            y, m, d = (int(x) for x in v[1:].split("."))
            return pd.Timestamp(base + y, m, d)
        except Exception:                                     # noqa: BLE001
            return pd.to_datetime(v, errors="coerce")

    df["date"] = df[df.columns[0]].map(conv)
    df = df[~df["date"].isna()].set_index("date")
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_index()


def fetch_jgb30() -> pd.Series:
    """Доходность 30-летних JGB, %."""
    frames = []
    for tag, url in (("hist", C.JGB_HISTORY_URL), ("cur", C.JGB_CURRENT_URL)):
        cache = RAW / f"jgb_{tag}.csv"
        text = None
        if _fresh(cache):
            text = cache.read_text(encoding="utf-8", errors="replace")
        else:
            try:
                text = _get(url, timeout=60)
                cache.write_text(text, encoding="utf-8")
            except Exception as e:                            # noqa: BLE001
                if cache.exists():
                    text = cache.read_text(encoding="utf-8", errors="replace")
                else:
                    _log("JGB", tag, "fail", f"{type(e).__name__}: {e}")
                    continue
        try:
            frames.append(_parse_jgb(text))
        except Exception as e:                                # noqa: BLE001
            _log("JGB", tag, "fail", f"разбор CSV: {type(e).__name__}: {e}")

    if not frames:
        return pd.Series(dtype="float64", name="JP30Y")

    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    col = next((c for c in df.columns if c.strip().upper() in ("30", "30Y")), None)
    if col is None:
        _log("JGB", "30Y", "fail", f"нет колонки 30Y, есть: {list(df.columns)[:18]}")
        return pd.Series(dtype="float64", name="JP30Y")
    s = df[col].dropna()
    s = s[~s.index.duplicated(keep="last")]
    s.name = "JP30Y"
    if len(s) == 0:
        _log("JGB", "30Y", "fail", f"колонка {col} есть, но числовых значений в ней нет")
        return pd.Series(dtype="float64", name="JP30Y")
    _log("JGB", "30Y", "ok", f"n={len(s)}  last={s.index[-1].date()} {s.iloc[-1]:,.3f}")
    return s


# ---------------------------------------------------------------- DBnomics
#
# Агрегатор открытой статистики (ЕЦБ, Банк Японии, МВФ, ОЭСР и прочие).
# Нужен там, где FRED бросил ряд, а первоисточник недоступен напрямую:
# data-api.ecb.europa.eu, например, отвечает не из любой сети, а DBnomics да.

def _parse_dbnomics(name: str, text: str) -> pd.Series:
    import json
    j = json.loads(text)
    docs = (j.get("series") or {}).get("docs") or []
    if not docs:
        errs = j.get("errors") or []
        raise ValueError(f"серия не найдена{': ' + str(errs)[:120] if errs else ''}")
    d = docs[0]
    periods = d.get("period") or []
    values = d.get("value") or []
    idx, vals = [], []
    for p, v in zip(periods, values):
        if not isinstance(v, (int, float)):
            continue                        # DBnomics ставит 'NA' строкой
        idx.append(p)
        vals.append(float(v))
    s = pd.Series(vals, index=pd.to_datetime(idx, errors="coerce"), dtype="float64")
    s = s[~s.index.isna()].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s.name = name
    return s.dropna()


def fetch_dbnomics(name: str, spec: dict) -> pd.Series:
    cache = RAW / f"dbnomics_{name}.json"
    url = (f"https://api.db.nomics.world/v22/series/"
           f"{spec['provider']}/{spec['dataset']}/{spec['code']}?observations=1")
    try:
        if _fresh(cache):
            s = _parse_dbnomics(name, cache.read_text(encoding="utf-8"))
            _log("DBNOM", name, "cache", f"n={len(s)}")
            return s
        text = _get(url)
        try:
            s = _parse_dbnomics(name, text)
        except Exception:                                     # noqa: BLE001
            _save_bad(cache, text)      # мусор кладём в .bad, кэш не трогаем
            raise
        if len(s) == 0:
            _save_bad(cache, text)
            raise ValueError("пустой ряд")
        cache.write_text(text, encoding="utf-8")   # кэш — только после успешного разбора
        _log("DBNOM", name, "ok",
             f"{spec['provider']}/{spec['dataset']}  n={len(s)}  "
             f"last={s.index[-1].date()} {s.iloc[-1]:,.6g}")
        return s
    except Exception as e:                                    # noqa: BLE001
        if cache.exists():
            try:
                s = _parse_dbnomics(name, cache.read_text(encoding="utf-8"))
                _log("DBNOM", name, "cache", f"сеть упала, старый кэш n={len(s)}")
                return s
            except Exception:                                 # noqa: BLE001
                pass
        if isinstance(e, HostBlocked):
            _log("DBNOM", name, "skip", f"хост {e} недоступен")
        else:
            _log("DBNOM", name, "fail", f"{type(e).__name__}: {e}")
        return pd.Series(dtype="float64", name=name)


# ------------------------------------------------------------ Банк Англии
#
# Публичная выгрузка из их базы IADB. LPMAUYM — денежный агрегат M4,
# месячные остатки, миллионы фунтов. Отдаёт готовый CSV: DATE,LPMAUYM
# с датами вида "31 Jul 2026".

def _parse_boe(name: str, text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    if df.shape[1] < 2:
        raise ValueError(f"ожидал две колонки, получил {list(df.columns)}")
    dates = pd.to_datetime(df[df.columns[0]], format="%d %b %Y", errors="coerce")
    if dates.isna().all():
        dates = pd.to_datetime(df[df.columns[0]], errors="coerce", dayfirst=True)
    vals = pd.to_numeric(df[df.columns[1]], errors="coerce")
    keep = ~dates.isna()
    s = pd.Series(vals[keep].values, index=dates[keep], dtype="float64").dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s.name = name
    return s


def fetch_boe(name: str, spec: dict) -> pd.Series:
    cache = RAW / f"boe_{name}.csv"
    url = ("https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp"
           f"?csv.x=yes&Datefrom=01/Jan/{C.START_DATE[:4]}&Dateto=now"
           f"&SeriesCodes={spec['code']}&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
    try:
        if _fresh(cache):
            s = _parse_boe(name, cache.read_text(encoding="utf-8"))
            _log("BOE", name, "cache", f"n={len(s)}")
            return s
        text = _get(url)
        try:
            s = _parse_boe(name, text)
        except Exception:                                     # noqa: BLE001
            _save_bad(cache, text)      # мусор кладём в .bad, кэш не трогаем
            raise
        if len(s) == 0:
            _save_bad(cache, text)
            raise ValueError("пустой ряд")
        cache.write_text(text, encoding="utf-8")   # кэш — только после успешного разбора
        _log("BOE", name, "ok", f"{spec['code']}  n={len(s)}  last={s.index[-1].date()} {s.iloc[-1]:,.6g}")
        return s
    except Exception as e:                                    # noqa: BLE001
        if cache.exists():
            try:
                s = _parse_boe(name, cache.read_text(encoding="utf-8"))
                _log("BOE", name, "cache", f"сеть упала, старый кэш n={len(s)}")
                return s
            except Exception:                                 # noqa: BLE001
                pass
        _log("BOE", name, "skip" if isinstance(e, HostBlocked) else "fail",
             f"{type(e).__name__}: {e}")
        return pd.Series(dtype="float64", name=name)


# ------------------------------------------------------------ Банк Японии
#
# Страница месячной денежной массы. Таблица широкая: сначала колонки с
# годовыми приростами в процентах, потом сами уровни в 100 млн иен.
# Колонку ищем по заголовку, а не по номеру: и "M2/Percent changes...",
# и "M2/Average amounts outstanding..." начинаются одинаково, поэтому
# процентные колонки отсеиваем явно.

_TAG = re.compile(r"<[^>]+>")
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S | re.I)
_DATE_CELL = re.compile(r"^(\d{4})/(\d{1,2})$")


def _cells(row_html: str) -> list[str]:
    out = []
    for c in _CELL.findall(row_html):
        out.append(re.sub(r"\s+", " ", _TAG.sub(" ", c)).replace("\xa0", " ").strip())
    return out


def _parse_boj(name: str, html: str, item: str) -> pd.Series:
    rows = _ROW.findall(html)
    header, col = None, None
    for row in rows:
        cs = _cells(row)
        if any(c.lower().startswith("name of time-series") for c in cs):
            header = cs
            break
    if header:
        for i, h in enumerate(header):
            if h.startswith(item + "/") and "percent change" not in h.lower():
                col = i
                break
    if col is None:
        raise ValueError(f"не нашёл колонку уровней для {item}; "
                         f"заголовок: {header[:6] if header else 'не найден'}")

    idx, vals = [], []
    for row in rows:
        cs = _cells(row)
        if not cs or not _DATE_CELL.match(cs[0]) or col >= len(cs):
            continue
        raw = cs[col].replace(",", "").replace(" ", "")
        if not raw or raw in ("-", "--", "NA"):
            continue
        try:
            v = float(raw)
        except ValueError:
            continue
        idx.append(pd.Timestamp(int(cs[0][:4]), int(cs[0][5:]), 1))
        vals.append(v)
    s = pd.Series(vals, index=pd.DatetimeIndex(idx), dtype="float64").sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s.name = name
    return s


def fetch_boj(name: str, spec: dict) -> pd.Series:
    cache = RAW / f"boj_{name}.html"
    try:
        if _fresh(cache):
            s = _parse_boj(name, cache.read_text(encoding="utf-8", errors="replace"), spec["item"])
            _log("BOJ", name, "cache", f"n={len(s)}")
            return s
        text = _get(spec["url"])
        try:
            s = _parse_boj(name, text, spec["item"])
        except Exception:                                     # noqa: BLE001
            _save_bad(cache, text)      # мусор кладём в .bad, кэш не трогаем
            raise
        if len(s) == 0:
            _save_bad(cache, text)
            raise ValueError("пустой ряд")
        cache.write_text(text, encoding="utf-8")   # кэш — только после успешного разбора
        _log("BOJ", name, "ok",
             f"{spec['item']}  n={len(s)}  last={s.index[-1].date()} {s.iloc[-1]:,.6g}")
        return s
    except Exception as e:                                    # noqa: BLE001
        if cache.exists():
            try:
                s = _parse_boj(name, cache.read_text(encoding="utf-8", errors="replace"), spec["item"])
                _log("BOJ", name, "cache", f"сеть упала, старый кэш n={len(s)}")
                return s
            except Exception:                                 # noqa: BLE001
                pass
        _log("BOJ", name, "skip" if isinstance(e, HostBlocked) else "fail",
             f"{type(e).__name__}: {e}")
        return pd.Series(dtype="float64", name=name)


# ----------------------------------------------------------------- Китай
#
# Первоисточники по Китаю недоступны: Госстат КНР (data.stats.gov.cn) отдаёт
# 403 и скрипту, и настоящему браузеру — режут по региону, а не ботов.
# Поэтому берём зеркало: финансовый портал East Money публикует сводку
# денежной массы НБК своим же JSON-эндпоинтом, без ключа.
#
# Поля отчёта RPT_ECONOMY_CURRENCY_SUPPLY, всё в 亿元 (100 млн юаней):
#   BASIC_CURRENCY — M2 (货币和准货币)
#   CURRENCY       — M1
#   FREE_CASH      — M0
# Суффикс _SAME — прирост год к году, _SEQUENTIAL — к прошлому месяцу.
#
# Это посредник, а не первоисточник: если он сменит формат или уйдёт,
# компонент просто выпадет из суммы и будет подписан под панелью.

def _parse_eastmoney(name: str, text: str, field: str) -> pd.Series:
    import json
    j = json.loads(text)
    if not j.get("success", True):
        raise ValueError(f"портал ответил: {j.get('message')}")
    rows = (j.get("result") or {}).get("data") or []
    if not rows:
        raise ValueError("пустой ответ")
    if field not in rows[0]:
        raise ValueError(f"нет поля {field}; есть: {sorted(rows[0])[:10]}")
    idx, vals = [], []
    for r in rows:
        v = r.get(field)
        d = pd.to_datetime(str(r.get("REPORT_DATE", ""))[:10], errors="coerce")
        if v is None or pd.isna(d):
            continue
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            continue
        idx.append(d)
    s = pd.Series(vals, index=pd.DatetimeIndex(idx), dtype="float64").sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s.name = name
    return s


def fetch_eastmoney(name: str, spec: dict) -> pd.Series:
    cache = RAW / f"eastmoney_{name}.json"
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           f"?reportName={spec['report']}&columns=ALL&pageNumber=1&pageSize=2000"
           "&sortColumns=REPORT_DATE&sortTypes=-1")
    try:
        if _fresh(cache):
            s = _parse_eastmoney(name, cache.read_text(encoding="utf-8"), spec["field"])
            _log("EASTM", name, "cache", f"n={len(s)}")
            return s
        text = _get(url)
        try:
            s = _parse_eastmoney(name, text, spec["field"])
        except Exception:                                     # noqa: BLE001
            _save_bad(cache, text)      # мусор кладём в .bad, кэш не трогаем
            raise
        if len(s) == 0:
            _save_bad(cache, text)
            raise ValueError("пустой ряд")
        cache.write_text(text, encoding="utf-8")   # кэш — только после успешного разбора
        _log("EASTM", name, "ok",
             f"{spec['field']}  n={len(s)}  last={s.index[-1].date()} {s.iloc[-1]:,.6g}")
        return s
    except Exception as e:                                    # noqa: BLE001
        if cache.exists():
            try:
                s = _parse_eastmoney(name, cache.read_text(encoding="utf-8"), spec["field"])
                _log("EASTM", name, "cache", f"сеть упала, старый кэш n={len(s)}")
                return s
            except Exception:                                 # noqa: BLE001
                pass
        _log("EASTM", name, "skip" if isinstance(e, HostBlocked) else "fail",
             f"{type(e).__name__}: {e}")
        return pd.Series(dtype="float64", name=name)


# ------------------------------------------------------- метаданные FRED

META: dict[str, dict] = {}
_UNIT_WORDS = (
    ("trillion", 1e3),
    ("billion", 1.0),
    ("100 million", 1e-1),
    ("hundred million", 1e-1),
    ("million", 1e-3),
    ("thousand", 1e-6),
)


# Строки, которые означают "просто единицы валюты, без приставки".
_BARE_CURRENCY = ("national currency", "yen", "yuan", "euro", "dollar",
                  "pound", "sterling", "renminbi", "currency units")


def units_to_billions(units: str):
    """
    Множитель, приводящий ряд к миллиардам его валюты, или None если не понял.

    'Millions of U.S. Dollars' -> 1e-3, 'Billions of Dollars' -> 1,
    '100 Millions of Yen' -> 0.1, 'Yen' / 'National Currency' -> 1e-9.

    None вместо догадки принципиален: раньше любая незнакомая строка
    ('Index 2015=100', пустая) молча давала 1e-9, компонент схлопывался
    почти в ноль, оставался "свежим и непустым" и тихо выпадал из суммы.
    """
    u = (units or "").lower()
    for word, factor in _UNIT_WORDS:
        if word in u:
            return factor
    if any(w in u for w in _BARE_CURRENCY):
        return 1e-9
    return None


OFFLINE = False          # --offline: не ходить в сеть даже за метаданными


def fetch_fred_meta(series_id: str) -> dict:
    """Карточка ряда: единицы, заголовок, дата последнего наблюдения."""
    key = fred_key()
    if not key:
        return {}
    cache = RAW / f"meta_{series_id}.json"
    text = None
    if cache.exists() and (time.time() - cache.stat().st_mtime) / 86400 < 7:
        text = cache.read_text(encoding="utf-8")
    elif OFFLINE:
        return {}
    else:
        try:
            text = _get(f"https://api.stlouisfed.org/fred/series"
                        f"?series_id={series_id}&api_key={key}&file_type=json")
            cache.write_text(text, encoding="utf-8")
        except Exception:                                     # noqa: BLE001
            if cache.exists():
                text = cache.read_text(encoding="utf-8")
    if not text:
        return {}
    try:
        import json
        s = json.loads(text)["seriess"][0]
        return {"units": s.get("units", ""), "title": s.get("title", ""),
                "end": s.get("observation_end", "")}
    except Exception:                                         # noqa: BLE001
        return {}


_SCALE_WARNED: set[str] = set()


def money_scale(series_id: str) -> tuple[float, str]:
    """Множитель до миллиардов и пояснение, откуда он взялся."""
    units = META.get(series_id, {}).get("units", "")
    if units:
        f = units_to_billions(units)
        if f is not None:
            return f, units
        if series_id not in _SCALE_WARNED:                    # шумим ровно один раз
            _SCALE_WARNED.add(series_id)
            _log("UNITS", series_id, "fail",
                 f"не понял единицы {units!r} — беру запасной множитель из config")
    return C.UNIT_SCALE.get(series_id, 1.0), f"запасной множитель из config ({units or 'единицы неизвестны'})"


# ------------------------------------------------- файлы, скачанные вручную

_MANUAL: dict[str, pd.Series] | None = None


def manual_series() -> dict[str, pd.Series]:
    """
    Ряды из CSV, положенных руками в data/manual/.

    Пригодится, если FRED недоступен и нет ключа: на fred.stlouisfed.org можно
    выгрузить хоть все ряды разом через
        fredgraph.csv?id=DFF,DTB3,DGS2,...
    и бросить файл сюда. Формат: первая колонка — дата, остальные — ряды,
    имя ряда берётся из заголовка колонки.
    """
    global _MANUAL                                            # noqa: PLW0603
    if _MANUAL is not None:
        return _MANUAL

    out: dict[str, pd.Series] = {}
    d = ROOT / "data" / "manual"
    if d.exists():
        for f in sorted(d.glob("*.csv")):
            try:
                df = pd.read_csv(f)
                if df.shape[1] < 2:
                    continue
                dates = pd.to_datetime(df[df.columns[0]], errors="coerce")
                keep = ~dates.isna()
                for col in df.columns[1:]:
                    vals = pd.to_numeric(df[col].replace(".", pd.NA), errors="coerce")
                    s = pd.Series(vals[keep].values, index=dates[keep], dtype="float64")
                    s = s.dropna().sort_index()
                    s = s[~s.index.duplicated(keep="last")]
                    if len(s):
                        s.name = col.strip()
                        out[col.strip()] = s
            except Exception as e:                            # noqa: BLE001
                _log("MANUAL", f.name, "fail", f"{type(e).__name__}: {e}")
    if out:
        names = ", ".join(list(out)[:8]) + ("…" if len(out) > 8 else "")
        _log("MANUAL", "data/manual", "ok", f"рядов в файлах: {len(out)} ({names})")
    _MANUAL = out
    return out


# ------------------------------------------------------------------ фасад

def fetch_all(only: set[str] | None = None) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    man = manual_series()
    for sid in C.FRED:
        if only and sid not in only:
            continue
        s = fetch_fred(sid)
        if len(s) == 0 and sid in man:            # сеть не дала — берём из файла
            s = man[sid]
            _log("MANUAL", sid, "ok", f"из файла n={len(s)}  last={s.index[-1].date()}")
        out[sid] = s
        if sid in C.MONEY_SERIES and len(s):
            META[sid] = fetch_fred_meta(sid)

    for name, spec in C.DBNOMICS.items():
        if only and name not in only:
            continue
        s = fetch_dbnomics(name, spec)
        if len(s) == 0 and name in man:
            s = man[name]
            _log("MANUAL", name, "ok", f"из файла n={len(s)}  last={s.index[-1].date()}")
        out[name] = s
        META[name] = {"units": spec.get("units", ""), "title": spec.get("desc", "")}

    for name, spec in C.DIRECT.items():
        if only and name not in only:
            continue
        fetcher = {"boe": fetch_boe, "boj": fetch_boj, "eastmoney": fetch_eastmoney}[spec["kind"]]
        s = fetcher(name, spec)
        if len(s) == 0 and name in man:
            s = man[name]
            _log("MANUAL", name, "ok", f"из файла n={len(s)}  last={s.index[-1].date()}")
        out[name] = s
        META[name] = {"units": spec.get("units", ""), "title": spec.get("desc", "")}
    for name, sym in C.YAHOO.items():
        if only and name not in only:
            continue
        out[name] = fetch_yahoo(name, sym)
    if not only or "JP30Y" in only:
        out["JP30Y"] = fetch_jgb30()
    return out
