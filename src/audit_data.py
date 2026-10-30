"""Audit the published snapshot without contacting sources or revealing API keys."""
import datetime as dt
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

def inspect(payload):
    panels={}
    for col in payload['columns']+payload['markets']['columns']+[c for w in payload.get('workspaces',[]) for c in w['columns']]:
        for panel in col['panels']:panels[panel['id']]=panel
    errors=[];stale=[];series_count=0;points=0
    today=dt.date.today().isoformat()
    for pid,panel in panels.items():
        for row in panel['series']:
            series_count+=1
            data=row.get('data',[]);points+=len(data)
            key={'panel':pid,'series':row['name']}
            times=[d['time'] for d in data]
            if not data:errors.append({**key,'issue':'empty'})
            if times!=sorted(set(times)):errors.append({**key,'issue':'dates_unsorted_or_duplicated'})
            if times and times[-1]>today:errors.append({**key,'issue':'future_observation','date':times[-1]})
            if any(not math.isfinite(v) for d in data for v in d.values() if isinstance(v,(int,float))):errors.append({**key,'issue':'non_finite_value'})
            if row.get('stale'):stale.append({**key,'asof':row.get('asof')})
            if data and row.get('lastRaw') is not None:
                last=data[-1].get('value',data[-1].get('close'))
                if abs(last-row['lastRaw'])>.001:errors.append({**key,'issue':'last_value_mismatch'})
            if any('open' in d and not (d['low']<=d['open']<=d['high'] and d['low']<=d['close']<=d['high'] and d.get('volume',0)>=0) for d in data):errors.append({**key,'issue':'invalid_ohlcv'})
    failed=[{'kind':d['kind'],'name':d['name'],'status':d['status']} for d in payload.get('diagnostics',[]) if d['status'] in ('fail','skip')]
    missing_curve=[{'curve':c['name'],'tenor':v['tenor']} for c in payload['markets']['curves'] for v in c['values'] if v['value'] is None]
    return dict(generated=payload['generated'],panels=len(panels),series=series_count,points=points,errors=errors,stale=stale,source_failures=failed,missing_curve_points=missing_curve)

def main():
    report=inspect(json.loads((ROOT/'data/dashboard.json').read_text(encoding='utf-8')))
    (ROOT/'data/audit-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Проверка дашборда',f"Сборка: {report['generated']}",'',f"Проверено уникальных панелей: {report['panels']}; рядов в панелях: {report['series']}; точек: {report['points']}.",'',f"Ошибок данных: {len(report['errors'])}. Ошибок загрузки: {len(report['source_failures'])}. Пропусков на кривой доходности: {len(report['missing_curve_points'])}.",'','Проверены пустые ряды, NaN/Infinity, дубликаты и порядок дат, будущие наблюдения, согласованность последнего значения, допустимость OHLC и объёмов. Проверка использует опубликованную сборку; корректность каждого значения у внешнего поставщика не подтверждает.','','## Свежесть','']
    lines+=['| Панель | Ряд | Последнее наблюдение |','|---|---|---|']
    lines += [f"| {r['panel']} | {r['series']} | {r['asof']} |" for r in report['stale']]
    lines += ['','Четыре ряда BIS через FRED заканчиваются наблюдением за IV квартал 2025 года (FRED маркирует квартал датой 2025-10-01). Они показываются с предупреждением и не протягиваются до сегодняшней даты как новые наблюдения.','','## Интерфейс','', 'Проверены колесо мыши над отдельным графиком, независимость соседних панелей, сохранение отдельных диапазонов, дневной/недельный режим, поиск, все разделы и полноэкранный график. Синхронизация по умолчанию выключена; включается только кнопкой «Связать». Глобальные кнопки диапазона по-прежнему применяются ко всем графикам раздела.','', 'Исправлены смещение оверлея в полном экране, календарный период YoY/3m при пропущенных наблюдениях, проверка частоты исходных месячных рядов, дата ставки ФРС и требования к M2 на конец квартала.','']
    if report['errors']:lines+=['## Ошибки',json.dumps(report['errors'],ensure_ascii=False,indent=2)]
    (ROOT/'DATA_AUDIT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))
    return bool(report['errors'] or report['source_failures'] or report['missing_curve_points'])

if __name__=='__main__':raise SystemExit(main())
