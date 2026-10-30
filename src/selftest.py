# -*- coding: utf-8 -*-
"""
Оффлайн-проверка конвейера.

Генерирует синтетические данные в data/raw/ в точно тех форматах, которые
отдают FRED / Yahoo / Минфин Японии, и прогоняет через них весь расчёт.
Нужен, чтобы проверить код без доступа к сети. Живые данные он НЕ трогает —
кладёт всё в отдельную папку data_selftest/.

    python src/selftest.py
"""

from __future__ import annotations

import json
import sys
import time
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config as C          # noqa: E402
import sources              # noqa: E402
import derive               # noqa: E402

RNG = np.random.default_rng(7)

# правдоподобные уровни, чтобы заодно проверить масштабы и вёрстку
LEVELS = {
    "DFF": 3.6, "DTB3": 3.8, "DGS2": 3.1, "DGS30": 4.7,
    "T10Y3M": 0.0, "T10Y2Y": 0.5, "T5YIE": 2.34, "DFII10": 2.31,
    "VIXCLS": 15.3, "NFCI": -0.56, "STLFSI4": -0.9,
    "BAMLH0A0HYM2": 2.9, "BAMLC0A0CM": 0.9, "SAHMREALTIME": -0.03,
    "WALCL": 6_600_000, "WTREGEN": 967_900.0, "RRPONTSYD": 0.702,   # опустошён, как сейчас в реальности
    "ECBASSETSW": 5_900_000, "JPNASSETS": 7_400_000,
    "M2SL": 23_218,
    "DEXUSEU": 1.09, "DEXJPUS": 150.0, "DEXCHUS": 7.15, "DEXUSUK": 1.27,
    "CPIAUCSL": 332.8, "HSN1F": 660.0, "PERMIT": 1_433,
    "CSUSHPINSA": 330.0, "USREC": 0.0,
}
VOL = {"WALCL": .0008, "M2SL": .0006, "CPIAUCSL": .0003, "PERMIT": .004,
       "EXHOSLUSM495S": .004, "CSUSHPINSA": .0006}

MONTHLY = {"M2SL", "CPIAUCSL", "HSN1F", "PERMIT", "CSUSHPINSA", "USREC",
           "SAHMREALTIME", "JPNASSETS"}
WEEKLY = {"WALCL", "WTREGEN", "ECBASSETSW", "NFCI", "STLFSI4"}


def walk(level: float, n: int, vol: float, floor: float | None = None) -> np.ndarray:
    steps = RNG.normal(0, vol, n)
    if abs(level) < 1e-9:
        path = np.cumsum(steps) * 2.0
    else:
        path = level * np.exp(np.cumsum(steps) - np.cumsum(steps)[-1])
    if floor is not None:
        path = np.maximum(path, floor)
    return path


def gen_fred(raw_dir: Path) -> None:
    for sid, lvl in LEVELS.items():
        if sid in MONTHLY:
            idx = pd.date_range("2005-01-01", dt.date.today(), freq="MS")
        elif sid in WEEKLY:
            idx = pd.date_range("2005-01-05", dt.date.today(), freq="W-WED")
        else:
            idx = pd.date_range("2005-01-03", dt.date.today(), freq="B")
        vals = walk(lvl, len(idx), VOL.get(sid, 0.012))
        if sid == "USREC":
            vals = np.zeros(len(idx))
        df = pd.DataFrame({"observation_date": idx.strftime("%Y-%m-%d"), sid: np.round(vals, 6)})
        (raw_dir / f"fred_{sid}.csv").write_text(df.to_csv(index=False), encoding="utf-8")


def gen_yahoo(raw_dir: Path) -> None:
    ylv = {"TLT": 82.0, "MOVE": 73.2, "DXY": 98.8, "SPX": 7681.0,
           "HGX": 566.8, "HYG": 80.0, "LQD": 110.0, "VIX": 15.3}
    idx = pd.date_range("2005-01-03", dt.date.today(), freq="B")
    ts = [int(time.mktime(d.timetuple())) for d in idx]
    for name, lvl in ylv.items():
        vals = walk(lvl, len(idx), 0.011)
        payload = {"chart": {"result": [{
            "meta": {"symbol": name},
            "timestamp": ts,
            "indicators": {"quote": [{"close": [round(float(v), 4) for v in vals]}]},
        }], "error": None}}
        (raw_dir / f"yahoo_{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def gen_dbnomics(raw_dir: Path) -> None:
    """Кэш DBnomics в том же виде, в каком его отдаёт API."""
    idx = pd.date_range("2005-01-01", dt.date.today(), freq="MS")
    for name, lvl in {"M2EU": 16_436_438.0}.items():
        vals = walk(lvl, len(idx), 0.004)
        payload = {"series": {"docs": [{
            "series_code": name,
            "period": [d.strftime("%Y-%m") for d in idx],
            "value": [round(float(v), 3) for v in vals],
        }]}}
        (raw_dir / f"dbnomics_{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def gen_direct(raw_dir: Path) -> None:
    """Прямые источники: CSV Банка Англии и HTML-таблица Банка Японии."""
    idx = pd.date_range("2005-01-01", dt.date.today(), freq="ME")

    # Банк Англии: DATE,LPMAUYM с датами "31 Jul 2026"
    m4 = walk(3_302_403.0, len(idx), 0.004)
    csv = "DATE,LPMAUYM\n" + "".join(
        f"{d.strftime('%d %b %Y')},{v:.0f}\n" for d, v in zip(idx, m4))
    (raw_dir / "boe_M2UK.csv").write_text(csv, encoding="utf-8")

    # Банк Японии: широкая таблица, сперва проценты, потом уровни
    mi = pd.date_range("2005-01-01", dt.date.today(), freq="MS")
    m2 = walk(12_970_074.0, len(mi), 0.003)
    m3 = m2 * 1.266
    hdr = ["Name of time-series",
           "M2/Percent changes from the previous year in average amounts outstanding/Money Stock",
           "M3/Percent changes from the previous year in average amounts outstanding/Money Stock",
           "M2/Average amounts outstanding/Money Stock",
           "M3/Average amounts outstanding/Money Stock"]
    html = ["<table><tr>" + "".join(f"<th>{h}</th>" for h in hdr) + "</tr>"]
    for d, a, b in zip(mi, m2, m3):
        html.append(f"<tr><td>{d.year}/{d.month:02d}</td><td>2.2</td><td>1.4</td>"
                    f"<td>{a:.0f}</td><td>{b:.0f}</td></tr>")
    html.append("<tr><td>2099/01</td><td></td><td></td><td></td><td></td></tr></table>")
    (raw_dir / "boj_M2JP.html").write_text("".join(html), encoding="utf-8")

    # East Money: сводка денежной массы НБК, значения в 100 млн юаней
    m2cn = walk(3_555_077.24, len(mi), 0.004)
    rows = [{"REPORT_DATE": d.strftime("%Y-%m-%d 00:00:00"),
             "TIME": f"{d.year}\u5e74{d.month:02d}\u6708\u4efd",
             "BASIC_CURRENCY": round(float(v), 2),
             "CURRENCY": round(float(v) * 0.325, 2),
             "FREE_CASH": round(float(v) * 0.042, 2)}
            for d, v in zip(mi, m2cn)][::-1]          # портал отдаёт от свежих к старым
    (raw_dir / "eastmoney_M2CN.json").write_text(
        json.dumps({"result": {"pages": 1, "data": rows, "count": len(rows)},
                    "success": True, "message": "ok", "code": 0}), encoding="utf-8")


def gen_jgb(raw_dir: Path) -> None:
    """Повторяет реальный формат Минфина Японии, включая обе записи дат и мусор в хвосте."""
    idx = pd.date_range("2005-01-03", dt.date.today(), freq="B")
    v30 = walk(3.5, len(idx), 0.010)

    head = "Date,1Y,2Y,3Y,4Y,5Y,6Y,7Y,8Y,9Y,10Y,15Y,20Y,25Y,30Y,40Y\n"
    mid = "0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0,2.0,2.5,3.0"
    tail = ",,,,,,,,,,,,,,,\n\"  |If you cannot download the latest csv data, please clear the browser's cache.\",,,,,,,,,,,,,,,\n"

    # архив 1974~ : японские эры
    def era(d: pd.Timestamp) -> str:
        return (f"R{d.year - 2018}.{d.month}.{d.day}" if d.year >= 2019
                else f"H{d.year - 1988}.{d.month}.{d.day}")

    hist = ("Interest Rate,,,,,,,,,,,,,,,(Unit : %)\n" + head
            + "".join(f"{era(d)},{mid},{v:.3f},3.6\n" for d, v in zip(idx, v30)) + tail)
    (raw_dir / "jgb_hist.csv").write_text(hist, encoding="utf-8")

    # текущий месяц : даты со слэшами
    cur_idx, cur_v = idx[-3:], v30[-3:]
    cur = ("Interest Rate (September 2026),,,,,,,,,,,,,,,(Unit : %)\n" + head
           + "".join(f"{d.year}/{d.month}/{d.day},{mid},{v:.3f},3.6\n"
                     for d, v in zip(cur_idx, cur_v)) + tail)
    (raw_dir / "jgb_cur.csv").write_text(cur, encoding="utf-8")


def main() -> int:
    root = HERE.parent
    raw_dir = root / "data_selftest" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print("Генерирую синтетические данные…")
    gen_fred(raw_dir)
    gen_yahoo(raw_dir)
    gen_dbnomics(raw_dir)
    gen_direct(raw_dir)
    gen_jgb(raw_dir)

    # подменяем папку кэша и запрещаем сеть
    sources.RAW = raw_dir
    sources.CACHE_HOURS = 10 ** 6
    sources.DIAG.clear()

    def no_net(*a, **k):
        raise RuntimeError("selftest: сеть запрещена")
    sources._get = no_net

    print("Гоняю загрузчики…")
    raw = sources.fetch_all()

    failed = [d["name"] for d in sources.DIAG if d["status"] == "fail"]
    assert not failed, f"загрузчики упали: {failed}"

    print("Считаю панели…")
    cols = derive.build_panels(raw)

    problems = []
    for c in cols:
        for p in c["panels"]:
            for s in p["series"]:
                if not s["data"]:
                    problems.append(f"{c['title']} / {p['title']} / {s['name']}")
    n_pts = sum(len(s["data"]) for c in cols for p in c["panels"] for s in p["series"])
    n_pan = sum(len(c["panels"]) for c in cols)

    print()
    print(f"  колонок: {len(cols)}   панелей: {n_pan}   точек: {n_pts:,}".replace(",", " "))
    if problems:
        print("  ПУСТЫЕ РЯДЫ:")
        for p in problems:
            print("    -", p)
    else:
        print("  все ряды заполнены")

    print()
    print("  Контрольные величины (на синтетике, порядок должен быть правдоподобным):")
    gm2, gm2p, gm2d = derive.global_m2_usd(raw)
    cb, cbp, cbd = derive.cb_balance_usd(raw)
    nl = derive.net_fed_liquidity(raw)
    print(f"    Global M2, трлн $      : {derive.fmt(derive.last_val(gm2), 1)}")
    print(f"    Балансы ЦБ, трлн $     : {derive.fmt(derive.last_val(cb), 2)}")
    print(f"    Net Fed Liquidity, млрд: {derive.fmt(derive.last_val(nl), 0)}")
    print(f"    FED STANCE, пп         : {derive.fmt(derive.last_val(derive.fed_stance(raw)), 2)}")
    print(f"    Stress Index, z        : {derive.fmt(derive.last_val(derive.stress_composite(raw)[0]), 2)}")

    # собираем html из синтетики, чтобы проверить шаблон
    payload = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M") + " (SELFTEST)",
        "displayStart": derive.DISPLAY_START,
        "columns": cols,
        "diagnostics": sources.DIAG,
    }
    tpl = (root / "web" / "index.html").read_text(encoding="utf-8")
    lib = (root / "web" / "vendor" / "lightweight-charts.js").read_text(encoding="utf-8")
    out = root / "dashboard_selftest.html"
    out.write_text(
        tpl.replace("/*__LIB__*/", lib).replace("/*__DATA__*/", json.dumps(payload, ensure_ascii=False)),
        encoding="utf-8")
    print(f"\n  тестовая страница: {out}  ({out.stat().st_size/1e6:.1f} МБ)")
    print("\nOK")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
