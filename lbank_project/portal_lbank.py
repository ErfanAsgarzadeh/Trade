"""Read-only LBank account adapter. Never route futures credentials to spot implicitly."""
import math

import ccxt


class FuturesNotValidated(Exception):pass


class LBankAccountReader:
    def snapshot(self, connection):
        if connection['market'] != 'spot':
            raise FuturesNotValidated('Private futures adapter has not been validated')
        exchange=ccxt.lbank(dict(apiKey=connection['api_key'],secret=connection['secret'],
                                 enableRateLimit=True,timeout=10000))
        # Explicit spot endpoint: no markets download, no hidden swap->spot routing.
        response=exchange.spotPrivatePostSupplementUserInfoAccount({})
        data=response.get('data',{})
        if response.get('result') not in (True,'true') or not isinstance(data.get('balances'),list):
            raise ValueError('Unexpected account response')
        balances=[]
        for item in data['balances']:
            free=float(item['free']);locked=float(item['locked'])
            if not math.isfinite(free) or not math.isfinite(locked):raise ValueError('Invalid balance')
            if free or locked:
                balances.append(dict(asset=str(item['asset']).upper(),free=free,locked=locked,total=free+locked))
        # Raw exchange payload/permissions/API echoes never leave this adapter.
        return dict(market='spot',balances=balances)
