"""Owner-scoped execution readiness, never an authorization to send orders."""
import math
import time


def readiness(connection,entitlement,now=None):
    now=time.time() if now is None else now
    account=(connection or {}).get('account') or {}
    snapshot=account.get('snapshot') or {}
    checked=account.get('checked_at')
    fresh=(isinstance(checked,(float,int)) and not isinstance(checked,bool)
           and math.isfinite(checked) and 0<=now-checked<=300)
    checks=dict(autotrade_license=(entitlement.get('product')=='autotrade'
                                   and entitlement.get('entries_allowed') is True),
                thetruetrade_futures=(connection.get('configured') is True
                    and connection.get('exchange_id')=='thetruetrade' and connection.get('market')=='futures'),
                account_read_verified=(fresh and account.get('status')=='verified_read_only'
                    and snapshot.get('exchange_id')=='thetruetrade' and snapshot.get('market')=='futures'))
    blockers=[]
    if not checks['autotrade_license']:blockers.append('AUTOTRADE_LICENSE_REQUIRED')
    if not checks['thetruetrade_futures']:blockers.append('THETRUETRADE_FUTURES_CONNECTION_REQUIRED')
    if not checks['account_read_verified']:blockers.append('RECENT_ACCOUNT_VERIFICATION_REQUIRED')
    # These are actual implementation gaps, not configurable switches.
    blockers.extend(('EXCHANGE_ACCOUNT_LICENSE_BINDING_NOT_VERIFIED',
                     'CUSTOMER_EXECUTOR_NOT_PROVISIONED','PROTECTED_LIVE_EXECUTION_NOT_VALIDATED'))
    status=('signals_only' if entitlement.get('product')=='signals' else
            'license_required' if not checks['autotrade_license'] else
            'connection_required' if not checks['thetruetrade_futures'] else
            'verification_required' if not checks['account_read_verified'] else 'integration_pending')
    return dict(status=status,exchange_id='thetruetrade',live_execution_supported=False,
                trading_enabled=False,checks=checks,blockers=blockers)
