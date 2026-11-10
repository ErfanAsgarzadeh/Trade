from tools import server_inventory as inventory


def test_inventory_only_returns_allowlisted_container_fields(monkeypatch):
    calls=[]
    def run(args):
        calls.append(args)
        if args[1:3]==['ps','-aq']:return 0,'a'*64+'\n'
        if 'inspect' in args and '.State.Running' in args[3]:return 0,'true false running healthy\n'
        if 'inspect' in args:return 0,'2 536870912 1000000000\n'
        if 'stats' in args:return 0,'{"CPUPerc":"2.5%","MemUsage":"100MiB / 512MiB","Name":"PRIVATE_NAME","ID":"PRIVATE_ID"}'
        return 0,'inactive\ninactive\nactive\n'
    monkeypatch.setattr(inventory,'run',run)
    result=inventory.collect();container=result['containers'][0]
    assert container['running'] is True and container['health']=='healthy'
    assert container['memory_limit_bytes']==536870912
    assert container['memory_usage']=='100MiB / 512MiB'
    assert 'PRIVATE' not in str(result)
    assert not any('Config.Env' in str(c) or '{{json .State}}' in str(c) for c in calls)
