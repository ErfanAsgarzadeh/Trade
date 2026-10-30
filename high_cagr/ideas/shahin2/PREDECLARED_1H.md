# Shahin on 1h entries — pre-declared (written before any 1h result of this study was seen)

Baseline: shipped 4h Shahin (lab.py baseline). Every 1h variant keeps the improvements: ATR-regime filter, profit floor
1R -> +0.1R, pyramid, late-entry gate (move over 240 1h bars = 60 x 4h, threshold 0.1521), 1 % risk, 4 slots, same coins.
Variants (lab1h.py): Donchian N {10, 20, 40} 1h bars with the 1h trail / 1h stop / 4h ATR regime;
N 40 with: 1h ATR regime | trail on the 4h channel | stop 2 x ATR(4h) | trail 4h + stop 4h.
A 1h variant REPLACES the 4h baseline only if: ALONE Calmar >= 4h baseline in TRAIN and VALID, ACCOUNT Calmar >= 4h baseline
in TRAIN and VALID with full max DD <= baseline + 1 pp, and OTHER30 full Calmar >= the 4h baseline's OTHER30 Calmar.
