"""One-command data refresh, validation and publication to the existing origin/main."""
from __future__ import annotations
import argparse
import datetime as dt
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import webbrowser

ROOT=Path(__file__).resolve().parent.parent
PUBLIC_FILES=('index.html','DATA_AUDIT.md','data/audit-report.json')
SITE='https://alexvispio-hue.github.io/us-macro-dashboard/'

class UpdateError(RuntimeError):pass

def command(args, capture=False, allowed=(0,)):
    result=subprocess.run(args,cwd=ROOT,text=True,encoding='utf-8',errors='replace',
        stdout=subprocess.PIPE if capture else None,stderr=subprocess.PIPE if capture else None)
    if result.returncode not in allowed:
        detail=(result.stderr or result.stdout or '').strip() if capture else ''
        raise UpdateError('Команда завершилась с ошибкой: '+args[0]+(' · '+detail if detail else ''))
    return result

def git(*args,capture=True,allowed=(0,)):
    return command(['git',*args],capture=capture,allowed=allowed)

def preflight(fetch=False):
    if git('branch','--show-current').stdout.strip()!='main':
        raise UpdateError('Публикация разрешена только из ветки main. Текущая ветка не изменена.')
    allowed=set(PUBLIC_FILES)
    for args in [('diff','--cached','--name-only'),('diff','--name-only')]:
        extra=set(git(*args).stdout.splitlines())-allowed
        if extra:
            raise UpdateError('Сначала сохраните изменения исходников отдельным коммитом: '+', '.join(sorted(extra)))
    git('remote','get-url','origin')
    if fetch:
        git('fetch','origin','main',capture=False)
        if git('merge-base','--is-ancestor','origin/main','HEAD',allowed=(0,1)).returncode:
            raise UpdateError('На GitHub есть изменения, которых нет локально. Попросите Codex синхронизировать проект. Ничего не перезаписано.')

def install_dependencies():
    for name,minimum in [('pandas',(2,2)),('requests',(2,31))]:
        try:
            version=importlib.metadata.version(name)
            numbers=tuple(int(n) for n in re.findall(r'\d+',version)[:2])
            if numbers<minimum:raise importlib.metadata.PackageNotFoundError(name)
        except importlib.metadata.PackageNotFoundError:
            print('Устанавливаю зависимости проекта...',flush=True)
            command([sys.executable,'-m','pip','install','-r','requirements.txt'])
            return

def validate_fallbacks(payload):
    failed=[d['name'] for d in payload.get('diagnostics',[]) if d['status'] in ('fail','skip')]
    cached=[d['name'] for d in payload.get('diagnostics',[]) if d['status']=='cache' and re.search('сеть упала|старый кэш|старого кэша',d.get('detail',''),re.I)]
    if failed or cached:
        raise UpdateError('Часть источников не обновилась: '+', '.join(sorted(set(failed+cached)))+'. Предыдущая опубликованная версия сохранена. Повторите запуск, когда восстановится доступ к источникам.')

def prepare(offline=False):
    install_dependencies()
    print('\n[1/4] Загрузка данных и сборка...',flush=True)
    command([sys.executable,'src/build.py','--offline' if offline else '--refresh'])
    print('\n[2/4] Проверка данных...',flush=True)
    command([sys.executable,'src/audit_data.py'])
    payload=json.loads((ROOT/'data/dashboard.json').read_text(encoding='utf-8'))
    validate_fallbacks(payload)
    print('\n[3/4] Подготовка сайта и проверка ключей...',flush=True)
    command([sys.executable,'src/package_site.py'])

def publish():
    # Check again after the download: never include concurrently staged source edits.
    preflight()
    git('add','--',*PUBLIC_FILES,capture=False)
    changed=git('diff','--cached','--quiet','--',*PUBLIC_FILES,allowed=(0,1)).returncode==1
    if changed:
        message='Update dashboard data '+dt.datetime.now().astimezone().isoformat(timespec='minutes')
        git('commit','--only','-m',message,'--',*PUBLIC_FILES,capture=False)
    else:
        print('Файлы публикации уже актуальны; новый коммит не нужен.',flush=True)
    git('push','origin','main',capture=False)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Проверить Git без загрузки и публикации')
    parser.add_argument('--prepare-only',action='store_true',help='Собрать и проверить, без коммита и push')
    parser.add_argument('--offline',action='store_true',help='Только совместно с --prepare-only: проверка из кэша')
    parser.add_argument('--no-open',action='store_true',help='Не открывать сайт в браузере')
    parser.add_argument('--no-pause',action='store_true',help='Для запуска батника без паузы')
    args=parser.parse_args(argv)
    if args.offline and not args.prepare_only:
        parser.error('--offline разрешён только с --prepare-only, чтобы не публиковать кэш как обновлённые данные')
    try:
        if args.check:
            preflight()
            print('Git: main, origin настроен, посторонних изменений для коммита нет. Проверка пройдена.')
            return 0
        if not args.prepare_only:
            preflight(fetch=True)
        prepare(offline=args.offline)
        if args.prepare_only:
            print('\nСборка проверена. GitHub не изменён.')
            return 0
        print('\n[4/4] Сохранение версии и отправка на GitHub...',flush=True)
        publish()
        print('\nГотово: обновление отправлено в GitHub. Развёртывание Pages обычно занимает несколько минут.')
        print('До завершения развёртывания сайт может показывать предыдущую сборку. Затем обновите страницу Ctrl+F5.')
        print(SITE)
        if not args.no_open:webbrowser.open(SITE)
        return 0
    except (UpdateError,OSError,ValueError) as exc:
        print('\nОБНОВЛЕНИЕ ОСТАНОВЛЕНО: '+str(exc),file=sys.stderr)
        print('Файлы и история Git не удалены. Подробности загрузки: last_run.log.',file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nОбновление прервано пользователем.',file=sys.stderr)
        return 130

if __name__=='__main__':raise SystemExit(main())
