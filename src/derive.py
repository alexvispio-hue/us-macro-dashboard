# -*- coding: utf-8 -*-
"""Производные ряды и сборка описания панелей дашборда."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd

import config as C
import sources

DISPLAY_START = "2018-01-01"   # с какой даты рисуем (история грузится глубже, для z-score)

# ------------------------------------------------------------- утилиты


def daily(s: pd.Series) -> pd.Series:
    """Приводит любой ряд к дневной сетке рабочих дней с протяжкой вперёд."""
    if s is None or len(s) == 0:
        return pd.Series(dtype="float64")
    idx = pd.date_range(s.index.min(), max(s.index.max(), pd.Timestamp.today().normalize()), freq="B")
    return s.reindex(s.index.union(idx)).ffill().reindex(idx)


def align(*series: pd.Series) -> list[pd.Series]:
    series = [s if s is not None else pd.Series(dtype="float64") for s in series]
    ds = [daily(s) for s in series]
    ds = [d for d in ds if len(d)]
    if not ds:
        return [pd.Series(dtype="float64") for _ in series]
    idx = ds[0].index
    for d in ds[1:]:
        idx = idx.intersection(d.index)
    return [daily(s).reindex(idx) if len(s) else pd.Series(index=idx, dtype="float64") for s in series]


def z(s: pd.Series, win: int = C.Z_WINDOW_DAYS) -> pd.Series:
    if len(s) == 0:
        return s
    m = s.rolling(win, min_periods=max(60, win // 8)).mean()
    sd = s.rolling(win, min_periods=max(60, win // 8)).std()
    return (s - m) / sd.replace(0, np.nan)


def yoy(s: pd.Series, periods: int) -> pd.Series:
    """Изменение к значению `periods` наблюдений назад, в %."""
    if len(s) == 0:
        return s
    return (s / s.shift(periods) - 1.0) * 100.0


def to_points(s: pd.Series, start: str = DISPLAY_START, decimals: int = 4) -> list[dict]:
    if s is None or len(s) == 0:
        return []
    s = s[s.index >= pd.Timestamp(start)].dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    out = []
    for t, v in s.items():
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            continue
        out.append({"time": t.strftime("%Y-%m-%d"), "value": round(float(v), decimals)})
    return out


def last_val(s: pd.Series):
    s = s.dropna() if s is not None else None
    return None if s is None or len(s) == 0 else float(s.iloc[-1])


def fmt(v, digits: int = 2, suffix: str = "") -> str:
    """
    Число с точностью по величине, а не по фиксированной настройке панели.

    Фиксированная точность подводит на рядах с огромным размахом: у обратного
    репо исторический максимум 2554 млрд, а сейчас 0.7 млрд — при точности 0
    живое значение округлялось до нуля и выглядело как отсутствие данных.
    Та же логика продублирована в fmtNum() на странице, чтобы подписи на осях
    и в шапке панели совпадали.
    """
    if v is None:
        return "н/д"
    a = abs(v)
    if a >= 10000:
        return f"{v:,.0f}{suffix}".replace(",", " ")
    if a >= 1000:
        return f"{v:.0f}{suffix}"
    if a >= 100:
        return f"{v:.1f}{suffix}"
    if a >= 1:
        return f"{v:.2f}{suffix}"
    if a > 0:
        return f"{v:.3f}{suffix}"
    return f"0{suffix}"


# --------------------------------------------------- композиты (M2, балансы ЦБ)


def _scaled(raw: dict, sid: str) -> pd.Series:
    """Ряд, приведённый к миллиардам своей валюты. Множитель — из метаданных FRED."""
    s = raw.get(sid, pd.Series(dtype="float64"))
    if len(s) == 0:
        return s
    factor, _ = sources.money_scale(sid)
    return s * factor


def asof(s: pd.Series):
    """Дата последнего НАСТОЯЩЕГО наблюдения — до всякой протяжки вперёд."""
    if s is None or len(s) == 0:
        return None
    s = s.dropna()
    return None if len(s) == 0 else s.index[-1]


def cadence_days(s: pd.Series) -> float:
    """Типичный шаг между наблюдениями. Нужен, чтобы отличать норму от заморозки."""
    if s is None or len(s.dropna()) < 8:
        return 1.0
    d = pd.Series(s.dropna().index).diff().dt.days.dropna()
    return float(d.median()) if len(d) else 1.0


def is_stale(s: pd.Series, stamp=None) -> bool:
    """
    Ряд отстал сильнее, чем позволяет его собственная частота.

    Порог считаем от данных, а не константой: месячный ряд с лагом в месяц —
    это норма публикации, а дневной с таким же лагом — авария. Единый порог
    пометил бы половину дашборда «устаревшим» и обесценил бы саму пометку.
    """
    stamp = stamp if stamp is not None else asof(s)
    if stamp is None:
        return False
    lag = (pd.Timestamp.today().normalize() - stamp).days
    return lag > max(8.0, 3.0 * cadence_days(s))


def clamp_future(s: pd.Series) -> pd.Series:
    """
    Подрезает последний узел, если resample увёл его в будущее.

    resample метит узел концом периода: сентябрьское наблюдение получает дату
    30 сентября. Значение верное, но подпись «на 2026-09-30» врёт, а страница
    считает эту дату самой свежей во всём наборе — и окна 1Д и 1Н уезжают
    в пустоту после последних данных.
    """
    if s is None or len(s) == 0:
        return s
    today = pd.Timestamp.today().normalize()
    if s.index[-1] > today:
        s = s.copy()
        s.index = s.index[:-1].append(pd.DatetimeIndex([today]))
    return s


def on_grid(s: pd.Series, freq: str) -> pd.Series:
    """
    Ряд на сетке `freq`, значение в узле — последнее НАБЛЮДЁННОЕ до этого узла.

    Нужно, чтобы складывать ряды разной частоты, не смешивая «винтажи»:
    остатки денежной массы одни страны датируют началом месяца, другие концом,
    и без общей сетки сумма полмесяца складывала свежие данные по одним
    странам со старыми по другим.
    """
    s = s.dropna() if s is not None else pd.Series(dtype="float64")
    if len(s) == 0:
        return s
    return clamp_future(s.resample(freq).last().ffill())


def fx_on_grid(fx: pd.Series, idx: pd.DatetimeIndex, freq: str) -> pd.Series:
    """Курс, снятый на те же узлы сетки, что и сам запас."""
    f = on_grid(fx, freq)
    return f.reindex(f.index.union(idx)).ffill().reindex(idx) if len(f) else pd.Series(index=idx, dtype="float64")


def _compose(parts: dict) -> tuple[pd.Series, dict, list[str]]:
    """
    Складывает компоненты, выбрасывая пустые и протухшие.

    parts: {имя: (ряд в млрд USD, дата последнего настоящего наблюдения)}

    Дату свежести берём у ИСХОДНОГО ряда, а не у протянутого. daily() дотягивает
    последнее значение до сегодняшнего дня, и по нему любой замороженный ряд
    выглядит свежим — ровно на этом отбраковка один раз и не сработала.

    Замороженный компонент опаснее отсутствующего: сумма выглядит правдоподобно,
    но перестаёт двигаться.
    """
    used, dropped = {}, []
    today = pd.Timestamp.today().normalize()
    for name, (s, stamp) in parts.items():
        s = s.dropna() if s is not None else pd.Series(dtype="float64")
        if len(s) == 0 or stamp is None:
            dropped.append(f"{name}: нет данных")
        elif (today - stamp).days > C.STALE_DAYS:
            dropped.append(f"{name}: заморожен на {stamp.date()}")
        else:
            used[name] = s
    if not used:
        return pd.Series(dtype="float64"), {}, dropped
    # sort=True обязателен: компоненты стартуют в разные даты, и без сортировки
    # ffill() протянет значения по перепутанному порядку индекса.
    df = pd.concat(used, axis=1, sort=True).ffill().dropna(how="all")
    return df.sum(axis=1, min_count=1) / 1000.0, used, dropped      # млрд -> трлн


M2_FREQ = "ME"          # месячная сетка, узел — конец месяца


def global_m2_usd(raw: dict) -> tuple[pd.Series, dict, list[str]]:
    """
    Широкие деньги крупнейших экономик в долларах.

    Две вещи, которые здесь сделаны намеренно.

    Во-первых, все пять компонентов приводятся к КОНЦУ МЕСЯЦА. FRED, ЕЦБ,
    Банк Японии и East Money датируют остатки началом месяца, Банк Англии —
    концом. На дневной сетке с протяжкой вперёд сумма почти весь месяц
    складывала июльские данные по четырём странам с июньскими по пятой.

    Во-вторых, курс берётся на тот же узел сетки, а не дневной. Запас —
    величина на дату; умножая месячный запас на дневной курс, получаешь
    панель, которая внутри месяца движется исключительно от валютного рынка,
    хотя подписана как денежная масса.
    """
    def part(sid, fx_id=None, divide=False):
        s = on_grid(_scaled(raw, sid), M2_FREQ)
        if fx_id and len(s):
            f = fx_on_grid(raw.get(fx_id, pd.Series(dtype="float64")), s.index, M2_FREQ)
            s = s / f.replace(0, np.nan) if divide else s * f
        return s, asof(raw.get(sid))

    return _compose({
        "US": part(C.M2_US),
        "EU": part(C.M2_EU, "DEXUSEU"),                  # USD за 1 EUR
        "JP": part(C.M2_JP, "DEXJPUS", divide=True),     # JPY за 1 USD
        "CN": part(C.M2_CN, "DEXCHUS", divide=True),     # CNY за 1 USD
        "UK": part(C.M2_UK, "DEXUSUK"),                  # USD за 1 GBP
    })


CB_FREQ = "W-WED"       # ФРС и ЕЦБ публикуют балансы по средам


def cb_balance_usd(raw: dict) -> tuple[pd.Series, dict, list[str]]:
    """
    Балансы ФРС + ЕЦБ + Банка Японии в долларах, недельная сетка по средам.

    Дневная сетка тут была лишней: ФРС и ЕЦБ отчитываются раз в неделю,
    Банк Японии раз в месяц. Протяжка до дня не добавляла информации, зато
    умножала месячный японский баланс на дневную иену — и панель дёргалась
    от курса между публикациями.
    """
    def part(sid, fx_id=None, divide=False):
        s = on_grid(_scaled(raw, sid), CB_FREQ)
        if fx_id and len(s):
            f = fx_on_grid(raw.get(fx_id, pd.Series(dtype="float64")), s.index, CB_FREQ)
            s = s / f.replace(0, np.nan) if divide else s * f
        return s, asof(raw.get(sid))

    return _compose({
        "FED": part("WALCL"),
        "ECB": part("ECBASSETSW", "DEXUSEU"),
        "BOJ": part("JPNASSETS", "DEXJPUS", divide=True),
    })


def net_fed_liquidity(raw: dict) -> pd.Series:
    """
    Чистая ликвидность ФРС = активы - счёт Минфина - обратное репо, млрд USD.

    И никакого fillna(0). Если счёт Минфина не загрузился, ноль вместо
    него завысит ликвидность примерно на 800 млрд и попадёт ровно в тот
    диапазон, который README объявляет нормальным, — то есть соврёт незаметно.
    Лучше пустая панель, чем правдоподобная неправда.
    """
    for sid in ("WALCL", "WTREGEN", "RRPONTSYD"):
        s = raw.get(sid)
        if s is None or len(s.dropna()) == 0:
            return pd.Series(dtype="float64")
    # Считаем по средам. Активы и счёт Минфина выходят раз в неделю, репо —
    # ежедневно; на дневной сетке два слагаемых из трёх стояли на месте
    # до недели, а третье двигалось, и разность давала пилу на пустом месте.
    # В 2021-2022, когда репо ходило на сотни миллиардов в день, это было бы
    # хорошо заметно.
    parts = {k: on_grid(_scaled(raw, k), CB_FREQ)
             for k in ("WALCL", "WTREGEN", "RRPONTSYD")}
    df = pd.concat(parts, axis=1, sort=True).ffill().dropna()
    if len(df) == 0:
        return pd.Series(dtype="float64")
    return df["WALCL"] - df["WTREGEN"] - df["RRPONTSYD"]


STRESS_PARTS = {"VIXCLS": "VIX", "MOVE": "MOVE", "BAMLH0A0HYM2": "HY OAS",
                "NFCI": "NFCI", "STLFSI4": "STLFSI"}


def stress_composite(raw: dict) -> tuple[pd.Series, list[str], list[str]]:
    """
    Композитный индекс стресса: средний z-score по доступным метрикам.

    Возврат: (ряд, вошедшие, выброшенные). Раньше подпись под панелью всегда
    перечисляла все пять метрик, даже если MOVE не загрузился, — а он падает
    регулярно, запасного источника у него нет. Хуже другое: замороженный
    компонент daily() протягивал вперёд, скользящее среднее продолжало ехать,
    и мёртвый ряд давал дрейфующий z-score, тянувший весь индекс.
    """
    comps, used, dropped = [], [], []
    today = pd.Timestamp.today().normalize()
    for sid, label in STRESS_PARTS.items():
        s = raw.get(sid, pd.Series(dtype="float64"))
        if (s is None or len(s) == 0) and sid == "VIXCLS":
            s = raw.get("VIX", pd.Series(dtype="float64"))
        stamp = asof(s)
        if stamp is None:
            dropped.append(f"{label}: нет данных")
            continue
        if (today - stamp).days > C.STALE_DAYS:
            dropped.append(f"{label}: заморожен на {stamp.date()}")
            continue
        comps.append(z(daily(s)))
        used.append(label)
    if not comps:
        return pd.Series(dtype="float64"), used, dropped
    df = pd.concat(comps, axis=1, sort=True)
    return df.mean(axis=1, skipna=True).dropna(), used, dropped


def fed_stance(raw: dict) -> pd.Series:
    """Ставка ФРС минус доходность 2-летки.

    > 0 — ставка выше того, что закладывает рынок: жёсткая политика (заложены снижения)
    < 0 — мягкая политика (заложены повышения)
    """
    ffr, y2 = align(raw.get("DFF"), raw.get("DGS2"))
    if len(ffr) == 0:
        return pd.Series(dtype="float64")
    return (ffr - y2).dropna()


def real_spx_yoy(raw: dict, normalize: bool = True) -> pd.Series:
    """Реальная годовая доходность SPX: номинальный YoY минус инфляция YoY."""
    spx = raw.get("SPX", pd.Series(dtype="float64"))
    cpi = raw.get("CPIAUCSL", pd.Series(dtype="float64"))
    if len(spx) == 0:
        return pd.Series(dtype="float64")
    spx_m = clamp_future(spx.resample("ME").last())
    nom = yoy(spx_m, 12)
    if len(cpi) == 0:
        # без инфляции это номинальная доходность, а панель подписана как
        # реальная — лучше пустая панель, чем подмена смысла
        return pd.Series(dtype="float64")
    infl = yoy(cpi.resample("ME").last(), 12)
    real = clamp_future((nom - infl).dropna())
    if normalize and len(real) > 24:
        real = ((real - real.expanding(24).mean()) / real.expanding(24).std()).dropna()
    return daily(real)


# ------------------------------------------------------------- сборка панелей

W = "#e8e8e8"


def _p(pid, title, series, ptype="line", zero=False, height=1, sub=None, digits=2, suffix=""):
    return {
        "id": pid, "title": title, "type": ptype, "zero": zero,
        "height": height, "sub": sub, "digits": digits, "suffix": suffix,
        "series": series,
    }


def _s(name, s, color, ptype=None, digits=2, suffix="", scale="right",
       invert=False, stamp=None, freshness_source=None):
    """
    stamp — дата последнего НАСТОЯЩЕГО наблюдения. Для сырых рядов считается
    сама; для производных (они уже протянуты daily() до сегодня) её нужно
    передать явно, иначе протухший ряд будет выглядеть свежим.
    """
    st = stamp if stamp is not None else asof(s)
    return {
        "name": name, "suffix": suffix, "color": color, "type": ptype, "scale": scale, "invert": invert,
        "last": fmt(last_val(s), digits, suffix),
        "lastRaw": last_val(s),
        "asof": st.strftime("%Y-%m-%d") if st is not None else None,
        "stale": bool(is_stale(freshness_source if freshness_source is not None else s, st)),
        "data": to_points(s),
    }


def build_panels(raw: dict) -> list[dict]:
    g = lambda k: raw.get(k, pd.Series(dtype="float64"))   # noqa: E731

    # --- производные
    netliq = net_fed_liquidity(raw)
    gm2, gm2_parts, gm2_out = global_m2_usd(raw)
    cbtot, cb_parts, cb_out = cb_balance_usd(raw)
    stress, stress_used, stress_out = stress_composite(raw)
    stress_sources=[g(sid) if len(g(sid)) else g("VIX") for sid,label in STRESS_PARTS.items() if label in stress_used]
    stress_stamp=min(filter(None,[asof(a) for a in stress_sources]),default=None)
    stress_cadence=max(stress_sources,key=cadence_days) if stress_sources else pd.Series(dtype=float)
    stance = fed_stance(raw)
    rspx = real_spx_yoy(raw)

    ffr = daily(g("DFF"))
    # ровно год назад по календарю: в pd.date_range(freq="B") 262 дня в году,
    # поэтому shift(252) давал бы ~11.6 месяца при подписи "12m"
    roc = (ffr - ffr.reindex(ffr.index - pd.DateOffset(years=1), method="ffill").values).dropna()
    ffr_bill = (align(g("DFF"), g("DTB3"))[0] - align(g("DFF"), g("DTB3"))[1]).dropna()

    us30, jp30 = align(g("DGS30"), g("JP30Y"))
    carry = (us30 - jp30).dropna()

    hyg, lqd = align(g("HYG"), g("LQD"))
    risk_spread = (hyg / lqd.replace(0, np.nan)).dropna()

    vix = g("VIXCLS") if len(g("VIXCLS")) else g("VIX")

    # --- колонки
    col1 = {
        "title": "СТАВКИ И РИСК",
        "panels": [
            _p("tlt",   "TLT",                    [_s("TLT", g("TLT"), W)]),
            _p("move",  "MOVE",                   [_s("MOVE", g("MOVE"), "#f48fb1")]),
            _p("vix",   "VIX",                    [_s("VIX", vix, "#ffd54f")]),
            _p("dxy",   "DXY",                    [_s("DXY", g("DXY"), "#26a69a", "area")], digits=3),
            _p("ffr",   "FED RATE + ROC",
               [_s("Fed Funds", ffr, "#ffee58", stamp=asof(g("DFF"))),
                _s("12m изм., пп", roc, "#26a69a", "hist", stamp=asof(g("DFF")))], zero=True, height=1.3),
            _p("t5yie", "5Y ожидаемая инфляция (T5YIE)", [_s("T5YIE", g("T5YIE"), "#ffa726")]),
            _p("real10","Real 10Y (TIPS)",        [_s("DFII10", g("DFII10"), W)], zero=True),
            _p("stance","FED STANCE (FFR − 2Y)",  [_s("Stance", stance, "#66bb6a", "baseline", stamp=min(filter(None, [asof(g("DFF")), asof(g("DGS2"))]), default=None))], zero=True,
               sub="выше 0 — жёстко (рынок ждёт снижений), ниже 0 — мягко"),
            _p("curve", "3M10Y / 2Y10Y",
               [_s("10Y−3M", g("T10Y3M"), "#d4e157", "baseline"),
                _s("10Y−2Y", g("T10Y2Y"), W)], zero=True, height=1.2),
        ],
    }

    col2 = {
        "title": "ЛИКВИДНОСТЬ И КРЕДИТ",
        "panels": [
            _p("spx2",  "SPX",                    [_s("SPX", g("SPX"), W)], digits=0, height=1.4),
            _p("risk",  "Risk Spread (HYG/LQD)",  [_s("HYG/LQD", risk_spread, "#ef5350", stamp=min(filter(None, [asof(g("HYG")), asof(g("LQD"))]), default=None))], digits=3,
               sub="аппетит к риску: растёт — риск-он"),
            _p("nfci",  "Fin Conditions (NFCI)",  [_s("NFCI", g("NFCI"), "#f8bbd0")], zero=True,
               sub="выше 0 — условия жёстче среднего"),
            _p("carry", "US30Y − JP30Y",          [_s("Спред, пп", carry, "#ec407a", stamp=min(filter(None, [asof(g("DGS30")), asof(g("JP30Y"))]), default=None))], digits=3,
               sub="керри-трейд: сужение — риск разворота потоков"),
            _p("ffr3m", "FFR − 3M T-Bill",        [_s("Спред, пп", ffr_bill, "#ff9800", "baseline", stamp=min(filter(None,[asof(g("DFF")),asof(g("DTB3"))]),default=None))], zero=True),
            _p("gm2",   "Global M2 (трлн $)",     [_s("Global M2", gm2, "#ffeb3b", freshness_source=g("M2SL"), stamp=min(filter(None, [asof(g(s)) for s in (C.M2_US, C.M2_EU, C.M2_JP, C.M2_CN, C.M2_UK)]), default=None))], digits=1,
               sub=("в сумме: " + " + ".join(gm2_parts) if gm2_parts else "нет свежих компонентов")
                   + (" · выброшено: " + "; ".join(gm2_out) if gm2_out else "")),
            _p("gli",   "Global Liquidity (трлн $)", [_s("Балансы ЦБ", cbtot, "#66bb6a", "area", freshness_source=g("JPNASSETS"), stamp=min(filter(None, [asof(g(s)) for s in ("WALCL", "ECBASSETSW", "JPNASSETS")]), default=None))], digits=2,
               sub=("в сумме: " + " + ".join(cb_parts) if cb_parts else "нет свежих компонентов")
                   + (" · выброшено: " + "; ".join(cb_out) if cb_out else "")),
            _p("netliq","Net Fed Liquidity (млрд $)", [_s("Активы−TGA−RRP", netliq, "#ef5350", stamp=min(filter(None, [asof(g("WALCL")), asof(g("WTREGEN")), asof(g("RRPONTSYD"))]), default=None))], digits=0, height=1.3),
            _p("stress","Stress Index (z-score)",
               [_s("Композит", stress, "#ff9800", "hist", invert=True, stamp=stress_stamp, freshness_source=stress_cadence)], zero=True,
               sub=("средний z по: " + ", ".join(stress_used) if stress_used else "нет компонентов")
                   + "; красный — стресс растёт"
                   + (" · выброшено: " + "; ".join(stress_out) if stress_out else "")),
            _p("rrp",   "Reverse Repo (млрд $)",  [_s("RRP", g("RRPONTSYD"), "#4caf50", "area")], digits=0,
               sub="пик 2554 млрд в дек. 2022, сейчас опустошён — околонулевые значения тут настоящие"),
        ],
    }

    col3 = {
        "title": "ЦИКЛ",
        "panels": [
            _p("sahm",  "SAHM Rule",              [_s("Sahm", g("SAHMREALTIME"), "#ff9800")],
               sub="выше 0.50 — исторический сигнал рецессии"),
            _p("spx3",  "SPX",                    [_s("SPX", g("SPX"), W)], digits=0, height=2.0),
            _p("curve3","SPX vs 3M/10Y",
               [_s("10Y−3M", g("T10Y3M"), "#26a69a", "baseline"),
                _s("10Y−2Y", g("T10Y2Y"), W)], zero=True, height=1.3),
            _p("rspx",  "Real SPX Y (z-score)",   [_s("Real SPX YoY", rspx, "#d4c05a", "baseline", freshness_source=g("CPIAUCSL"), stamp=asof(g("CPIAUCSL")))], zero=True,
               sub="номинальный YoY минус инфляция, нормировано"),
            _p("real10b","Real 10Y (TIPS)",       [_s("DFII10", g("DFII10"), W, "baseline")], zero=True),
            _p("cbparts", "Балансы ЦБ по отдельности (трлн $)",
               [_s(k, v / 1000.0, c, None, 2, stamp=asof(g({"FED":"WALCL","ECB":"ECBASSETSW","BOJ":"JPNASSETS"}[k])), freshness_source=g({"FED":"WALCL","ECB":"ECBASSETSW","BOJ":"JPNASSETS"}[k]))
                for (k, v), c in zip(cb_parts.items(), ["#ef5350", "#42a5f5", "#ffa726"])],
               height=1.2, sub="ФРС / ЕЦБ / Банк Японии, пересчёт в доллары"),
        ],
    }

    col4 = {
        "title": "НЕДВИЖИМОСТЬ И РЫНОК",
        "panels": [
            _p("spxhgx", "SPX  /  HGX (жильё)",
               [_s("SPX", g("SPX"), W, None, 0),
                _s("HGX", g("HGX"), "#ffa726", None, 0, "", "left")], digits=0, height=2.2),
            _p("exhs",  "New Home Sales (тыс., SAAR)", [_s("Продажи новых домов", g("HSN1F"), "#66bb6a")], digits=0,
               sub="Existing Home Sales на FRED почти пуст — NAR ограничила лицензию"),
            _p("permit","Building Permits",       [_s("Разрешения", g("PERMIT"), W)], digits=0),
            _p("cs",    "Home Price (Case-Shiller)", [_s("CS index", g("CSUSHPINSA"), "#ffa726")], digits=1),
        ],
    }

    return [col1, col2, col3, col4]
