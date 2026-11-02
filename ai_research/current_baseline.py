"""Read-only version-pinned audit of newest three-bot rules and the F pilot.

No backtest is launched by this audit: it verifies already generated source-report
numbers and identifies which *different* historical ledger the earlier AI study
used. Verifying runtime ON status requires server read access (NOT provided).
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"ai_research"/"output"
BASE_COMMIT="623d3b1a4c57ce515444613471d2d87560db5cf1"
F_FROM="2022-01-01"

def load(relative):
    return json.loads((ROOT/relative).read_text())

def audit():
    c3=load("lbank_project/c3_config.json")
    sha=load("lbank_project/config.json")
    p=load("lbank_project/pa_config.json")
    w=load("high_cagr/output/ideas/winrate/final.json")
    f=load("high_cagr/output/ideas/frisk/result.json")["runs"]
    risk_gate=(ROOT/"lbank_project/risk_gate.py").read_text()
    overlay=(ROOT/"lbank_project/risk_overlay.py").read_text()
    for k,v in {
        "profit_lock_arm_r":1.0,"profit_lock_r":0.1,
        "partial_target_r":2.0,"partial_close_frac":0.5
    }.items():
        assert c3.get(k)==v,(k,c3.get(k),v)
    assert sha["strategy_settings"]["late_entry_filter_enabled"] is True
    assert sha["strategy_settings"]["late_entry_bars"]==60
    assert sha["strategy_settings"]["late_entry_max_log_move"]==0.1521
    assert p["strategy_variant"]=="C_exhaustion_soft"
    assert p["volume_multiplier"]==1.5
    assert 'DEFAULT = {"enabled": False' in risk_gate
    assert "SHADOW MODE service" in overlay
    assert (ROOT/"high_cagr/ideas/winrate/ledger.py").exists()
    assert (ROOT/"high_cagr/ideas/frisk/dd_engine.py").exists()
    assert (ROOT/"lbank_project/tests/test_c3_sleeve.py").exists()
    assert (ROOT/"lbank_project/tests/test_risk_gate.py").exists()
    baseline=w["shipped|x1"];new=w["final|x1"]
    assert baseline["trades"]==2875 and new["trades"]==2679
    assert new["win_rate"]["c3"]>baseline["win_rate"]["c3"]
    assert new["dd"]<baseline["dd"]
    keys={
      "no_f":f"from {F_FROM} | no F",
      "f_walk_forward":f"from {F_FROM} | F (walk-forward AI)",
      "f_shipped_in_sample":f"from {F_FROM} | F (shipped AI model, in-sample)",
      "f_without_ai":f"from {F_FROM} | F without AI (vol target + brake + streak)",
    }
    scores={k:{metric:float(f[v][metric]) for metric in ("cagr","dd","calmar")}
            |{"trades":int(f[v]["trades"])} for k,v in keys.items()}
    assert scores["f_walk_forward"]["dd"]>scores["no_f"]["dd"]  # less negative
    return {
      "source_ref":"claude/keen-noether-mbvppe",
      "source_commit":BASE_COMMIT,
      "source_pr":"https://github.com/ErfanAsgarzadeh/Trade/pull/17",
      "status":"verified static repo files + preexisting historical report artifacts",
      "server_runtime_status":"NOT_VERIFIED - control file on server inaccessible",
      "research_only":True,
      "bot_rules":{
        "Shahin":{"late_entry_enabled":True,"late_entry_bars":60,"late_entry_max_log_move":0.1521},
        "Mojsavar":{"profit_lock_arm_r":1.0,"profit_lock_r":0.1,"partial_target_r":2.0,"partial_close_frac":0.5},
        "Ghoghnous":{"strategy_variant":"C_exhaustion_soft","volume_multiplier":1.5},
        "F":{"default_enabled":False,"exists":True,"pilot_runtime_enabled":"unknown",
             "model":"market regime / account risk, not individual-trade filter"}
      },
      "new_rules_no_F_2021_2026":{
          "prior_rules":{"trades":baseline["trades"],"cagr_pct":baseline["cagr"],
                         "max_dd_pct":baseline["dd"],"win_pct":baseline["win_rate"]["all"]},
          "current_rules":{"trades":new["trades"],"cagr_pct":new["cagr"],
                           "max_dd_pct":new["dd"],"win_pct":new["win_rate"]["all"]}
      },
      "new_rules_F_comparison_2022_2026":scores,
      "historical_ai_filter_status":"Different outdated 2991-trade ledger; NOT current 2679-trade rules",
      "limitations":[
          "All values come from existing research reports, not independently rerun here.",
          "Server runtime F enabled state, current shadow decisions, PAPER positions and build versions not accessible.",
          "F shipped score model was trained on the full historical interval, so its backtest is in sample.",
          "The F historical 'walk-forward' 2022 fold uses data from 2023-26 due to insufficient earlier training; not clean OOS for 2022.",
          "Preexisting strategy/symbol research also saw much of the 2025-26 historical period.",
          "Reported CAGR and DD represent research engines and Binance data, not verified LBank paper account equity.",
          "Do not apply the old ledger AI predictions to the newly protected 2679-trade baseline.",
      ]
    }

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    r=audit()
    p=OUT/"current_baseline.json";p.write_text(json.dumps(r,ensure_ascii=False,indent=2))
    print(json.dumps({
      "source":r["source_commit"],"profit_lock":r["bot_rules"]["Mojsavar"],
      "baseline_2021_2026":r["new_rules_no_F_2021_2026"],
      "F_2022_2026":r["new_rules_F_comparison_2022_2026"],
      "runtime_status":r["server_runtime_status"]},ensure_ascii=False))
if __name__=="__main__":main()
