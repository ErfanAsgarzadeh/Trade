"""Verify and restore every saved period ledger from committed parts."""
from pathlib import Path
import hashlib,json,zipfile,tempfile
ROOT=Path(__file__).resolve().parents[1]
def main():
 dst=ROOT/'high_cagr/data_parts';manifest=json.loads((dst/'manifest.json').read_text());overall=hashlib.sha256()
 with tempfile.TemporaryFile(dir=ROOT/'high_cagr') as f:
  for part in manifest['parts']:
   b=(dst/part['name']).read_bytes();assert len(b)==part['bytes'] and hashlib.sha256(b).hexdigest()==part['sha256'];overall.update(b);f.write(b)
  assert overall.hexdigest()==manifest['zip_sha256'];f.seek(0)
  with zipfile.ZipFile(f) as z:
   for row in manifest['members']:
    p=ROOT/row['path'];assert p.resolve().is_relative_to((ROOT/'high_cagr/output').resolve());b=z.read(row['path']);assert len(b)==row['bytes'] and hashlib.sha256(b).hexdigest()==row['sha256'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
 print('Restored',len(manifest['members']),'audited ledgers')
if __name__=='__main__':main()
