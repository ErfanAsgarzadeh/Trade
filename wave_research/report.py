from html import escape
import json

import numpy as np
import pandas as pd

from .data_loader import aggregate, load
from .strategies import NAMES, NOT_TESTED, PROXIES

COLORS = ["#16758a", "#aa462f", "#435dba", "#7957a1", "#28864e", "#ad6b09", "#5a6470", "#bd4773"]


def line_chart(title, frame):
    matrix = frame.to_numpy(dtype=float)
    finite = matrix[np.isfinite(matrix)]
    if not len(finite):
        return ""
    lo, hi = finite.min(), finite.max()
    lines = []
    for i, col in enumerate(frame):
        data = matrix[:, i]
        ix = np.flatnonzero(np.isfinite(data))
        xy = " ".join(f"{45 + 670*j/max(len(data)-1,1):.1f},{205-180*(data[j]-lo)/max(hi-lo,1e-12):.1f}" for j in ix)
        lines.append(f'<polyline points="{xy}" fill="none" stroke="{COLORS[i%len(COLORS)]}" stroke-width="1.5"/>')
    legend = " · ".join(f'<span style="color:{COLORS[i%len(COLORS)]}">{escape(str(c))}</span>' for i, c in enumerate(frame))
    return (f'<section><h3>{escape(title)}</h3><svg viewBox="0 0 745 225" role="img" aria-label="{escape(title)}">'
            f'<path d="M45 25V205H715" fill="none" stroke="#aaa"/>'
            f'<text x="4" y="28">{hi:.2g}</text><text x="4" y="205">{lo:.2g}</text>'
            f'{"".join(lines)}</svg><p>{legend}</p></section>')


def heatmap(frame):
    out = ["<table><thead><tr><th>دوره</th>", *(f"<th>{escape(x)}</th>" for x in frame), "</tr></thead><tbody>"]
    for row in frame.itertuples():
        out.append(f"<tr><th>{escape(str(row.Index))}</th>")
        for val in row[1:]:
            if pd.isna(val):
                out.append("<td>—</td>")
            else:
                alpha = min(.7, abs(val)/22)
                color = "33,129,87" if val >= 0 else "180,62,56"
                out.append(f'<td style="background:rgba({color},{alpha:.3f})">{val:.2f}</td>')
        out.append("</tr>")
    return "".join([*out, "</tbody></table>"])


def candles(title, bars, trade, first, mins, pivots):
    prices = [trade.entry, trade.stop, trade.target, trade.exit]
    lo = min(bars[:, 2].min(), *prices)
    hi = max(bars[:, 1].max(), *prices)
    y = lambda price: 205 - 180*(price-lo)/max(hi-lo, 1e-12)
    x = lambda i: 45 + 670*i/max(len(bars)-1, 1)
    marks = []
    for i, (op, high, low, close, _) in enumerate(bars):
        color = "#14835c" if close >= op else "#af4a49"
        marks.append(f'<path d="M{x(i):.2f} {y(high):.2f}V{y(low):.2f}" stroke="{color}"/>'
                     f'<rect x="{x(i)-3:.2f}" y="{min(y(op),y(close)):.2f}" width="6" height="{max(.8,abs(y(op)-y(close))):.2f}" fill="{color}"/>')
    for price, tag, color in zip(prices, ("Entry", "SL", "TP", "Exit"), COLORS):
        marks.append(f'<path d="M45 {y(price):.2f}H715" stroke="{color}" stroke-dasharray="5 4"/>'
                     f'<text x="5" y="{y(price):.2f}" fill="{color}">{tag}</text>')
    visible = pivots[(pivots[:, 0] >= first) & (pivots[:, 1] <= trade.entry_min//mins) & (pivots[:, 0] < first+len(bars))]
    points = " ".join(f"{x(i-first):.2f},{y(price):.2f}" for i, _, _, price in visible)
    marks.append(f'<polyline points="{points}" stroke="#435dba" fill="none"/>')
    for minute, color in ((trade.entry_min, "#161616"), (trade.exit_min, "#777")):
        offset = minute//mins-first
        if 0 <= offset < len(bars):
            marks.append(f'<path d="M{x(offset):.2f} 25V205" stroke="{color}" stroke-dasharray="2 3"/>')
    return (f'<section><h3>{escape(title)}</h3><svg viewBox="0 0 745 225" role="img" '
            f'aria-label="{escape(title)}">{"".join(marks)}</svg></section>')


def charts(out, plans, finalists, cfg):
    from .wave_engine import atr, zigzag

    equity = pd.read_csv(out/"equity.csv").set_index("date")
    plots = [line_chart("موجودی روزانه (دلار)", equity),
             line_chart("افت روزانه (٪)", 100*(1-equity/equity.cummax()))]
    months = pd.read_csv(out/"monthly_returns.csv").set_index("period_end")
    plots.append("<h3>بازده ماهانهٔ راهبردهای نهایی (٪)</h3>" + heatmap(months[finalists].T.rename(
        columns=lambda value: value[:7])))
    monte = pd.read_csv(out/"monte_carlo_results.csv.gz")
    bins = np.linspace(monte.return_pct.quantile(.005), monte.return_pct.quantile(.995), 60)
    plots.append(line_chart("توزیع بازده بوت‌استرپ، برش صدک ۰٫۵ تا ۹۹٫۵ (فراوانی)",
                            pd.DataFrame({name: np.histogram(g.return_pct, bins)[0]
                                          for name, g in monte.groupby("strategy")})))
    trials = pd.read_csv(out/"optimization_trials.csv.gz")
    central = trials[trials.period == "validation"].pivot_table(
        index="strategy", columns="target_r", values="sharpe", aggfunc="median")
    central.index = [f"S{x:02d}" for x in central.index]
    central.columns = [f"{x:g}R" for x in central.columns]
    plots.append("<h3>حساسیت هدف سود (میانهٔ شارپ اعتبارسنجی در تنظیمات آزموده)</h3>" + heatmap(central))
    series = pd.read_csv(out/"out_of_sample_results.csv")
    select = series[series.strategy.isin(finalists)].set_index("strategy")
    plots.append(line_chart("مقایسهٔ شارپ آموزش، اعتبارسنجی و آزمون نهایی",
                            select[["train_sharpe", "validation_sharpe", "final_sharpe"]].T))
    plots.append(line_chart("مقایسهٔ Profit Factor", select[["train_pf", "validation_pf", "final_pf"]].T))
    plots.append(line_chart("نرخ برد (٪) و نسبت میانگین برد به باخت ×۱۰۰، آزمون نهایی",
                            pd.DataFrame({"نرخ برد":select.final_win_rate_pct,
                                          "نسبت برد به باخت ×۱۰۰":select.final_avg_win_loss_ratio*100})))
    trades = pd.read_csv(out/"trade_history.csv.gz")
    for sym in set(plans[name]["symbol"] for name in finalists):
        examples = [name for name in finalists if plans[name]["symbol"] == sym and name in set(trades.strategy)]
        if not examples:
            continue
        market, _ = load(sym, cfg)
        for name in examples:
            p = plans[name]
            mins = cfg["timeframes"][p["timeframe"]]
            bars = aggregate(market, mins)
            pivots = zigzag(bars[:, 3], atr(bars, p["params"]["atr_period"])*p["params"]["atr_multiple"])
            subset = trades[(trades.strategy == name) & (trades.quantity > 0)]
            final_start = len(equity)*4//5*1440
            subset = subset[subset.entry_min >= final_start]
            for win, caption in ((True, "معاملهٔ موفق"), (False, "معاملهٔ ناموفق")):
                options = subset[subset.pnl > 0] if win else subset[subset.pnl < 0]
                if options.empty:
                    continue
                t = options.iloc[0]
                first = max(0, int(t.entry_min)//mins-15)
                stop = min(len(bars), int(t.exit_min)//mins+5)
                plots.append(candles(f"{name} · {sym} {p['timeframe']} · {caption}", bars[first:stop], t, first, mins, pivots))
    return "\n".join(plots)


def render(out, plans, finalists, baseline, cfg):
    from .main import write

    config = cfg["selection"]
    raw = baseline.loc[(baseline.sizing == "compound") & (baseline.direction == 0)
                       & (baseline.risk == cfg["baseline"]["risk"])]
    rows = []
    for i, name in enumerate(NAMES, 1):
        key = f"S{i:02d}"
        row = dict(strategy=key, name=name, proxy=i in PROXIES, selected=key in finalists)
        if key not in plans:
            subset = raw[(raw.strategy == i) & (raw.period == "train")]
            maximum = int(subset.trades.max()) if len(subset) else 0
            status = "Not Tested" if i in NOT_TESTED else (
                "Insufficient Data" if maximum < config["minimum_trades"] else "Rejected in training")
            rows.append(dict(**row, status=status, reason=NOT_TESTED.get(i, "Training sample or expectancy gate"),
                             maximum_training_trades=maximum))
            continue
        plan = plans[key]
        tr, va, te = plan["periods"]
        gates = dict(sample=va["trades"]+te["trades"] >= config["minimum_trades"],
                     pf=(te["profit_factor"] or 0) > config["minimum_pf"],
                     expectancy=(te["expectancy_r"] or 0) > 0,
                     sharpe=te["sharpe"] > config["minimum_sharpe"],
                     drawdown=te["drawdown_pct"] < config["maximum_dd_pct"],
                     positive_oos=va["return_pct"] > 0 and te["return_pct"] > 0,
                     concentration=(te["concentration_top5"] or 1) <= .35)
        rows.append(dict(**row, status="Metric gates passed" if all(gates.values()) else "Metric gates failed",
                         reason=", ".join(k for k, value in gates.items() if not value),
                         rank_score=plan["rank_score"], symbol=plan["symbol"], timeframe=plan["timeframe"],
                         **{f"{s['period']}_{field}":s[field] for s in (tr, va, te)
                            for field in ("trades", "sharpe", "cagr_pct", "return_pct", "drawdown_pct",
                                          "expectancy_r", "win_rate_pct", "avg_win_loss_ratio")},
                         **{f"{s['period']}_pf":s["profit_factor"] for s in (tr, va, te)}))
    ranking = pd.DataFrame(rows).sort_values(["rank_score", "strategy"], ascending=[False, True], na_position="last")
    write(ranking, out/"strategy_ranking.csv")
    write(ranking[ranking.rank_score.notna()], out/"out_of_sample_results.csv")
    training = raw[(raw.period == "train") & (raw.trades >= config["minimum_trades"]) & (raw.expectancy_r > 0)].copy()
    training["score"] = training.sharpe - .015 * training.drawdown_pct
    winners = []
    for label in ("symbol", "timeframe"):
        for _, g in training.groupby(label):
            top = g.sort_values(["score", "trades", "strategy"], ascending=[False, False, True]).iloc[0]
            mask = ((raw.strategy == top.strategy) & (raw.symbol == top.symbol) & (raw.timeframe == top.timeframe))
            winners.append(raw[mask].assign(winner_group=label))
    by_group = pd.concat(winners, ignore_index=True)
    write(by_group, out/"training_winners_by_market.csv")
    portfolios = pd.read_csv(out/"portfolio_results.csv.gz", keep_default_na=False)
    portfolio_final = portfolios[portfolios.period == "final"].copy()
    portfolio_final = portfolio_final[(portfolio_final.waves.isin(finalists)) |
                                      (portfolio_final.waves.isin(["", "+".join(sorted(finalists))]))]
    tables = {"Rank": ranking, "Market winners": by_group, "Portfolio final": portfolio_final,
              "Walk-forward": pd.read_csv(out/"walk_forward.csv"),
              "Bootstrap": pd.read_csv(out/"bootstrap_intervals.csv"), "Cost stress": pd.read_csv(out/"cost_stress.csv"),
              "Monthly": pd.read_csv(out/"monthly_returns.csv"), "Yearly": pd.read_csv(out/"yearly_returns.csv")}
    with pd.ExcelWriter(out/"backtest_report.xlsx", engine="openpyxl") as xlsx:
        for label, frame in tables.items():
            frame.to_excel(xlsx, sheet_name=label, index=False)
            ws = xlsx.sheets[label]
            ws.freeze_panes = "B2"
            ws.auto_filter.ref = ws.dimensions
    metadata = json.loads((out/"run_config.json").read_text())
    top = ranking.head(10)[["strategy", "name", "symbol", "timeframe", "validation_sharpe",
                             "final_trades", "final_cagr_pct", "final_drawdown_pct", "final_pf", "status"]]
    sections = [
        "<!doctype html><html lang='fa' dir='rtl'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>",
        "<title>پژوهش موج‌شماری</title><style>body{margin:2rem auto;max-width:1160px;padding:0 1rem;font:16px system-ui;background:#f5f7f8;color:#1d2630}table{border-collapse:collapse;background:white;display:block;overflow:auto;direction:ltr}th,td{padding:.42rem;border:1px solid #ddd;text-align:right;white-space:nowrap}section{background:white;padding:1rem;margin:1rem 0}svg{width:100%;max-height:440px;direction:ltr}h2{margin-top:2rem}</style>",
        "<h1>بک‌تست موج‌شماری بازار آتی کریپتو</h1>",
        "<p>مرتب‌سازی بر اساس اعتبارسنجی است. آزمون نهایی در انتخاب استفاده نشده و همان آرشیو قبلاً در پژوهش‌های ریپو استفاده شده است.</p>",
        f"<p>{len(NAMES)-len(NOT_TESTED)} راهبرد آزموده‌شده · {metadata['baseline_trials']:,} آزمون پایه · {len(portfolios)//3:,} سناریوی حساب مشترک.</p>",
        "<p>افت حساب مشترک از سود و زیان تحقق‌یافته محاسبه می‌شود. منحنی راهبردهای مستقل پوزیشن باز را در پایان روز ارزش‌گذاری می‌کند. راهبردهای تقریبی با ستون proxy مشخص‌اند.</p>",
        "<h2>ده رتبهٔ اول اعتبارسنجی</h2>", top.to_html(index=False, float_format=lambda x:f"{x:.3f}"),
        "<h2>حساب مشترک، برش نهایی</h2>", portfolio_final[["waves", "bots", "trades", "cagr_pct", "drawdown_pct", "sharpe"]].to_html(index=False, float_format=lambda x:f"{x:.3f}"),
        "<h2>نمودارها</h2>", charts(out, plans, finalists, cfg),
        "<h2>فهرست و وضعیت هر ۵۲ راهبرد</h2>", ranking[["strategy", "name", "proxy", "status", "reason"]].to_html(index=False),
        "</html>"]
    (out/"backtest_report.html").write_text("\n".join(sections))
