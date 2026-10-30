"""Public-source workspaces supplementing the original macro dashboard."""
from __future__ import annotations
import pandas as pd
import derive as D
import sources

FRED = {
 'CRDQUSAPABIS':'BIS US private credit', 'CRDQXMAPABIS':'BIS euro area private credit',
 'CRDQJPAPABIS':'BIS Japan private credit', 'CRDQCNAPABIS':'BIS China private credit',
 'CPILFESL':'Core CPI', 'PCEPI':'PCE price index', 'PCEPILFE':'Core PCE',
 'GDP':'Nominal GDP', 'GDPC1':'Real GDP', 'A191RL1Q225SBEA':'Real GDP growth, annualized',
 'GFDEBTN':'Federal debt', 'GFDEGDQ188S':'Federal debt / GDP',
 'UNRATE':'Unemployment', 'PAYEMS':'Nonfarm payrolls', 'ICSA':'Initial claims', 'CCSA':'Continuing claims',
 'INDPRO':'Industrial production', 'RSAFS':'Retail sales', 'HOUST':'Housing starts', 'MORTGAGE30US':'30Y mortgage',
 'TOTLL':'US bank loans and leases', 'BUSLOANS':'Commercial and industrial loans', 'TOTALSL':'Consumer credit',
 'BOGZ1FL663067003Q':'Broker customer receivables', 'CP':'Corporate profits after tax',
 'DFII5':'5Y real yield', 'DFII20':'20Y real yield', 'DFII30':'30Y real yield',
 'DGS3MO':'3M Treasury', 'DGS2':'2Y Treasury', 'DGS5':'5Y Treasury', 'DGS10':'10Y Treasury', 'DGS30':'30Y Treasury',
}
YAHOO = {k:k for k in ['SPY','QQQ','IWM','DIA','VT','EFA','EEM','XLK','XLF','XLE','XLV','XLI','XLP','XLY','XLU','XLB','XLRE','XLC','SOXX','GLD','SLV','DBC']}
YAHOO.update({'BTC':'BTC-USD','ETH':'ETH-USD','WTI':'CL=F','BRENT':'BZ=F','GAS':'NG=F','COPPER':'HG=F','SILVER':'SI=F','WHEAT':'ZW=F','CORN':'ZC=F','SOY':'ZS=F'})
COLORS=['#5bd8c0','#90aaff','#e8c47a','#e38ca9']

def load(existing=None):
    """Reuse rows already loaded by the core, including manual CSV fallbacks."""
    existing=existing or {}
    manual=sources.manual_series()
    out={}
    for sid in FRED:
        if sid in existing and len(existing[sid]):
            out[sid]=existing[sid]
            continue
        data=sources.fetch_fred(sid)
        if data.empty and sid in manual:
            data=manual[sid]
            sources._log('MANUAL',sid,'ok',f'n={len(data)}')
        out[sid]=data
    for name,symbol in YAHOO.items():
        out[name]=existing[name] if name in existing and len(existing[name]) else sources.fetch_yahoo(name,symbol)
    return out


def calendar_change(series, months=12, weekly=False, annualize=False):
    """Match calendar periods; missing months/quarters must not shift the comparison."""
    a=series.dropna().sort_index()
    if a.empty:
        return a
    if weekly:
        targets=a.index-pd.DateOffset(years=1)
        base=a.reindex(targets,method='nearest',tolerance=pd.Timedelta(days=4)).to_numpy()
    else:
        periods=a.index.to_period('M')
        by_month=pd.Series(a.to_numpy(),index=periods).groupby(level=0).last()
        base=by_month.reindex(periods-months).to_numpy()
    ratio=a/pd.Series(base,index=a.index).replace(0,float('nan'))
    return ((ratio**(12/months) if annualize else ratio)-1)*100


def build(raw, columns, markets):
    g=lambda k:raw.get(k,pd.Series(dtype=float))
    existing={p['id']:p for c in columns+markets['columns'] for p in c['panels']}
    def p(pid,title,sid,unit='',factor=1):
        return D._p(pid,title,[D._s(sid,g(sid)*factor,COLORS[0],suffix=" "+unit if unit else "",stamp=D.asof(g(sid)))],sub=f'{sid} · {unit} · наблюдения источника',suffix=unit)
    def transformed(pid,title,sid,periods,kind='yoy'):
        a=g(sid).dropna()
        a=calendar_change(a,months=3 if kind=='annual3' else 12,weekly=periods==52,annualize=kind=='annual3')
        return D._p(pid,title,[D._s(sid,a,COLORS[1],suffix="%",stamp=D.asof(g(sid)))],zero=True,sub=f'{sid} · % · '+('3м, в годовом выражении' if kind=='annual3' else f'изменение за {periods} наблюдений'))
    result=[]
    def section(key,family,title,panels,note='',curve=False):
        result.append(dict(id=key,family=family,title=title,note=note,curve=curve,
            columns=[dict(title=title,panels=panels[i:i+2]) for i in range(0,len(panels),2)]))
    def old(*ids): return [existing[k] for k in ids if k in existing]
    section('balances','MACRO / WORLD','Деньги и балансы ЦБ',old('gm2','gli','cbparts','netliq','rrp'))
    section('moneygrowth','MACRO / WORLD','Рост денежной массы',[transformed('m2-'+k,k+' · M2 YoY',k,12) for k in ['M2SL','M2EU','M2JP','M2CN','M2UK']], 'YoY рассчитан на месячных наблюдениях в национальной валюте; M2UK — M4 Банка Англии.')
    section('globalcredit','MACRO / WORLD','Рост кредита · мир',[transformed('credit-'+k,t+' · Credit YoY',k,4) for k,t in [('CRDQUSAPABIS','США'),('CRDQXMAPABIS','Еврозона'),('CRDQJPAPABIS','Япония'),('CRDQCNAPABIS','Китай')]],'BIS через FRED: кредит частному нефинансовому сектору, с поправкой на разрывы; YoY в национальной валюте. Покрытие четырёх экономик, не агрегат всего мира.')
    section('credit','MACRO / WORLD','Кредит',[p('loans','Кредиты банков США','TOTLL','млрд $'),transformed('loans-yoy','Кредиты банков США · YoY','TOTLL',52),p('businessloans','Кредиты бизнесу США','BUSLOANS','млрд $'),p('consumercredit','Потребительский кредит США','TOTALSL','млрд $',.001)], 'Покрытие: США. Полного Global Credit Growth у текущих источников нет; показатели других стран не подменяются американскими.')
    section('cycle','MACRO / USA','Экономический цикл',old('sahm','spx3','rspx')+[p('industry','Промышленное производство','INDPRO','индекс'),transformed('retail','Розничные продажи · YoY','RSAFS',12)], 'Публичные показатели цикла. Авторский Business Cycle · SOL не воспроизводится без формулы.')
    section('inflation','MACRO / USA','Инфляция · CPI и PCE',[transformed('cpi-yoy','CPI · YoY','CPIAUCSL',12),transformed('corecpi-yoy','Core CPI · YoY','CPILFESL',12),transformed('pce-yoy','PCE · YoY','PCEPI',12),transformed('corepce-yoy','Core PCE · YoY','PCEPILFE',12)]+old('t5yie'))
    section('momentum','MACRO / USA','Импульс инфляции',[transformed('momentum-'+k,t+' · 3m annualized',k,3,'annual3') for k,t in [('CPIAUCSL','CPI'),('CPILFESL','Core CPI'),('PCEPI','PCE'),('PCEPILFE','Core PCE')]], 'Формула: ((индекс / индекс 3 месяца назад)^4 − 1) × 100. Это темп, а не прогноз.')
    receiv=(g('BOGZ1FL663067003Q')/1000).copy()
    receiv.index=pd.DatetimeIndex(receiv.index).to_period('Q').to_timestamp(how='end').normalize()
    m2raw=g('M2SL').dropna()
    m2monthly=pd.Series(m2raw.to_numpy(),index=pd.DatetimeIndex(m2raw.index).to_period('M')).groupby(level=0).last()
    m2=pd.Series(m2monthly.reindex(receiv.index.to_period('M')).to_numpy(),index=receiv.index)
    broker_ratio=receiv/m2.replace(0,float('nan'))*100
    section('broker','MACRO / USA','Брокерские требования / M2',[D._p('broker-m2','Broker receivables / US M2',[D._s('Доля, %',broker_ratio,COLORS[0],stamp=D.asof(broker_ratio),freshness_source=receiv)],sub='FRED Z.1 · требования к клиентам / M2 на конец квартала, %')], 'BOGZ1FL663067003Q: миллионы $ → миллиарды $. Включает прочие требования к клиентам; не равен FINRA margin debt.')
    section('gdp','MACRO / USA','ВВП',[p('gdp-level','Номинальный ВВП','GDP','трлн $',.001),p('realgdp','Реальный ВВП','GDPC1','трлн $ 2017',.001),p('gdp-growth','Реальный ВВП · QoQ SAAR','A191RL1Q225SBEA','%')])
    section('debt','MACRO / USA','Государственный долг',[p('debt-level','Федеральный долг США','GFDEBTN','трлн $',.000001),p('debt-gdp','Федеральный долг / ВВП','GFDEGDQ188S','%')])
    section('conditions','MACRO / USA','Финансовые условия',old('nfci','stress','risk','vix','move'))
    section('labor','MACRO / USA','Рынок труда и заявки',[p('unemployment','Безработица','UNRATE','%'),p('payrolls','Nonfarm payrolls','PAYEMS','млн',.001),p('claims','Первичные заявки','ICSA','тыс.',.001),p('continuing','Повторные заявки','CCSA','млн',.000001)]+old('sahm'))
    section('housing','MACRO / USA','Жильё и строительство',old('exhs','permit','cs','spxhgx')+[p('starts','Начатое строительство','HOUST','тыс. SAAR'),p('mortgage','Ипотека 30 лет','MORTGAGE30US','%')])
    section('forex','FOREX','Валюты',old('dxy')+[p('fx-'+k,t,k,u) for k,t,u in [('DEXUSEU','EUR / USD','USD за EUR'),('DEXUSUK','GBP / USD','USD за GBP'),('DEXJPUS','USD / JPY','JPY за USD'),('DEXCHUS','USD / CNY','CNY за USD')]])
    section('crypto','CRYPTO','Криптовалюты',[p('btc','Bitcoin / USD','BTC','$'),p('eth','Ethereum / USD','ETH','$')])
    for key,title,items in [('commodityetf','ETF на сырьё',[('GLD','Gold ETF'),('SLV','Silver ETF'),('DBC','Broad commodities ETF')]),('futures','Фьючерсы',[('WTI','WTI'),('COPPER','Copper'),('SILVER','Silver')]),('metals','Металлы',[('GLD','Gold ETF'),('SILVER','Silver futures'),('COPPER','Copper futures')]),('energy','Энергетика',[('WTI','WTI'),('BRENT','Brent'),('GAS','Natural gas')]),('agri','Сельхозтовары',[('WHEAT','Wheat'),('CORN','Corn'),('SOY','Soybeans')])]:
        section(key,'COMMODITY',title,[p(key+'-'+k,t,k,{'WTI':'$/барр.','BRENT':'$/барр.','GAS':'$/MMBtu','COPPER':'$/фунт','SILVER':'$/унц.','WHEAT':'¢/буш.','CORN':'¢/буш.','SOY':'¢/буш.'}.get(k,'$/акция')) for k,t in items]+(old('gold') if key=='metals' else []),'Фьючерсы — непрерывные ряды Yahoo Finance с переходами контрактов; единицы зависят от контракта. ETF — цена в USD за акцию.')
    section('yieldcurve','BONDS','Кривая доходности',old('curve'),curve=True)
    section('spreads','BONDS','Спреды доходностей',old('curve','carry','ffr3m','stance'))
    section('realyields','BONDS','Реальные доходности',[p('real-'+k,t,k,'%') for k,t in [('DFII5','TIPS · 5Y'),('DFII10','TIPS · 10Y'),('DFII20','TIPS · 20Y'),('DFII30','TIPS · 30Y')]])
    section('nominal','BONDS','Номинальные доходности',[p('yield-'+k,t,k,'%') for k,t in [('DGS2','Treasury · 2Y'),('DGS5','Treasury · 5Y'),('DGS10','Treasury · 10Y'),('DGS30','Treasury · 30Y')]]+old('ffr'))
    section('worldstocks','EQUITIES','Мировые акции',[p('world-'+k,t,k,'USD') for k,t in [('VT','Весь мир · VT'),('EFA','Развитые рынки · EFA'),('EEM','Развивающиеся рынки · EEM')]],'ETF служат доступными прокси региональных рынков. Цена без учёта реинвестирования дивидендов.')
    section('usindices','EQUITIES','Индексы США',old('spy')+[p('us-'+k,t,k,'USD') for k,t in [('QQQ','Nasdaq 100 · QQQ'),('IWM','Russell 2000 · IWM'),('DIA','Dow Jones · DIA')]])
    section('sectors','EQUITIES','Секторы США',[p('sector-'+k,t+' · '+k,k,'USD') for k,t in [('XLK','Technology'),('XLF','Financials'),('XLE','Energy'),('XLV','Health Care'),('XLI','Industrials'),('XLP','Consumer Staples'),('XLY','Consumer Discretionary'),('XLU','Utilities'),('XLB','Materials'),('XLRE','Real Estate'),('XLC','Communication'),('SOXX','Semiconductors')]])
    section('earnings','EQUITIES','Корпоративные прибыли',[p('profits','Прибыль компаний США после налогов','CP','млрд $'),transformed('profits-yoy','Прибыль компаний · YoY','CP',4)],'BEA / FRED: прибыль всех американских корпораций после налогов, SAAR. Это не EPS индекса S&P 500.')
    return result
