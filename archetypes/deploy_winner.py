"""Apply only a candidate passing the user's three eligibility conditions."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT.parent/'lbank_project'))
from lbank_bot import ConfigStore
m=json.loads((ROOT/'output/matrix.json').read_text());winner=m['winner']
if not winner or winner['full']['trades']<40 or winner['train']['net_profit']<=0 or winner['oos']['net_profit']<=0:
    raise SystemExit('No eligible winner. Existing config is preserved.')
c=json.loads((ROOT/'output/winning_config.json').read_text())
ConfigStore(ROOT.parent/'lbank_project/config.json').write(c)
print('Applied eligible winner:',winner['id'])
