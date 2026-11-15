"use client";
import { useLang } from "@/lib/lang";
import { linePath, type Point } from "@/lib/forward";
import { num } from "@/lib/format";

const W = 720,
  H = 320,
  PAD = { l: 52, r: 16, t: 16, b: 34 };

export const dayLabel = (iso: string, lang: "fa" | "en") =>
  new Date(iso + "T00:00:00Z").toLocaleDateString(
    lang === "en" ? "en-US" : "fa-IR",
    { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" },
  );

/** Equity index line in plain SVG with a text alternative and a data table; colours come from theme variables. */
export default function ForwardChart({ points }: { points: Point[] }) {
  const { lang, t } = useLang();
  if (points.length < 2) return null;
  const { d, x, y, min, max } = linePath(points, W, H, PAD);
  const last = points[points.length - 1];
  const up = last.v >= 100;
  const ticks = [min, (min + max) / 2, max];
  const area =
    d +
    ` L${x(points.length - 1).toFixed(1)},${y(min).toFixed(1)} L${x(0).toFixed(1)},${y(min).toFixed(1)} Z`;
  const summary = t(
    `نمودار شاخص سرمایهٔ آزمون پیشرو از ${dayLabel(points[0].d, lang)} تا ${dayLabel(last.d, lang)}؛ از ۱۰۰ شروع شده و به ${num(last.v, lang)} رسیده است.`,
    `Equity index chart from ${dayLabel(points[0].d, lang)} to ${dayLabel(last.d, lang)}: it started at 100 and stands at ${num(last.v, lang)}.`,
  );
  return (
    <figure className="forward-chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-labelledby="forward-chart-title forward-chart-desc"
        focusable="false"
      >
        <title id="forward-chart-title">
          {t("شاخص سرمایه (شروع از ۱۰۰)", "Equity index (starts at 100)")}
        </title>
        <desc id="forward-chart-desc">{summary}</desc>
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              className="fc-grid"
              x1={PAD.l}
              x2={W - PAD.r}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text
              className="fc-axis"
              x={PAD.l - 8}
              y={y(tick) + 4}
              textAnchor="end"
            >
              {num(Math.round(tick * 10) / 10, lang)}
            </text>
          </g>
        ))}
        {min < 100 && max > 100 && (
          <line
            className="fc-base"
            x1={PAD.l}
            x2={W - PAD.r}
            y1={y(100)}
            y2={y(100)}
          />
        )}
        <path className={up ? "fc-area fc-up" : "fc-area fc-down"} d={area} />
        <path className={up ? "fc-line fc-up" : "fc-line fc-down"} d={d} />
        <circle
          className={up ? "fc-dot fc-up" : "fc-dot fc-down"}
          cx={x(points.length - 1)}
          cy={y(last.v)}
          r="4"
        />
        <text className="fc-axis" x={PAD.l} y={H - 10} textAnchor="start">
          {dayLabel(points[0].d, lang)}
        </text>
        <text className="fc-axis" x={W - PAD.r} y={H - 10} textAnchor="end">
          {dayLabel(last.d, lang)}
        </text>
      </svg>
      <figcaption>
        {t(
          "شاخص سرمایه: ۱۰۰ نقطهٔ شروع است. عدد دلاری یا اندازهٔ حساب منتشر نمی‌شود.",
          "Equity index: 100 is the starting point. No dollar amounts or account size are published.",
        )}
      </figcaption>
      <details className="forward-table-toggle">
        <summary>
          {t(
            "جدول دادهٔ نمودار (برای صفحه‌خوان‌ها)",
            "Chart data table (for screen readers)",
          )}
        </summary>
        <div className="forward-table-scroll" tabIndex={0}>
          <table>
            <caption className="sr-only">
              {t(
                "شاخص سرمایه در پایان هر روز UTC",
                "Equity index at the end of each UTC day",
              )}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("روز", "Day")}</th>
                <th scope="col">{t("شاخص", "Index")}</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.d}>
                  <th scope="row">{dayLabel(p.d, lang)}</th>
                  <td>{num(p.v, lang)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
