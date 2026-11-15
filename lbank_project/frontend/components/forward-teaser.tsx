"use client";
import { useLang } from "@/lib/lang";
import { linePath, useForwardTest, withStart } from "@/lib/forward";
import { num, percent } from "@/lib/format";

/** Landing-page card: four headline numbers, a sparkline and a link to the full page. Renders nothing until data exists. */
export default function ForwardTeaser() {
  const { lang, t, path } = useLang();
  const data = useForwardTest();
  const ready = !!data && data.available && !data.collecting;
  const points = ready ? withStart(data!) : [];
  const box = { l: 4, r: 4, t: 6, b: 6 };
  const line = points.length > 1 ? linePath(points, 320, 90, box) : null;
  const signed = (v: number) =>
    (v > 0 ? "+" : v < 0 ? "-" : "") + percent(Math.abs(v), lang, 2);
  return (
    <div className="forward-teaser">
      <div>
        {ready ? (
          <dl className="forward-tiles">
            <div className="forward-tile">
              <dt>{t("بازده کل", "Total return")}</dt>
              <dd
                className={data!.total_return_pct! >= 0 ? "fw-up" : "fw-down"}
              >
                {signed(data!.total_return_pct!)}
              </dd>
            </div>
            <div className="forward-tile">
              <dt>{t("بیشترین افت", "Max drawdown")}</dt>
              <dd>{signed(data!.max_drawdown_pct!)}</dd>
            </div>
            <div className="forward-tile">
              <dt>{t("نرخ برد", "Win rate")}</dt>
              <dd>
                {data!.win_rate_pct == null
                  ? "-"
                  : percent(data!.win_rate_pct, lang)}
              </dd>
            </div>
            <div className="forward-tile">
              <dt>{t("روزهای اجرا", "Days running")}</dt>
              <dd>{num(data!.days!, lang)}</dd>
            </div>
          </dl>
        ) : (
          <p>
            {t(
              "آمار پس از ۷ روز اجرای کامل نمایش داده می‌شود؛ ربات‌ها هم‌اکنون در حال اجرای کاغذی‌اند.",
              "Statistics appear after 7 full days; the bots are running in paper mode right now.",
            )}
          </p>
        )}
      </div>
      <div className="forward-spark">
        {line && (
          <svg
            viewBox="0 0 320 90"
            role="img"
            aria-label={t(
              "نمودار کوچک شاخص سرمایهٔ آزمون پیشرو",
              "Small chart of the forward-test equity index",
            )}
            focusable="false"
          >
            <path
              className={
                points[points.length - 1].v >= 100
                  ? "fc-line fc-up"
                  : "fc-line fc-down"
              }
              d={line.d}
            />
          </svg>
        )}
        <p>
          <a className="landing-secondary" href={path("/forward-test/")}>
            {t("دیدن نتایج کامل", "See the full results")}
          </a>
        </p>
      </div>
    </div>
  );
}
