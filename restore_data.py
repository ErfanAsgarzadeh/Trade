"""Restore all archived minute data, funding, cached features and binary ledgers."""
from pathlib import Path
import json,hashlib,zipfile,sys
ROOT=Path(__file__).resolve().parent
def main():
 parts=ROOT/'data_parts';manifest=json.loads((parts/'manifest.json').read_text());temp=ROOT/'restore_archive.zip.tmp';whole=hashlib.sha256()
 with temp.open('wb') as f:
  for record in manifest['parts']:
   payload=(parts/record['name']).read_bytes()
   assert len(payload)==record['bytes'] and hashlib.sha256(payload).hexdigest()==record['sha256'],record['name']
   f.write(payload);whole.update(payload)
 assert whole.hexdigest()==manifest['zip_sha256'] and temp.stat().st_size==manifest['zip_bytes']
 with zipfile.ZipFile(temp) as z:
  for name in z.namelist():
   path=Path(name);assert not path.is_absolute() and '..' not in path.parts
  assert z.testzip() is None
  if '--check-only' not in sys.argv:z.extractall(ROOT)
 temp.unlink();print('Verified' if '--check-only' in sys.argv else 'Restored',len(manifest['members']),'verified binary/input files')
if __name__=='__main__':main()
