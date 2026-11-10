"""Versioned USD prices shared by billing, the portal and signed licenses."""
from calendar import monthrange
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING

VERSION = '2026-11-v1'
PRICES = {
    1000: (9, 24, 42), 3000: (19, 49, 89), 5000: (29, 79, 139),
    10000: (49, 129, 229), 25000: (99, 269, 479),
    50000: (169, 459, 809), 100000: (299, 809, 1439),
}
TERMS = (1, 3, 6)
GRACE_SECONDS = 72 * 3600


def money(value, *, positive=False):
    try:
        result = Decimal(str(value))
        if isinstance(value, bool) or not result.is_finite() or result < 0 or result > Decimal('1000000000'):
            raise ValueError('Invalid USD amount')
        result = result.quantize(Decimal('.01'))
        if positive and result <= 0:
            raise ValueError('USD amount must be positive')
        return result
    except (InvalidOperation, TypeError):
        raise ValueError('Invalid USD amount') from None


def price_cents(cap, months):
    if type(cap) is not int or type(months) is not int or cap not in PRICES or months not in TERMS:
        raise ValueError('Unknown capital tier or duration')
    return PRICES[cap][TERMS.index(months)] * 100


def catalog():
    return dict(version=VERSION, currency='USD', grace_hours=72,
                tiers=[dict(cap_usd=cap, prices_cents={str(m): price_cents(cap, m) for m in TERMS}) for cap in PRICES])


def add_months(stamp, months):
    dt = datetime.fromtimestamp(stamp, timezone.utc)
    total = dt.year * 12 + dt.month - 1 + months
    return dt.replace(year=total // 12, month=total % 12 + 1,
                      day=min(dt.day, monthrange(total // 12, total % 12 + 1)[1])).timestamp()


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def prorated_cents(old_cap, new_cap, months, start, end, now):
    difference = price_cents(new_cap, months) - price_cents(old_cap, months)
    if difference <= 0 or not start <= now < end:
        raise ValueError('Upgrade requires an active license and a higher capital tier')
    fraction = Decimal(str(end - now)) / Decimal(str(end - start))
    return int((Decimal(difference) * fraction).to_integral_value(rounding=ROUND_CEILING))
