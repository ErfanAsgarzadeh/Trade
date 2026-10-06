"""Store verified raw inputs and binary ledgers in Git-sized offline parts."""
from pathlib import Path
import hashlib,json,zipfile
ROOT=Path(__file__).resolve().parent.parent
def main():
 output=ROOT/'data_parts';output.mkdir(exist_ok=True);files=[]
 for folder in ['btc_backtest/cache','portfolio/cache','btc_backtest/output','optimization/output','archetypes/output','portfolio/output']:
  files += [p for p in (ROOT/folder).iterdir() if p.is_file() and p.suffix in ['.zip','.CHECKSUM','.npz','.png']]
 files.append(ROOT/'optimization/features.npz');temporary=output/'inputs_and_ledgers.zip.tmp'
 with zipfile.ZipFile(temporary,'w',zipfile.ZIP_STORED,allowZip64=True) as z:
  for p in sorted(files):z.write(p,p.relative_to(ROOT))
 parts=[];whole=hashlib.sha256();chunk_size=24*1024*1024
 with temporary.open('rb') as f:
  i=0
  while chunk:=f.read(chunk_size):
   name=f'inputs_and_ledgers.part{i:03d}';(output/name).write_bytes(chunk);whole.update(chunk);parts.append(dict(name=name,bytes=len(chunk),sha256=hashlib.sha256(chunk).hexdigest()));i+=1
 manifest=dict(format='Concatenated ZIP_STORED parts; python restore_data.py verifies and restores original paths',parts=parts,zip_sha256=whole.hexdigest(),zip_bytes=temporary.stat().st_size,members=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size) for p in sorted(files)])
 (output/'manifest.json').write_text(json.dumps(manifest,indent=2));temporary.unlink();print('PACKED',len(files),'members',len(parts),'parts',manifest['zip_bytes'],flush=True)
if __name__=='__main__':main()
