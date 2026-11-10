import json
import tarfile
import pytest
from tools.collect_live_handoff import collect


def test_recovers_sources_but_not_env_journals_runtime_or_symlinks(tmp_path):
    project=tmp_path/'project';project.mkdir()
    for name in ('live_mirror.py','ttt_pilot_binding.py','live_risk.py'):(project/name).write_text('# source\n')
    (project/'.env').write_text('API_SECRET=PRIVATE')
    (project/'runtime').mkdir();(project/'runtime/ttt_final_checks.py').write_text('PRIVATE_RUNTIME')
    (project/'pilot_journal.json').write_text('PRIVATE_JOURNAL')
    (project/'live-final-check').mkdir()
    (project/'live-final-check/ttt_pilot_reconcile.py').write_text('# reconcile')
    (project/'ttt_final_checks.py').symlink_to(project/'.env')
    (project/'API reference TheTrueTrade.pdf').write_bytes(b'pdf fixture')
    target=tmp_path/'recovery.tar.gz';result=collect(project,target)
    with tarfile.open(target) as stream:
        content=b''.join(stream.extractfile(m).read() for m in stream.getmembers())
        manifest=json.loads(stream.extractfile('live-source-recovery/recovery-manifest.json').read())
    assert b'PRIVATE' not in content
    assert result['source_files']==5 and result['api_reference_found']
    assert 'ttt_final_checks.py' in result['missing_source_names']
    assert manifest['environment_or_journal_collected'] is False
    assert not result['services_changed'] and not result['orders_sent']
    assert target.stat().st_mode & 0o777==0o600
    with pytest.raises(FileExistsError):collect(project,target)
