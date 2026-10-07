"""Download + prepare the holdout symbols with exactly the stage-2 code path."""
from pathlib import Path
import sys,json,concurrent.futures
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import stage2_data as d
def main():
    chosen=[c['symbol'] for c in json.loads((d.OUT/'stage3_selection.json').read_text())['chosen']]
    rels=[r for s in chosen for r in d.files(s)];manifest=[]
    with concurrent.futures.ThreadPoolExecutor(12) as pool:
        for k,(rel,sha,_) in enumerate(pool.map(d.fetch,rels)):
            manifest.append(dict(file=rel,sha256=sha))
            if k%200==0:print('verified',k,'/',len(rels),flush=True)
    (d.OUT/'stage3_data_manifest.json').write_text(json.dumps(manifest,indent=0));infos=[]
    for s in chosen:
        info=d.prepare(s,manifest);infos.append(info);print('PREPARED',s,'missing',info['missing_minutes_in_test'],f"({info['missing_fraction']*100:.3f}%)",flush=True)
    (d.OUT/'stage3_coverage.json').write_text(json.dumps(infos,indent=1))
if __name__=='__main__':main()
