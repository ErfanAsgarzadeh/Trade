"""Package deliverables without credentials, database state or test temporaries."""
from pathlib import Path
import zipfile,json
ROOT=Path(__file__).resolve().parent.parent
project=ROOT/'lbank_project'
project_files=[p for p in project.iterdir() if p.is_file() and (p.suffix in ['.py','.json','.txt','.yml','.md'] or p.name in ['Dockerfile','.env.example','.dockerignore','.gitignore'])]
project_files += [p for p in (project/'tests').iterdir() if p.is_file() and p.suffix in ['.py','.cjs','.json']]
files=list(project_files)
files += [p for p in (ROOT/'optimization').iterdir() if p.is_file() and p.suffix in ['.py','.md','.txt','.json','.npz']]
files += [p for p in (ROOT/'optimization/baseline').iterdir() if p.is_file() and p.suffix in ['.py','.json']]
files += [p for p in (ROOT/'optimization/output').iterdir() if p.is_file()]
files += [p for p in (ROOT/'btc_backtest').iterdir() if p.is_file() and p.suffix in ['.py','.txt']]
files += [p for p in (ROOT/'btc_backtest/output').iterdir() if p.is_file() and p.suffix in ['.json','.md','.png','.html']]
for filename,selected in [('lbank_futures_paper_bot.zip',project_files),('btc_optimization_suite.zip',files)]:
    with zipfile.ZipFile(ROOT/filename,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in selected:z.write(p,p.relative_to(ROOT),compress_type=zipfile.ZIP_STORED if p.suffix=='.npz' else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(ROOT/filename) as z:
        assert z.testzip() is None
        assert all('pytest-of-root' not in p and '__pycache__' not in p and not p.endswith('.db') for p in z.namelist())
        config=json.loads(z.read('lbank_project/config.json'))
        assert config['strategy_mode']['mode']=='SINGLE'
    print(filename,(ROOT/filename).stat().st_size)
