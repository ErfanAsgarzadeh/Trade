import lbank_candles as L


def test_candle_collector_builds_and_rolls_bars(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "OUT", tmp_path)
    sym = "BTC/USDT:USDT"
    t = 1791628249
    c = L.Collector([sym])
    for k, price in enumerate((100., 105., 99., 101.)):
        c.step({"BTCUSDT": price}, t + 10 * k)
    c.flush_all(t + 9999)
    rows = L.read_rows(L.csv_path(sym))
    assert len(rows) == 1 and rows[0][1:5] == [100., 105., 99., 101.] and rows[0][0] % (L.H4 * 1000) == 0
    c2 = L.Collector([sym])                       # restart in the next 4h bar: old bar kept, new bar appended
    c2.step({"BTCUSDT": 110.}, t + L.H4)
    rows = L.read_rows(L.csv_path(sym))
    assert len(rows) == 2 and rows[0][4] == 101. and rows[1][0] - rows[0][0] == L.H4 * 1000 and rows[1][1] == 110.


def test_symbol_mapping():
    assert L.lbank_name("SHIB/USDT:USDT") == "SHIBUSDT"
    assert L.csv_path("BTC/USDT:USDT").name == "BTC_USDT_USDT_4h.csv"
