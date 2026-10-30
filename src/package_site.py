"""Create the GitHub Pages entry from the verified standalone build."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent.parent

def main():
    page=(ROOT/'dashboard.html').read_text(encoding='utf-8')
    if '/*__DATA__*/' in page or '/*__RESEARCH__*/' in page:
        raise RuntimeError('Dashboard must be built before publication')
    keyfile=ROOT/'fred_key.txt'
    if keyfile.exists():
        keys=[line.strip() for line in keyfile.read_text(encoding='utf-8').splitlines() if line.strip() and not line.lstrip().startswith('#')]
        if any(len(key)>8 and key in page for key in keys):raise RuntimeError('Credential detected in published page')
    (ROOT/'index.html').write_text(page,encoding='utf-8')
    print('GitHub Pages entry prepared; credential scan passed.')

if __name__=='__main__':main()
