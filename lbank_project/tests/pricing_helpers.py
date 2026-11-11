"""Disposable test tariffs; never called by production provisioning."""
from capital_plans import PRICES,TERMS
from product_pricing import configure


def enable_test_prices(store):
    for product,multiplier in [('autotrade',1),('signals',0.5)]:
        configure(store,product,{str(cap):{str(m):str(prices[i]*multiplier) for i,m in enumerate(TERMS)} for cap,prices in PRICES.items()},enabled=True)
