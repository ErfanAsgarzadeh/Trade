#!/usr/bin/env python3
"""Standalone, GET-only TheTrueTrade contract probe; no raw account data in output."""
import argparse
import getpass
import hashlib
import hmac
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE='https://apiv2.thetruetrade.io'
SYMBOLS=('BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT')
ROUTES=(('/futures/assets',None),('/futures/markets',None),
        ('/futures/positions',{'active':'true'}),('/futures/positions',{'page':1}))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def get(key,secret,path,query=None,opener=None):
    if (path,query) not in ROUTES:raise ValueError('Unapproved read route')
    uri=path+('?' + urllib.parse.urlencode(query) if query else '')
    stamp=str(int(time.time()*1000))
    signature=hmac.new(secret.encode(),f'{stamp}GET{uri}'.encode(),hashlib.sha256).hexdigest()
    headers={'Accept':'application/json','User-Agent':'Trade-contract-probe/1'}
    if path!='/futures/markets':headers.update({'X-API-Key':key,'X-Timestamp':stamp,'X-Signature':signature})
    request=urllib.request.Request(BASE+uri,method='GET',headers=headers)
    with (opener or urllib.request.build_opener(NoRedirect())).open(request,timeout=10) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('Oversized response')
    return json.loads(raw)


def positive(value):
    if isinstance(value,bool):return False
    try:return math.isfinite(float(value)) and float(value)>0
    except (ValueError,TypeError,OverflowError):return False


def rows(document):
    if isinstance(document,list):return document
    if isinstance(document,dict):
        for field in ('items','positions','data','results'):
            if isinstance(document.get(field),list):return document[field]
    return None


def summarize(document,kind):
    if kind=='assets':
        summary=document.get('summary') if isinstance(document,dict) else None
        return {'recognized_summary':isinstance(summary,dict),
                'equity_field_reported':isinstance(summary,dict) and summary.get('totalAssets') is not None,
                'available_margin_field_reported':isinstance(summary,dict) and summary.get('availableBalance') is not None}
    records=rows(document)
    if records is None or not all(isinstance(row,dict) for row in records):return {'recognized_list':False}
    if kind=='markets':
        return {symbol:{'reported':any(r.get('symbol')==symbol for r in records),
                        **{field:any(r.get('symbol')==symbol and positive(r.get(field)) for r in records)
                           for field in ('stepSize','tickSize','minOrderSize','minOrderValue','maxLeverage')}} for symbol in SYMBOLS}
    meta=document.get('meta') if isinstance(document,dict) else None
    active=[r for r in records if str(r.get('status','')).upper() in ('OPEN','OPENED') or r.get('isActive') is True]
    return {'recognized_list':True,'records_returned':len(records),'active_records_returned':len(active),
            'pagination_metadata_reported':isinstance(meta,dict),
            'another_page_reported':bool(isinstance(meta,dict) and (meta.get('hasNext') or meta.get('hasNextPage') or meta.get('nextCursor'))),
            'active_with_saved_sl':sum(positive(r.get('stopLoss')) for r in active),
            'active_with_sl_reference':sum(isinstance(r.get('slOrderId'),(str,int)) and not isinstance(r.get('slOrderId'),bool) and bool(str(r['slOrderId']).strip()) for r in active),
            'stop_execution_verified':False}


def probe(key,secret,opener=None):
    report={'schema':1,'read_only':True,'orders_sent':False,'live_trading_authorized':False,'checks':{}}
    for label,(path,query) in zip(('assets','markets','active_positions','full_positions'),ROUTES):
        try:
            data=get(key,secret,path,query,opener)
            report['checks'][label]={'http_get':'ok','summary':summarize(data,'positions' if 'positions' in label else label)}
        except urllib.error.HTTPError as exc:report['checks'][label]={'http_status':exc.code}
        except Exception as exc:report['checks'][label]={'status':'failed','error_type':type(exc).__name__}
    report['conclusion']='READ_ONLY_EVIDENCE_ONLY_NOT_LIVE_AUTHORIZATION'
    report['not_verified']=['withdrawal_permission_disabled','account_license_identity_binding',
                            'new_entry_protective_stop_lifecycle','stop_move_and_partial_fill_recovery',
                            'complete_position_pagination','customer_executor_provisioning']
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-env',action='store_true',help='Explicitly use TTT_API_KEY/TTT_API_SECRET from this process')
    args=parser.parse_args()
    try:
        if args.from_env:key,secret=os.getenv('TTT_API_KEY',''),os.getenv('TTT_API_SECRET','')
        else:
            # Refuse getpass's echoing fallback if no controlling terminal exists.
            tty=os.open('/dev/tty',os.O_RDWR);os.close(tty)
            key=getpass.getpass('TheTrueTrade API key (hidden, local SSH terminal): ')
            secret=getpass.getpass('TheTrueTrade API secret (hidden, local SSH terminal): ')
        if not key.strip() or not secret.strip():raise ValueError('Missing credentials')
        result=probe(key.strip(),secret.strip())
    except (OSError,ValueError,EOFError,KeyboardInterrupt):
        result={'read_only':True,'orders_sent':False,'live_trading_authorized':False,
                'conclusion':'NOT_RUN_LOCAL_TERMINAL_AND_READ_CREDENTIALS_REQUIRED'}
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
