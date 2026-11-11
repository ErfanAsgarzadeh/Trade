#!/usr/bin/env python3
"""Read-only, allowlisted server inventory. No environment, logs, argv or mounts."""
import json
import os
from pathlib import Path
import re
import subprocess


def run(args):
    try:
        result=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=15)
        return result.returncode,result.stdout
    except (OSError,subprocess.SubprocessError):return -1,''


def number(value):
    try:return int(value)
    except (ValueError,TypeError):return None


def collect():
    report={'read_only':True,'credentials_used':False,'services_changed':False}
    memory={}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            name=line.split(':')[0]
            if name in ('MemTotal','MemAvailable','SwapTotal','SwapFree'):
                memory[name+'_mib']=round(int(line.split()[1])/1024,1)
    except (OSError,ValueError):pass
    report['memory']=memory
    report['cpu_count']=os.cpu_count()
    report['load']=list(os.getloadavg()) if hasattr(os,'getloadavg') else None
    processes=[]
    for folder in Path('/proc').iterdir():
        if not folder.name.isdigit():continue
        try:
            fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in (folder/'status').read_text().splitlines() if ':' in line}
            rss=int(fields.get('VmRSS','0 kB').split()[0])
            # Map comm to fixed categories; never print argv, users or arbitrary names.
            name=fields.get('Name','').lower()
            category=next((label for pattern,label in (('python','python'),('node','node'),('postgres','postgres'),('mysql','mysql'),('redis','redis'),('dockerd','docker-daemon'),('containerd','container-runtime'),('nginx','nginx'),('apache','apache')) if pattern in name),'other')
            processes.append({'pid':int(folder.name),'category':category,'rss_mib':round(rss/1024,1)})
        except (OSError,ValueError):continue
    report['largest_processes']=sorted(processes,key=lambda x:x['rss_mib'],reverse=True)[:12]
    code,out=run(['docker','ps','-aq','--no-trunc'])
    ids=[v for v in out.splitlines() if re.fullmatch('[a-f0-9]{12,64}',v)] if code==0 else []
    report['docker_accessible']=code==0
    containers=[]
    for index,identifier in enumerate(ids[:30],1):
        # Never request Config.Env, command line, labels, logs or mount locations.
        code,out=run(['docker','inspect','--format','{{.State.Running}} {{.State.OOMKilled}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}',identifier])
        values=out.strip().split() if code==0 else []
        state={'Running':values[0]=='true','OOMKilled':values[1]=='true','Status':values[2],
               'Health':{'Status':values[3]}} if len(values)==4 else {}
        code,out=run(['docker','inspect','--format','{{.RestartCount}} {{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}',identifier])
        limits=out.strip().split() if code==0 else []
        item={'number':index,'running':state.get('Running'),'oom_killed':state.get('OOMKilled'),
              'status':state.get('Status') if state.get('Status') in ('created','running','paused','restarting','removing','exited','dead') else 'UNKNOWN',
              'health':state.get('Health',{}).get('Status') if state.get('Health',{}).get('Status') in ('healthy','unhealthy','starting') else None,
              'restart_count':number(limits[0]) if len(limits)==3 else None,
              'memory_limit_bytes':number(limits[1]) if len(limits)==3 else None,
              'cpu_limit_nanocpus':number(limits[2]) if len(limits)==3 else None}
        code,out=run(['docker','stats','--no-stream','--format','{{json .}}',identifier])
        try:
            stats=json.loads(out) if code==0 else {}
            item['cpu_percent']=stats.get('CPUPerc') if re.fullmatch(r'[\d.]+%',str(stats.get('CPUPerc'))) else None
            item['memory_usage']=stats.get('MemUsage') if re.fullmatch(r'[\d.]+[A-Za-z]+ / [\d.]+[A-Za-z]+',str(stats.get('MemUsage'))) else None
        except ValueError:item['stats']='UNAVAILABLE'
        containers.append(item)
    report['containers']=containers
    report['container_mapping']='Numbers omit container names, images, logs and private metadata.'
    report['container_inventory_truncated']=len(ids)>30
    code,out=run(['systemctl','is-active','nginx','apache2','caddy'])
    report['web_services']={name:status if status in ('active','inactive','failed','unknown') else 'UNKNOWN' for name,status in zip(('nginx','apache2','caddy'),out.splitlines())}
    report['next_step']='Assess memory pressure and running workload before preparing an isolated release. No service was stopped.'
    return report


if __name__=='__main__':print(json.dumps(collect(),indent=2))
