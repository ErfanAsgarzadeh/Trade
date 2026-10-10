import lbank_candles as L


def test_candle_collector_builds_and_rolls_bars(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "OUT", tmp_path)
    monkeypatch.setattr(L, "SEED", tmp_path / "no_seed")
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


def test_seed_install_and_spot_backfill(tmp_path, monkeypatch):
    out, seed = tmp_path / "out", tmp_path / "seed"
    monkeypatch.setattr(L, "OUT", out)
    monkeypatch.setattr(L, "SEED", seed)
    sym = "BTC/USDT:USDT"
    base = 1791619200000
    L.write_rows(seed / L.csv_path(sym).name, [[base + i * L.H4 * 1000, 1., 2., 0.5, 1.5, 3.] for i in range(3)])
    calls = []

    def fake_spot(symbol, start_ms, until_ms):
        calls.append((start_ms, until_ms))
        return [[t, 9., 9., 9., 9., 1.] for t in range(int(start_ms), int(until_ms), L.H4 * 1000)]

    monkeypatch.setattr(L, "spot_klines", fake_spot)
    c = L.Collector([sym])
    assert len(L.read_rows(L.csv_path(sym))) == 3          # seeded
    now = (base + 8 * L.H4 * 1000) / 1000 + 5               # five bars later than the last seeded bar
    c.step({"BTCUSDT": 100.}, now)
    rows = L.read_rows(L.csv_path(sym))
    steps = {b[0] - a[0] for a, b in zip(rows, rows[1:])}
    assert steps == {L.H4 * 1000} and rows[-1][1] == 100. and rows[-1][0] == base + 8 * L.H4 * 1000   # contiguous, forming bar last
    assert calls and rows[3][1] == 9.                       # gap bars came from spot, not invented
