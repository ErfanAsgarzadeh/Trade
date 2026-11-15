"""Time-based one-time passwords (RFC 6238, HMAC-SHA1, 6 digits, 30 s) with the standard library only."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

PERIOD = 30
DIGITS = 6
RECOVERY_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'


def now():
    """Seconds since the epoch. The only clock TOTP reads, so tests can move it."""
    return time.time()


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')


def code_at(secret, step):
    """The code for one 30-second step (RFC 4226 dynamic truncation of HMAC-SHA1)."""
    key = base64.b32decode(secret + '=' * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack('>Q', step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = (struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return f'{number:0{DIGITS}d}'


def match(secret, code, last_step=0, at=None):
    """The accepted step when `code` is valid for the current step or one either side and newer than `last_step`, else None.
    Every candidate is compared so the work does not depend on which step matched."""
    code = str(code or '').strip().replace(' ', '')
    if len(code) != DIGITS or not code.isascii() or not code.isdigit():return None
    current = int((now() if at is None else at) // PERIOD)
    found = None
    for step in (current - 1, current, current + 1):
        if hmac.compare_digest(code_at(secret, step), code) and step > last_step:found = step
    return found


def uri(secret, username, issuer='Avina'):
    label = quote(f'{issuer}:{username}', safe='')
    return f'otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe="")}&algorithm=SHA1&digits={DIGITS}&period={PERIOD}'


def recovery_codes(count=10):
    """Fresh one-time codes like 'k3x9-m2pq-7hwd' (about 60 bits each)."""
    return ['-'.join(''.join(secrets.choice(RECOVERY_ALPHABET) for _ in range(4)) for _ in range(3)) for _ in range(count)]


def recovery_digest(code):
    return hashlib.sha256(str(code or '').strip().lower().encode()).hexdigest()
