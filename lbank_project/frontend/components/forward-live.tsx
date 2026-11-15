"use client";
import { useLang } from "@/lib/lang";
import { useForwardTest, withStart, type ForwardData } from "@/lib/forward";
import { num, percent } from "@/lib/format";
import ForwardChart, { dayLabel } from "./forward-chart";

const MONTHS_EN = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function signed(value: number | null | undefined, lang: "fa" | "en") {
  if (value === null || value === undefined) return "-";
  const text = percent(Math.abs(value), lang, 2);
  return (value > 0 ? "+" : value < 0 ? "-" : "") + text;
}

const tone = (value: number | null | undefined) =>
  value === null || value === undefined || value === 0
    ? ""
    : value > 0
      ? "fw-up"
      : "fw-down";

export function CollectingState({ data }: { data: ForwardData | null }) {
  const { lang, t } = useLang();
  return (
    <section className="forward-collecting" aria-live="polite">
      <h2>{t("در حال جمع‌آوری داده", "Collecting data")}</h2>
      <p>
        {data === null
          ? t("در حال بارگذاری...", "Loading...")
          : t(
              "آمار آزمون پیشرو پس از دست‌کم ۷ روز اجرای کامل نمایش داده می‌شود تا عددها گمراه‌کننده نباشند. ربات‌ها در حالت کاغذی در حال اجرا هستند؛ بعداً سر بزنید.",
              "Statistics appear after at least 7 full days of running so the numbers are not misleading. The bots are running in paper mode; please check back later.",
            )}
      </p>
      {data?.days ? (
        <p>
          {t("روزهای کامل تاکنون: ", "Full days so far: ")}
          <strong>{num(data.days, lang)}</strong>
        </p>
      ) : null}
    </section>
  );
}

export default function ForwardLive() {
  const { lang, t } = useLang();
  const data = useForwardTest();
  if (!data || !data.available || data.collecting) {
    return <CollectingState data={data} />;
  }
  const points = withStart(data);
  const tile = (label: string, value: string, cls = "") => (
    <div className="forward-tile">
      <dt>{label}</dt>
      <dd className={cls}>{value}</dd>
    </div>
  );
  const month = (m: string) => {
    const [y, mm] = m.split("-").map(Number);
    return lang === "en"
      ? `${MONTHS_EN[mm - 1]} ${y}`
      : new Date(Date.UTC(y, mm - 1, 15)).toLocaleDateString("fa-IR", {
          year: "numeric",
          month: "long",
          timeZone: "UTC",
        });
  };
  return (
    <>
      <p className="forward-status">
        <span className="forward-badge">
          {t("شبیه‌سازی کاغذی", "Paper trading")}
        </span>{" "}
        {t("شروع: ", "Started: ")}
        <strong>{dayLabel(data.start_date!, lang)}</strong>
        {" · "}
        {t("روزهای کامل: ", "Full days: ")}
        <strong>{num(data.days!, lang)}</strong>
        {" · "}
        {t("داده تا پایان روز UTC: ", "Data through the end of UTC day: ")}
        <strong>{dayLabel(data.data_through!, lang)}</strong>
      </p>
      <dl className="forward-tiles">
        {tile(
          t("بازده کل", "Total return"),
          signed(data.total_return_pct, lang),
          tone(data.total_return_pct),
        )}
        {tile(
          t("بیشترین افت از قله", "Max drawdown"),
          signed(data.max_drawdown_pct, lang),
          tone(data.max_drawdown_pct),
        )}
        {tile(
          t("معاملهٔ بسته‌شده", "Closed trades"),
          num(data.trades ?? 0, lang),
        )}
        {tile(
          t("نرخ برد", "Win rate"),
          data.win_rate_pct == null ? "-" : percent(data.win_rate_pct, lang),
        )}
        {tile(
          t("ضریب سود", "Profit factor"),
          data.profit_factor == null ? "-" : num(data.profit_factor, lang),
        )}
        {tile(
          t("بهترین روز", "Best day"),
          signed(data.best_day_pct, lang),
          tone(data.best_day_pct),
        )}
        {tile(
          t("بدترین روز", "Worst day"),
          signed(data.worst_day_pct, lang),
          tone(data.worst_day_pct),
        )}
        {tile(
          t("شاخص فعلی", "Current index"),
          num(data.current_index ?? 100, lang),
        )}
      </dl>
      <h2>{t("منحنی سرمایه", "Equity curve")}</h2>
      <ForwardChart points={points} />
      <h2>{t("بازده ماهانه", "Monthly returns")}</h2>
      <div className="forward-table-scroll" tabIndex={0}>
        <table className="forward-monthly">
          <caption className="sr-only">
            {t("بازده هر ماه به درصد", "Return of each month in percent")}
          </caption>
          <thead>
            <tr>
              <th scope="col">{t("ماه", "Month")}</th>
              <th scope="col">{t("بازده", "Return")}</th>
            </tr>
          </thead>
          <tbody>
            {(data.monthly ?? []).map((m) => (
              <tr key={m.m}>
                <th scope="row">{month(m.m)}</th>
                <td className={tone(m.r)}>{signed(m.r, lang)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>{t("به تفکیک ربات", "By bot")}</h2>
      <div className="forward-bots">
        {(data.bots ?? []).map((b) => (
          <article key={b.id} className="forward-bot">
            <h3>{lang === "en" ? b.name_en : b.name_fa}</h3>
            <dl>
              <div>
                <dt>{t("معاملهٔ بسته‌شده", "Closed trades")}</dt>
                <dd>{num(b.trades, lang)}</dd>
              </div>
              <div>
                <dt>{t("نرخ برد", "Win rate")}</dt>
                <dd>
                  {b.win_rate_pct == null ? "-" : percent(b.win_rate_pct, lang)}
                </dd>
              </div>
              <div>
                <dt>{t("سهم در بازده", "Contribution to return")}</dt>
                <dd className={tone(b.contribution_pct)}>
                  {signed(b.contribution_pct, lang)}
                </dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
      <p className="forward-updated">
        {t("آخرین به‌روزرسانی: ", "Last updated: ")}
        <time dateTime={data.computed_at}>
          {data.computed_at?.replace("T", " ").replace("Z", " UTC")}
        </time>
        {" · "}
        {data.equity_basis === "mark_to_market"
          ? t(
              "ارزش‌گذاری سرمایه شامل سود و زیان باز معاملات باز است.",
              "Equity is valued at market, including open positions.",
            )
          : t(
              "فقط سود و زیان تحقق‌یافته (بسته‌شده) حساب شده است؛ معاملات باز در سرمایه نیامده‌اند.",
              "Equity counts realised (closed) results only; open positions are not included.",
            )}
      </p>
    </>
  );
}
