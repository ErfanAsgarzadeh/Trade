"""Operator-configured product tariffs. New installations never open sales implicitly."""
import json
import uuid
import time
from capital_plans import PRICES, TERMS, money
from portal_audit import require_admin,record

PRODUCTS=('signals','autotrade')
LABELS={'signals':'فقط سیگنال','autotrade':'معاملهٔ خودکار'}


def validate_product(product):
    if product not in PRODUCTS:raise ValueError('Unknown subscription product')
    return product


def settings(db,product):
    validate_product(product)
    row=db.execute('SELECT * FROM product_pricing WHERE product=?',(product,)).fetchone()
    return dict(product=product,label=LABELS[product],sales_enabled=bool(row['enabled']) if row else False,
                version=row['version'] if row else 'unconfigured',
                prices=json.loads(row['prices']) if row else {})


def catalog(store):
    with store.db() as db:
        products=[]
        for product in PRODUCTS:
            config=settings(db,product)
            config['tiers']=[dict(cap_usd=cap,prices_cents={str(m):config['prices'].get(str(cap),{}).get(str(m)) for m in TERMS}) for cap in PRICES]
            config.pop('prices');products.append(config)
    return dict(version='products-v1',currency='USD',grace_hours=72,products=products,
                tiers=next(p['tiers'] for p in products if p['product']=='autotrade'))


def configure(store,product,document,enabled=False,expected_version=None,actor=None):
    validate_product(product)
    if type(enabled) is not bool:raise ValueError('Sales flag must be boolean')
    if not isinstance(document,dict):raise ValueError('Expected a JSON tariff object')
    if set(document)!={str(cap) for cap in PRICES}:raise ValueError('Supply all seven capital tiers')
    prices={}
    for cap,terms in document.items():
        if not isinstance(terms,dict) or set(terms)!={'1','3','6'}:raise ValueError('Supply 1, 3 and 6 calendar-month USD prices')
        prices[cap]={m:int(money(value,positive=True)*100) for m,value in terms.items()}
        if any(v>20000000 for v in prices[cap].values()):raise ValueError('Price may not exceed 200,000 USD')
    version=str(uuid.uuid4())
    with store.db() as db:
        store.database.begin_write(db,'admin-authority' if actor else 'product-pricing')
        if actor:
            require_admin(db,actor)
            if store.database.postgres:store.database.begin_write(db,'product-pricing')
        if expected_version is not None and settings(db,product)['version']!=expected_version:raise ValueError('Tariff version changed')
        db.execute('INSERT INTO product_pricing VALUES(?,?,?,?,?) ON CONFLICT(product) DO UPDATE SET '
                   'prices=excluded.prices,enabled=excluded.enabled,version=excluded.version,updated=excluded.updated',
                   (product,json.dumps(prices),int(enabled),version,time.time()))
        record(db,actor,'pricing_saved',product,dict(version=version,sales_enabled=enabled))
    return dict(product=product,version=version,sales_enabled=bool(enabled))


def close_sales(store,product,expected_version=None,actor=None):
    validate_product(product)
    with store.db() as db:
        store.database.begin_write(db,'admin-authority' if actor else 'product-pricing')
        if actor:
            require_admin(db,actor)
            if store.database.postgres:store.database.begin_write(db,'product-pricing')
        if expected_version is not None and settings(db,product)['version']!=expected_version:raise ValueError('Tariff version changed')
        db.execute('UPDATE product_pricing SET enabled=0,version=?,updated=? WHERE product=?',
                   (str(uuid.uuid4()),time.time(),product))
        record(db,actor,'sales_closed',product)


def priced(config,cap,months):
    if not config['sales_enabled']:raise ValueError('Sales are closed until tariffs are finalized')
    try:return config['prices'][str(cap)][str(months)]
    except KeyError:raise ValueError('Price is not configured') from None


def open_sales(store,product,expected_version,actor):
    # Reuse the current, fully validated tariff. The expected-version check in
    # configure fences any edit between reading it and opening sales.
    with store.db() as db:config=settings(db,product)
    document={cap:{term:str(value/100) for term,value in terms.items()} for cap,terms in config['prices'].items()}
    return configure(store,product,document,True,expected_version,actor)
