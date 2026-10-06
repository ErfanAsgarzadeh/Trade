"""Pack all 1152 audited period ledgers into hash-verified git-sized parts."""
from pathlib import Path
import hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1]
def main():
 dst=ROOT/'high_cagr/data_parts';dst.mkdir(exist_ok=True);files=sorted((ROOT/'high_cagr/output').glob('HC*.npz'));assert len(files)==1152
 archive=ROOT/'high_cagr/ledgers.zip';members=[]
 with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
  for p in files:
   members.append(dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()));z.write(p,str(p.relative_to(ROOT)))
 parts=[];overall=hashlib.sha256()
 with archive.open('rb') as f:
  i=0
  while True:
   b=f.read(8*1024*1024)
   if not b:break
   overall.update(b);name=f'ledgers.part{i:03d}';(dst/name).write_bytes(b);parts.append(dict(name=name,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()));i+=1
 manifest=dict(format='Concatenated ZIP_STORED with original NPZ members; restore_ledgers.py verifies hashes',parts=parts,members=members,zip_sha256=overall.hexdigest(),zip_bytes=archive.stat().st_size)
 (dst/'manifest.json').write_text(json.dumps(manifest,indent=2));print('PACKAGED',len(files),'ledgers',len(parts),'parts',archive.stat().st_size,flush=True)
if __name__=='__main__':main()
