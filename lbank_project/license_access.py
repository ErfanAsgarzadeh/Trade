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


def status(now: float | None = None) -> dict:
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
        envelope = json.loads(path.read_text(encoding='utf-8'))
        payload = envelope['payload']
        if set(envelope) != {'payload', 'signature'} or payload['schema'] != 1:
            return result
        key = serialization.load_pem_public_key(Path(key_path).read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            return result
        key.verify(base64.b64decode(envelope['signature'], validate=True), canonical(payload))
        if payload['customer_id'] != customer:
            return result
        issued = timestamp(payload['issued_at'])
        start = timestamp(payload['not_before'])
        end = timestamp(payload['expires_at'])
        if not issued <= start < end or not isinstance(payload['plan'], str):
            return result
        result.update(customer_id=customer, plan=payload['plan'], expires_at=payload['expires_at'])
        result['state'] = 'not_yet_valid' if now < start else 'expired' if now >= end else 'active'
        result['entries_allowed'] = result['state'] == 'active'
    except Exception:
        # Do not leak paths, license bodies or signatures through logs/API errors.
        result['state'] = 'invalid'
    return result


def entries_allowed(now: float | None = None) -> bool:
    return status(now)['entries_allowed']
