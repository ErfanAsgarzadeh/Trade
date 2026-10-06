"""Package current code, reproducible cached data, results and historical baselines."""
from pathlib import Path
import zipfile,json
ROOT=Path(__file__).resolve().parent.parent
project=ROOT/'lbank_project'
project_files=[p for p in project.iterdir() if p.is_file() and (p.suffix in ['.py','.json','.txt','.yml','.md'] or p.name in ['Dockerfile','.env.example','.dockerignore','.gitignore'])]
project_files += [p for p in (project/'tests').iterdir() if p.is_file() and p.suffix in ['.py','.cjs','.json']]
files=list(project_files)
for folder in ['archetypes','archetypes/prior','archetypes/output','optimization','optimization/baseline','optimization/output','btc_backtest','btc_backtest/output']:
    directory=ROOT/folder
    for p in directory.iterdir():
        if p.is_file() and p.suffix in ['.py','.md','.txt','.json','.npz','.html','.png','.log','.js']:
            files.append(p)
for filename,selected in [('lbank_futures_paper_bot.zip',project_files),('btc_archetypes_benchmark.zip',files)]:
    with zipfile.ZipFile(ROOT/filename,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in selected:z.write(p,p.relative_to(ROOT),compress_type=zipfile.ZIP_STORED if p.suffix=='.npz' else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(ROOT/filename) as z:
        assert z.testzip() is None
        assert all('__pycache__' not in n and 'pytest-of-root' not in n and not n.endswith('.db') for n in z.namelist())
        config=json.loads(z.read('lbank_project/config.json'))
        assert config['archetype_strategy']['family']=='DONCHIAN'
        assert 'lbank_project/strategy_archetypes.py' in z.namelist()
    print(filename,(ROOT/filename).stat().st_size)
