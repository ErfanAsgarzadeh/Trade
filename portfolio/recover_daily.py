from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import json,importlib.util
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('download',ROOT/'download_data.py');download=importlib.util.module_from_spec(spec);spec.loader.exec_module(download)
def main():
 issues=json.loads((ROOT/'output/coverage_issues.json').read_text());jobs=[]
 for issue in issues:
  for day in issue['dates']:
   s=issue['symbol'];name=f'{s}-1m-{day}.zip';jobs.append((s,name,download.BASE+f'daily/klines/{s}/1m/{name}'))
 results=[]
 with ThreadPoolExecutor(max_workers=8) as pool:
  for f in as_completed([pool.submit(download.fetch,job,{}) for job in jobs]):
   row=f.result();results.append(row);download.atomic(ROOT/'output/repair_manifest.json',results);print(row['name'],row['status'],row.get('error',''),flush=True)
 if any(x['status']!='verified' for x in results):raise SystemExit(1)
if __name__=='__main__':main()
