"""Resume verified frozen inputs from committed ZIP parts, without redownloading Binance."""
from pathlib import Path
import json,struct,zlib,hashlib,urllib.request,concurrent.futures,time
ROOT=Path(__file__).resolve().parents[1];CACHE=ROOT.parents[1]/'utilization_check';CHUNK=8388608
BASE='https://raw.githubusercontent.com/ErfanAsgarzadeh/Trade/708571ba898ddfd473c2946b7a73526fa651ac70/'
def fetch(url):
 for attempt in range(4):
  try:return urllib.request.urlopen(url,timeout=45).read()
  except Exception:
   if attempt==3:raise
   time.sleep(attempt+1)
def main():
 CACHE.mkdir(parents=True,exist_ok=True);(ROOT/'high_cagr/output').mkdir(parents=True,exist_ok=True)
 manifest=json.loads(fetch(BASE+'data_parts/manifest.json'));(ROOT/'high_cagr/output/input_parts_manifest.json').write_text(json.dumps(manifest))
 last_index=len(manifest['parts'])-1;last_path=CACHE/f'part{last_index:03d}';meta=manifest['parts'][last_index]
 if not last_path.exists() or hashlib.sha256(last_path.read_bytes()).hexdigest()!=meta['sha256']:
  data=fetch(BASE+'data_parts/'+meta['name']);assert hashlib.sha256(data).hexdigest()==meta['sha256'];last_path.write_bytes(data)
 data=last_path.read_bytes();e=data.rfind(b'PK\x05\x06');count=struct.unpack_from('<H',data,e+10)[0];p=struct.unpack_from('<I',data,e+16)[0]-last_index*CHUNK;rows=[]
 for _ in range(count):
  assert data[p:p+4]==b'PK\x01\x02';crc,size=struct.unpack_from('<II',data,p+16);nl,el,cl=struct.unpack_from('<HHH',data,p+28);loc=struct.unpack_from('<I',data,p+42)[0];name=data[p+46:p+46+nl].decode();rows.append(dict(path=name,crc=crc,size=size,offset=loc));p+=46+nl+el+cl
 selected=[r for r in rows if r['path'].startswith('portfolio/cache/') and 'BNBUSDT' not in r['path']]
 parts=set()
 for r in selected:parts.update(range(r['offset']//CHUNK,(r['offset']+30+len(r['path'])+100+r['size'])//CHUNK+1))
 def download(i):
  p=CACHE/f'part{i:03d}';m=manifest['parts'][i]
  if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=m['sha256']:
   data=fetch(BASE+'data_parts/'+m['name']);assert hashlib.sha256(data).hexdigest()==m['sha256'];temp=p.with_suffix('.tmp');temp.write_bytes(data);temp.replace(p)
  print('VERIFIED PART',i,flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(download,sorted(parts)))
 def read(a,n):
  out=bytearray()
  while n:
   i,j=divmod(a,CHUNK)
   with (CACHE/f'part{i:03d}').open('rb') as f:f.seek(j);d=f.read(min(n,CHUNK-j))
   assert d;out.extend(d);a+=len(d);n-=len(d)
  return bytes(out)
 for r in selected:
  head=read(r['offset'],30);assert head[:4]==b'PK\x03\x04';nl,el=struct.unpack_from('<HH',head,26)
  data=read(r['offset']+30+nl+el,r['size']);assert zlib.crc32(data)==r['crc'];p=ROOT/r['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 for name in ['portfolio/output/data_manifest.json','portfolio/output/repair_manifest.json','portfolio/output/coverage.json']:
  p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(fetch(BASE+name))
 result=dict(restored_members=len(selected),verified_parts=len(parts),status='complete',source_commit='708571ba898ddfd473c2946b7a73526fa651ac70');(ROOT/'high_cagr/output/restore_checkpoint.json').write_text(json.dumps(result,indent=2));print(result,flush=True)
if __name__=='__main__':main()
