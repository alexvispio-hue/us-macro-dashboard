# -*- coding: utf-8 -*-
"""
Сборка дашборда.

    python src/build.py            обновить данные и собрать dashboard.html
    python src/build.py --open     то же + открыть в браузере
    python src/build.py --doctor   только проверка источников, без сборки
    python src/build.py --offline  собрать из кэша, в сеть не ходить
"""

from __future__ import annotations

import json
import sys
import webbrowser
import datetime as dt
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config as C          # noqa: E402
import sources              # noqa: E402
import derive               # noqa: E402
import market               # noqa: E402
import catalogue            # noqa: E402
import history              # noqa: E402

ROOT = HERE.parent
TEMPLATE = ROOT / "web" / "index.html"
VENDOR = ROOT / "web" / "vendor" / "lightweight-charts.js"
OUT_HTML = ROOT / "dashboard.html"
OUT_JSON = ROOT / "data" / "dashboard.json"
LOG = ROOT / ("last_doctor.log" if "--doctor" in sys.argv else "last_run.log")


class _Tee:
    """Пишет всё, что уходит в консоль, ещё и в last_run.log."""

    def __init__(self, stream, path: Path):
        self.stream = stream
        self.file = open(path, "w", encoding="utf-8")         # noqa: SIM115
        # библиотеки спрашивают эти атрибуты у sys.stdout — без них AttributeError
        self.encoding = getattr(stream, "encoding", "utf-8")
        self.errors = getattr(stream, "errors", None)

    def isatty(self):
        return getattr(self.stream, "isatty", lambda: False)()

    def fileno(self):
        return self.stream.fileno()

    def write(self, s):
        self.stream.write(s)
        self.file.write(s)
        self.file.flush()
        return len(s)

    def flush(self):
        self.stream.flush()
        self.file.flush()

    def close(self):
        try:
            self.file.close()
        except Exception:                                     # noqa: BLE001
            pass


def main() -> int:
    args = set(sys.argv[1:])
    if "--offline" in args:
        sources.CACHE_HOURS = 10 ** 6      # кэш всегда считаем свежим
        sources.OFFLINE = True             # и метаданные из сети тоже не тянем

    key = sources.fred_key()
    print(f"Macro Dashboard · {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Python {sys.version.split()[0]} · {sys.platform}")
    print("Ключ FRED: " + ("есть — качаем через api.stlouisfed.org"
                           if key else "НЕТ — качаем CSV с fred.stlouisfed.org"))
    print(f"Аргументы: {' '.join(sys.argv[1:]) or '(нет)'}")
    print()

    print("=" * 74)
    print("  Загрузка данных")
    print("=" * 74)
    raw = sources.fetch_all()
    raw.update(catalogue.load(raw))

    ok = sum(1 for d in sources.DIAG if d["status"] in ("ok", "cache"))
    bad = [d for d in sources.DIAG if d["status"] in ("fail", "skip")]
    print("-" * 74)
    print(f"  Получено: {ok} из {len(sources.DIAG)}")
    if bad:
        print(f"  Не удалось: {', '.join(d['name'] for d in bad)}")
        print("  Панели с этими рядами будут пустыми — остальные соберутся нормально.")

    # частый случай: сайт FRED режет соединение, а официальный API работает
    if "fred.stlouisfed.org" in sources.DEAD_HOSTS and not sources.fred_key():
        print()
        print("!" * 74)
        print("  Сайт fred.stlouisfed.org не отвечает — соединение рвётся на подключении.")
        print("  Так бывает, когда FRED режет трафик из твоей страны.")
        print()
        print("  ЛЕЧИТСЯ БЕСПЛАТНЫМ КЛЮЧОМ. Официальный API живёт на другом хосте")
        print("  (api.stlouisfed.org) и обычно доступен даже когда сайт закрыт.")
        print()
        print("    1. Открой https://fredaccount.stlouisfed.org/apikeys")
        print("    2. Заведи аккаунт (почта + пароль) и нажми Request API Key")
        print("    3. Скопируй ключ в файл fred_key.txt рядом с run.bat")
        print("    4. Запусти run.bat заново")
        print()
        print("  Если и страница регистрации не открывается — включи VPN на время")
        print("  получения ключа. Дальше VPN уже не понадобится.")
        print("!" * 74)

    if "--doctor" in args:
        print()
        print("=" * 74)
        print("  Единицы денежных рядов (взяты из метаданных FRED)")
        print("=" * 74)
        for sid in sorted(C.MONEY_SERIES):
            s = raw.get(sid)
            if s is None or len(s) == 0:
                print(f"  {sid:18s} нет данных")
                continue
            factor, units = sources.money_scale(sid)
            print(f"  {sid:18s} {units:28s} x{factor:<8g} "
                  f"-> {s.iloc[-1] * factor:>14,.1f} млрд  ({s.index[-1].date()})")

        print()
        print("=" * 74)
        print("  Композиты")
        print("=" * 74)
        gm2, parts, dropped = derive.global_m2_usd(raw)
        for k, v in parts.items():
            print(f"  M2 {k:3s} в млрд USD: {derive.last_val(v):,.1f}")
        for d in dropped:
            print(f"  M2 выброшен -> {d}")
        print(f"  Global M2 итого, трлн USD: {derive.fmt(derive.last_val(gm2), 1)}")
        print()
        cb, cbp, cb_dropped = derive.cb_balance_usd(raw)
        for k, v in cbp.items():
            print(f"  Баланс {k:3s} в млрд USD: {derive.last_val(v):,.1f}")
        for d in cb_dropped:
            print(f"  Баланс выброшен -> {d}")
        print(f"  ФРС+ЕЦБ+БЯ итого, трлн USD: {derive.fmt(derive.last_val(cb), 2)}")
        print("  Ориентир: сумма трёх балансов сейчас порядка 15-20 трлн USD.")
        print()
        print(f"  Net Fed Liquidity, млрд USD: {derive.fmt(derive.last_val(derive.net_fed_liquidity(raw)), 0)}")
        print("  Ориентир: порядка 5000-6500 млрд USD.")
        return 0

    print()
    print("=" * 74)
    print("  Расчёт панелей")
    print("=" * 74)
    columns = derive.build_panels(raw)
    markets = market.build(raw)
    # Replace the duplicate bare SPX panel with the tradable SPY volume profile.
    columns[1]['panels'][0] = markets['columns'][0]['panels'][1]
    for col in columns:
        for panel in col['panels']:
            if panel['id'] == 'sahm':
                panel['levels'] = [0.5]
            if panel['id'] == 'spx3':
                panel['zones'] = derive.to_points(raw.get('USREC'))
                panel['sub'] = 'Красные зоны — рецессии NBER (USREC), не прогноз'

    n_pts = sum(len(s["data"]) for c in columns for p in c["panels"] for s in p["series"])
    n_pan = sum(len(c["panels"]) for c in columns)
    empty = [p["title"] for c in columns for p in c["panels"]
             if not any(s["data"] for s in p["series"])]
    print(f"  Панелей: {n_pan}, точек данных: {n_pts:,}".replace(",", " "))
    if empty:
        print(f"  Пустые панели: {', '.join(empty)}")

    payload = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "displayStart": derive.DISPLAY_START,
        "columns": columns,
        "markets": markets,
        "workspaces": catalogue.build(raw, columns, markets),
        "diagnostics": sources.DIAG,
    }

    previous = None
    if OUT_JSON.exists():
        try:
            previous = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    history.annotate(payload, raw)
    payload['changes'] = history.snapshot_change(previous, payload)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    if not TEMPLATE.exists():
        print(f"  ! нет шаблона {TEMPLATE}")
        return 1
    html = TEMPLATE.read_text(encoding="utf-8")
    lib = VENDOR.read_text(encoding="utf-8") if VENDOR.exists() else ""
    if not lib:
        print("  ! нет web/vendor/lightweight-charts.js — страница подтянет библиотеку из интернета")
    html = html.replace("/*__LIB__*/", lib)
    html = html.replace("/*__RESEARCH__*/", (ROOT / "web" / "research.js").read_text(encoding="utf-8"))
    # Тексты ошибок содержат данные с чужих серверов. Если там окажется "</script>",
    # тег закроется раньше времени и страница развалится целиком.
    blob = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/", blob)
    OUT_HTML.write_text(html, encoding="utf-8")

    size_mb = OUT_HTML.stat().st_size / 1e6
    print()
    print("=" * 74)
    print(f"  Готово: {OUT_HTML}   ({size_mb:.1f} МБ)")
    print("=" * 74)

    if "--open" in args:
        webbrowser.open(OUT_HTML.as_uri())
    return 0


if __name__ == "__main__":
    _orig = sys.stdout
    _tee = _Tee(_orig, LOG)
    sys.stdout = _tee
    sys.stderr = _tee
    try:
        code = main()
    except Exception:                                         # noqa: BLE001
        import traceback
        traceback.print_exc()
        code = 1
    finally:
        print()
        print(f"[лог этого запуска: {LOG}]")
        sys.stdout = _orig
        sys.stderr = sys.__stderr__
        _tee.close()
    raise SystemExit(code)
