# -*- coding: utf-8 -*-
"""
Конфигурация дашборда: какие ряды тянем и из каких источников.

Всё бесплатно и без API-ключей:
  FRED   -> https://fred.stlouisfed.org/graph/fredgraph.csv?id=XXX
  Yahoo  -> https://query1.finance.yahoo.com/v8/finance/chart/XXX
  MOF JP -> https://www.mof.go.jp/.../jgbcm.csv   (доходности JGB)

Если у тебя есть ключ FRED (бесплатный, fredaccount.stlouisfed.org),
положи его в переменную окружения FRED_API_KEY — скрипт переключится
на официальный API (он стабильнее). Без ключа тоже работает.
"""

# ---------------------------------------------------------------- FRED
# id -> человекочитаемое описание (используется в отчёте doctor)
FRED = {
    # ставки и кривая
    "DFF":            "Effective Fed Funds Rate, %",
    "DTB3":           "3-Month T-Bill, %",
    "DGS2":           "2Y Treasury, %",
    "DGS30":          "30Y Treasury, %",
    "T10Y3M":         "10Y-3M spread, pp",
    "T10Y2Y":         "10Y-2Y spread, pp",
    "T5YIE":          "5Y breakeven inflation, %",
    "DFII10":         "10Y TIPS (real yield), %",

    # риск / стресс
    "VIXCLS":         "VIX",
    "NFCI":           "Chicago Fed National Financial Conditions Index",
    "STLFSI4":        "St. Louis Fed Financial Stress Index",
    "BAMLH0A0HYM2":   "US High Yield OAS, pp",
    "BAMLC0A0CM":     "US Investment Grade OAS, pp",
    "SAHMREALTIME":   "Sahm Rule Recession Indicator",

    # ликвидность
    "WALCL":          "Fed total assets, $mn",
    "WTREGEN":        "Treasury General Account, $mn",
    "RRPONTSYD":      "Overnight Reverse Repo, $bn",
    "ECBASSETSW":     "ECB total assets, EUR mn",
    "JPNASSETS":      "Bank of Japan total assets, 100 mn JPY",

    # денежная масса
    # Только США. Зарубежную денежную массу FRED вести перестал: ряды MYAGM2*
    # замерли в 2017-2019, широкие деньги OECD (MABMM301*) — в ноябре 2023.
    # Живые данные берём у первоисточников, см. DBNOMICS и DIRECT ниже.
    "M2SL":           "US M2, $bn",

    # курсы (для перевода в USD)
    "DEXUSEU":        "USD per EUR",
    "DEXJPUS":        "JPY per USD",
    "DEXCHUS":        "CNY per USD",
    "DEXUSUK":        "USD per GBP",

    # макро / недвижимость
    # Existing Home Sales (EXHOSLUSM495S) на FRED почти пуст: NAR ограничила
    # лицензию, осталось меньше полутора лет. Берём продажи новых домов от
    # Бюро переписи — свободные данные с 1963 года.
    "CPIAUCSL":        "CPI, index",
    "HSN1F":           "New One Family Houses Sold, thous. SAAR",
    "PERMIT":          "Building Permits, thous. units",
    "CSUSHPINSA":      "Case-Shiller US National Home Price Index",
    "USREC":           "NBER recession indicator (0/1)",
}

# ---------------------------------------------------------------- Yahoo
YAHOO = {
    "TLT":  "TLT",        # 20+ Year Treasury Bond ETF
    "MOVE": "^MOVE",      # ICE BofA MOVE (волатильность облигаций)
    "DXY":  "DX-Y.NYB",   # индекс доллара
    "SPX":  "^GSPC",      # S&P 500
    "HGX":  "^HGX",       # PHLX Housing Sector Index
    "HYG":  "HYG",        # High Yield Corp Bond ETF
    "LQD":  "LQD",        # Investment Grade Corp Bond ETF
    "VIX":  "^VIX",       # запасной путь, если FRED:VIXCLS не отдаст
}

# Запасной источник, если Yahoo отдал 429 / упал. У Stooq нет MOVE, HGX и DXY.
STOOQ = {
    "TLT": "tlt.us", "SPX": "^spx", "VIX": "^vix",
    "HYG": "hyg.us", "LQD": "lqd.us",
}

# ---------------------------------------------------------------- Japan MOF
# 30-летние JGB. FRED японскую 30-летку не отдаёт, берём с сайта Минфина.
JGB_CURRENT_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
JGB_HISTORY_URL = ("https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
                   "historical/jgbcme_all.csv")

# ---------------------------------------------------------------- денежные ряды
#
# Эти ряды выражены в деньгах, и каждая страна публикует их в своих единицах:
# где миллионы, где сто-миллионы, где просто единицы валюты. Раньше множители
# стояли здесь руками — и один из них оказался неверным (WTREGEN на самом деле
# в миллионах, а не в миллиардах, из-за чего Net Fed Liquidity считался мимо).
#
# Теперь единицы НЕ УГАДЫВАЮТСЯ: при наличии ключа FRED скрипт спрашивает у
# API поле units по каждому ряду и сам приводит его к МИЛЛИАРДАМ. Список ниже
# говорит только о том, к каким рядам применять это приведение.
MONEY_SERIES = {
    "WALCL", "WTREGEN", "RRPONTSYD", "ECBASSETSW", "JPNASSETS",
    "M2SL", "M2EU", "M2JP", "M2CN", "M2UK",
}

# Запасные множители -> млрд нац. валюты. Работают, только если ключа нет и
# метаданные спросить не у кого.
UNIT_SCALE = {
    "WALCL":            1e-3,   # $mn         -> $bn
    "WTREGEN":          1e-3,   # $mn         -> $bn
    "RRPONTSYD":        1.0,    # уже $bn
    "ECBASSETSW":       1e-3,   # EUR mn      -> EUR bn
    "JPNASSETS":        1e-1,   # 100 mn JPY  -> JPY bn
    "M2SL":             1.0,    # уже $bn
}

# ---------------------------------------------------------------- прочее
START_DATE = "1998-01-01"   # с какой даты тянем историю
Z_WINDOW_DAYS = 1250        # окно для z-score в Stress Index (~5 лет торговых дней)

# Компонент композита старше этого возраста считается протухшим и в сумму не
# берётся: замороженный ряд тянет итог в горизонталь и врёт убедительнее,
# чем честный пропуск. Какие компоненты реально вошли — написано под панелью.
STALE_DAYS = 400

# Какие ряды берём под компоненты Global M2. Вынесено сюда, потому что
# источник для зарубежной денежной массы сейчас меняется: FRED её забросил,
# живые данные лежат у первоисточников.
M2_US = "M2SL"          # FRED
M2_EU = "M2EU"          # ЕЦБ через DBnomics
M2_JP = "M2JP"          # Банк Японии, напрямую
M2_CN = "M2CN"          # НБК через портал East Money
M2_UK = "M2UK"          # Банк Англии, напрямую


# ---------------------------------------------------------------- DBnomics
#
# Ряды, которых на FRED больше нет. Коды найдены разведкой (explore.bat) —
# у каждого проверена дата последнего наблюдения, чтобы не подключить
# очередной замороженный ряд.
#
# ECB/BSI M.U2.Y.V.M20.X.1.U2.2300.Z01.E — денежный агрегат M2 еврозоны,
# непогашенные остатки, очищено от сезонности и числа рабочих дней,
# в миллионах евро. На момент подключения — июль 2026.
DBNOMICS = {
    "M2EU": {
        "provider": "ECB", "dataset": "BSI",
        "code": "M.U2.Y.V.M20.X.1.U2.2300.Z01.E",
        "units": "Millions of Euro",
        "desc": "Денежный агрегат M2 еврозоны, остатки, SA+WDA",
    },
}

# ------------------------------------------------------- прямые источники
#
# Сюда попадает то, чего нет ни на FRED, ни у агрегаторов в живом виде.
# Разведка показала, что оба сайта открываются напрямую, а посредники
# отдают либо ничего, либо ряды двухлетней давности.
#
#   Банк Англии — публичная выгрузка из базы IADB, готовый CSV.
#     LPMAUYM = M4, месячные остатки, миллионы фунтов.
#
#   Банк Японии — страница месячной денежной массы. Таблица широкая:
#     сначала годовые приросты в процентах, потом уровни в 100 млн иен.
#     Нужную колонку ищем по заголовку, см. sources._parse_boj.
#
#   Китай — через портал East Money, который публикует сводку денежной
#     массы НБК своим JSON-эндпоинтом. Первоисточники (data.stats.gov.cn,
#     pbc.gov.cn) отдают 403 и скрипту, и настоящему браузеру: режут по
#     региону. Это посредник, и его надёжность ниже — если он отвалится,
#     компонент выпадет из суммы и будет подписан под панелью.
#
# Любой из этих рядов можно перебить своим файлом: положи CSV как
# data/manual/<ИМЯ>.csv, например data/manual/M2CN.csv — он подхватится,
# если сеть ряд не отдала.
DIRECT = {
    "M2UK": {
        "kind": "boe", "code": "LPMAUYM",
        "units": "Millions of Pounds",
        "desc": "Денежный агрегат M4 Британии, остатки",
    },
    "M2JP": {
        "kind": "boj", "item": "M2",
        "url": "https://www.stat-search.boj.or.jp/ssi/mtshtml/md02_m_1_en.html",
        "units": "100 Million Yen",
        "desc": "Денежный агрегат M2 Японии, средние остатки за месяц",
    },
    "M2CN": {
        "kind": "eastmoney",
        "report": "RPT_ECONOMY_CURRENCY_SUPPLY",
        "field": "BASIC_CURRENCY",          # 货币和准货币 = M2
        "units": "100 Million Yuan",
        "desc": "Денежный агрегат M2 Китая, данные НБК через East Money",
    },
}
