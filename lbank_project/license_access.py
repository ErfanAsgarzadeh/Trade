"""Offline signed customer licenses. Expiry blocks entries, never position exits.

This is access control for managed distributions, not tamper-proof DRM for public source.
Issuer private keys must never be shipped with a customer installation.
"""
from __future__ import annotations

import base64
from datetime import datetime
import json
import os
from pathlib import Path
import time
import math

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def timestamp(value: str) -> float:
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('License timestamps require a timezone')
    return dt.timestamp()


def verify_document(document: str, public_key: bytes) -> dict:
    """Verify issuer signature before inspecting or installing a license."""
    if len(document.encode('utf-8')) > 16384:
        raise ValueError('License too large')
    envelope = json.loads(document)
    if set(envelope) != {'payload', 'signature'}:
        raise ValueError('Invalid license envelope')
    key = serialization.load_pem_public_key(public_key)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError('Expected Ed25519 issuer')
    key.verify(base64.b64decode(envelope['signature'], validate=True), canonical(envelope['payload']))
    return envelope['payload']


def status(now: float | None = None, initial_capital: float | None = None) -> dict:
    now = time.time() if now is None else now
    required = os.getenv('BOT_LICENSE_REQUIRED', '0') == '1'
    license_path = os.getenv('BOT_LICENSE_FILE', '')
    key_path = os.getenv('BOT_LICENSE_PUBLIC_KEY_FILE', '')
    if not required and not license_path and not key_path:
        return dict(state='development', entries_allowed=True, customer_id=None,
                    plan=None, expires_at=None)
    result = dict(state='invalid', entries_allowed=False, customer_id=None,
                  plan=None, expires_at=None)
    try:
        customer = os.environ['BOT_CUSTOMER_ID']
        path = Path(license_path)
        if not license_path or not key_path or path.stat().st_size > 16384:
            return result
        payload = verify_document(path.read_text(encoding='utf-8'), Path(key_path).read_bytes())
        if payload['schema'] not in (1, 2):return result
        if payload['customer_id'] != customer:
            return result
        issued = timestamp(payload['issued_at'])
        start = timestamp(payload['not_before'])
        end = timestamp(payload['expires_at'])
        if not isinstance(payload['plan'], str) or not start < end or issued >= end:
            return result
        if payload['schema'] == 1 and not issued <= start:return result
        if payload['schema'] == 2:
            from capital_plans import money, price_cents
            cap = payload['cap_usd']
            price_cents(cap, payload['months'])
            funded = money(payload['funded_capital_usd'])
            activation = money(payload['capital_at_activation_usd'], positive=True)
            if activation > cap or payload['bots'] != ['main', 'c3', 'pa']:
                return result
            binding_file = os.getenv('BOT_LICENSE_ACCOUNT_ID_FILE')
            bound_account = Path(binding_file).read_text().strip() if binding_file else os.getenv('BOT_LICENSE_ACCOUNT_ID')
            if payload['account_id'] != bound_account:
                return result
            grace = payload['grace_ends_at']
            if funded > cap and (not grace or timestamp(grace) < issued):return result
            result.update(cap_usd=cap, months=payload['months'], account_id=payload['account_id'],
                          capital_at_activation_usd=str(activation), funded_capital_usd=str(funded),
                          grace_ends_at=grace)
        result.update(customer_id=customer, plan=payload['plan'], expires_at=payload['expires_at'])
        result['state'] = 'not_yet_valid' if now < start else 'expired' if now >= end else 'active'
        result['entries_allowed'] = result['state'] == 'active'
        if payload['schema'] == 2 and result['entries_allowed']:
            if funded > cap:
                result['state'] = 'grace' if now < timestamp(grace) else 'capital_exceeded'
                result['entries_allowed'] = result['state'] == 'grace'
            # Verify the immutable paper seed, not current equity: trading profits are exempt.
            seed = initial_capital if initial_capital is not None else os.getenv('PAPER_EQUITY')
            if seed is not None and (not math.isfinite(float(seed)) or float(seed) > cap or float(seed) <= 0):
                result.update(state='capital_exceeded', entries_allowed=False)
    except Exception:
        # Do not leak paths, license bodies or signatures through logs/API errors.
        result['state'] = 'invalid'
        result['entries_allowed'] = False
    return result


def entries_allowed(now: float | None = None, initial_capital: float | None = None) -> bool:
    return status(now, initial_capital)['entries_allowed']
