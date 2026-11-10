#!/usr/bin/env python3
"""Collect missing live-review SOURCE files, not secrets, databases or pilot state.

No Docker execution, network, service change, API call, or config/journal write.
The resulting archive is recovery material, never an executable live release.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile

SOURCES={
 'exchanges.py','live_mirror.py','live_risk.py','ttt_live_readiness.py',
 'live_server_preflight.py','ttt_pilot_plan.py','ttt_lifecycle_pilot.py',
 'ttt_pilot_binding.py','ttt_pilot_reconcile.py','ttt_pilot_evidence.py',
 'ttt_read_consistency.py','ttt_final_checks.py','driver.py',
 'test_ttt_final_checks.py','test_ttt_adapter_stop_readback.py','test_ttt_http_diagnostics.py',
 'test_ttt_lifecycle_pilot.py','test_ttt_minimum_value.py','test_ttt_pilot_binding.py',
 'test_ttt_pilot_evidence.py','test_ttt_pilot_plan.py','test_ttt_pilot_reconcile.py',
 'test_ttt_read_consistency.py',
}
REQUIRED={'live_risk.py','ttt_lifecycle_pilot.py','ttt_pilot_binding.py',
          'ttt_pilot_reconcile.py','ttt_pilot_evidence.py','ttt_read_consistency.py','ttt_final_checks.py'}
EXCLUDED={'runtime','data','ohlcv','funding','node_modules','.git','.venv','venv',
          '__pycache__','issuer-keys','customers','frontend','releases','models'}


def eligible(path):
    lower=path.name.lower()
    return path.name in SOURCES or (lower.endswith('.pdf') and ('thetruetrade' in lower or 'api reference' in lower))


def collect(root,destination):
    root=Path(root).resolve();destination=Path(destination)
    if not (root/'live_mirror.py').is_file():raise ValueError('Expected lbank_project directory')
    members={};missing=set(REQUIRED);pdf=False;truncated=False
    # Prune mutable/sensitive and large data directories, do not traverse symlinks.
    for directory,dirs,files in os.walk(root,followlinks=False):
        directory=Path(directory)
        dirs[:]=sorted(d for d in dirs if d not in EXCLUDED and not d.startswith('.')
                       and not (directory/d).is_symlink()) if len(directory.relative_to(root).parts)<8 else []
        for name in sorted(files):
            path=directory/name
            if not eligible(path) or path.is_symlink():continue
            if len(members)>=100:truncated=True;continue
            limit=20_000_000 if path.suffix.lower()=='.pdf' else 2_000_000
            if path.stat().st_size>limit:truncated=True;continue
            content=path.read_bytes()
            members[path.relative_to(root).as_posix()]=content
            missing.discard(path.name)
            pdf=pdf or path.suffix.lower()=='.pdf'
    manifest=dict(schema=1,created_utc=datetime.now(timezone.utc).isoformat(),
                  purpose='source_recovery_only_not_live_release',orders_sent=False,
                  services_changed=False,live_enabled_by_this_tool=False,
                  environment_or_journal_collected=False,source_versions_not_assumed_current=True,
                  missing_source_names=sorted(missing),api_reference_found=pdf,
                  collection_truncated=truncated,
                  files={name:hashlib.sha256(data).hexdigest() for name,data in sorted(members.items())})
    members['recovery-manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    with destination.open('xb') as stream:
        with tarfile.open(fileobj=stream,mode='w:gz') as archive:
            for name,content in sorted(members.items()):
                info=tarfile.TarInfo('live-source-recovery/'+name)
                info.size=len(content);info.mode=0o600
                archive.addfile(info,io.BytesIO(content))
    destination.chmod(0o600)
    return dict(archive=str(destination),source_files=len(members)-1,
                missing_source_names=sorted(missing),api_reference_found=pdf,
                orders_sent=False,services_changed=False,
                note='Upload recovery archive for code review. Do not execute recovered pilots.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path('/opt/Trade/lbank_project'))
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        if args.output:destination=args.output
        else:
            directory=Path(tempfile.mkdtemp(prefix='trade-live-recovery-'));directory.chmod(0o700)
            destination=directory/'live-source-recovery.tar.gz'
        result=collect(args.project,destination)
    except (OSError,ValueError):
        result={'status':'RECOVERY_NOT_COMPLETED','orders_sent':False,'services_changed':False}
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
