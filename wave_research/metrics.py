import numpy as np


def streak(mask):
    hits = np.flatnonzero(np.r_[True, ~mask, True])
    return int(np.diff(hits).max() - 1)


def score(equity, pnl, trades, start, end):
    start_equity = equity[start-1] if start else 10000.
    path = np.r_[start_equity, equity[start:end]]
    change = np.diff(path) / np.maximum(path[:-1], 1e-12)
    peaks = np.maximum.accumulate(path)
    drawdown = 1 - path / np.maximum(peaks, 1e-12)
    maxdd = float(drawdown.max())
    gain, loss = pnl[pnl > 0], pnl[pnl < 0]
    downside = np.sqrt(np.mean(np.minimum(change, 0)**2))
    cagr = max(0, path[-1]/max(path[0], 1e-12))**(365.25/(end-start)) - 1
    dd_dollars = np.max(peaks - path)
    active = 0.
    if len(trades):
        em, xm = trades[:, 0], trades[:, 1]
        active = np.maximum(0, np.minimum(xm+1, end*1440) - np.maximum(em, start*1440)).sum() / ((end-start)*1440)
    return dict(
        trades=len(pnl), wins=len(gain), losses=len(loss), win_rate_pct=100 * len(gain) / len(pnl) if len(pnl) else 0.,
        net_pnl=float(pnl.sum()), gross_profit=float(gain.sum()), gross_loss=float(-loss.sum()),
        profit_factor=float(gain.sum() / -loss.sum()) if len(loss) else None,
        average_win=float(gain.mean()) if len(gain) else None, average_loss=float(loss.mean()) if len(loss) else None,
        avg_win_loss_ratio=float(gain.mean() / -loss.mean()) if len(gain) and len(loss) else None,
        return_pct=float(100 * (path[-1]/max(path[0], 1e-12) - 1)), cagr_pct=float(cagr*100),
        sharpe=float(np.sqrt(365.25)*change.mean()/change.std()) if change.std() else 0.,
        sortino=float(np.sqrt(365.25)*change.mean()/downside) if downside else None,
        calmar=float(cagr/maxdd) if maxdd else None,
        recovery_factor=float((path[-1]-path[0])/dd_dollars) if dd_dollars else None,
        drawdown_pct=float(maxdd*100), drawdown_duration_days=streak(drawdown[1:] > 0),
        win_streak=streak(pnl > 0), loss_streak=streak(pnl < 0), exposure_pct=float(100 * active),
        average_minutes=float(np.mean(trades[:, 1]-trades[:, 0]+1)) if len(trades) else None,
        expectancy_r=float(np.mean(trades[:, 6] / trades[:, 5])) if len(trades) and trades.shape[1] > 2 else None,
        average_mae_r=float(trades[:, 8].mean()) if len(trades) and trades.shape[1] > 2 else None,
        average_mfe_r=float(trades[:, 9].mean()) if len(trades) and trades.shape[1] > 2 else None,
        concentration_top5=float(np.sort(gain)[-5:].sum()/gain.sum()) if len(gain) else None)
