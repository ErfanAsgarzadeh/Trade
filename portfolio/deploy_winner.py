"""Apply only verified eligible winner; keep paper mode and snapshot prior files."""
from pathlib import Path
import sys,json,shutil
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'lbank_project'))
import lbank_bot as bot
def main():
 d=json.loads((ROOT/'output/matrix.json').read_text());v=json.loads((ROOT/'output/verification.json').read_text());winner=d['winner']
 if winner is None:print('No eligible portfolio; prior config retained');return
 assert winner['eligible'] and v['passed'] and v['eligible_winner']
 assert all(winner[p]['max_dd_pct']<=25 for p in ['full','train','oos']) and winner['train']['net_profit']>0 and winner['oos']['net_profit']>0
 c=bot.validate_config(json.loads((ROOT/'output/winning_config.json').read_text()));assert c['bot_control']['dry_run_mode']
 backup=ROOT/'prior';backup.mkdir(exist_ok=True)
 for name in ['config.json','lbank_bot.py','strategy_archetypes.py']:
  source=ROOT.parent/'trade_master/lbank_project'/name
  if not (backup/name).exists():shutil.copy2(source if source.exists() else ROOT.parent/'lbank_project'/name,backup/name)
 bot.ConfigStore(ROOT.parent/'lbank_project/config.json').write(c)
 print('APPLIED',winner['id'],flush=True)
if __name__=='__main__':main()
