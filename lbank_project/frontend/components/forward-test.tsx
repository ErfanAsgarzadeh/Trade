import { localPath, pick, type Lang } from "@/lib/i18n";
import { LangProvider } from "@/lib/lang";
import { SiteFooter, SiteHeader } from "./site-chrome";
import ForwardLive from "./forward-live";

/** Static copy is server-rendered so crawlers see it without JavaScript; the numbers load from /api/forward-test. */
export default function ForwardTestPage({ lang = "fa" }: { lang?: Lang }) {
  const t = pick(lang),
    path = (p: string) => localPath(lang, p);
  return (
    <LangProvider lang={lang}>
      <div className="landing forward-page" id="landing-page">
        <a className="skip-link" href="#forward-main">
          {t("رفتن به محتوا", "Skip to content")}
        </a>
        <SiteHeader lang={lang} page="/forward-test/" />
        <main id="forward-main">
          <section className="forward-hero" aria-labelledby="forward-title">
            <span className="eyebrow">FORWARD TEST</span>
            <h1 id="forward-title">
              {t("فوروارد تست زنده آوینا", "Avina live forward test")}
            </h1>
            <p className="forward-paper" role="note">
              <strong>
                {t("شبیه‌سازی کاغذی (Paper Trading):", "Paper trading:")}
              </strong>{" "}
              {t(
                "این نتایج از سفارش‌های شبیه‌سازی‌شده با قیمت‌های واقعی بازار به دست آمده است؛ هیچ پول واقعی‌ای درگیر نیست. ربات‌ها همچنان در حال اجرا هستند و عددها هر روز به‌روز می‌شوند.",
                "These results come from simulated orders placed at real market prices; no real money is involved. The bots are still running and the numbers update every day.",
              )}
            </p>
          </section>
          <section className="forward-live" aria-label={t("نتایج", "Results")}>
            <ForwardLive />
          </section>
          <section className="forward-explain" aria-labelledby="forward-how">
            <h2 id="forward-how">
              {t("این نتایج را چگونه بخوانیم", "How to read this")}
            </h2>
            <h3>
              {t(
                "بک‌تست، آزمون پیشرو و نتیجهٔ زنده",
                "Backtest, forward test and live results",
              )}
            </h3>
            <ul>
              <li>
                {t(
                  "بک‌تست: اجرای ربات روی داده‌های گذشته. چون پس از دیدن داده ساخته می‌شود، می‌تواند خوش‌بینانه‌تر از واقعیت باشد.",
                  "Backtest: running the bot on past data. Because it is built after the data is known, it can be more optimistic than reality.",
                )}
              </li>
              <li>
                {t(
                  "آزمون پیشرو (همین صفحه): ربات‌ها در زمان واقعی و بدون دانستن آینده با قیمت‌های زندهٔ بازار اجرا می‌شوند، اما سفارش‌ها شبیه‌سازی‌اند و پولی جابه‌جا نمی‌شود.",
                  "Forward test (this page): the bots run in real time on live market prices without knowing the future, but orders are simulated and no money moves.",
                )}
              </li>
              <li>
                {t(
                  "نتیجهٔ زنده: معامله با پول واقعی در صرافی؛ این صفحه نتیجهٔ زنده نیست و نباید به‌جای آن خوانده شود.",
                  "Live results: trading with real money on an exchange. This page is not a live result and should not be read as one.",
                )}
              </li>
            </ul>
            <h3>{t("محدودیت‌های معامله کاغذی", "Limits of paper trading")}</h3>
            <p>
              {t(
                "شبیه‌ساز کارمزد رفت‌وبرگشت را با نرخ ثابت (۰٫۱۲٪ ارزش معامله) از سود و زیان کم می‌کند. لغزش قیمت واقعی در اجرای سفارش و هزینهٔ تأمین مالی (فاندینگ) در این نتایج لحاظ نشده است؛ در معامله با پول واقعی ممکن است نتایج کمتر باشد. همچنین دادهٔ کوتاه‌مدت از نظر آماری ضعیف است و عملکرد گذشته تضمینی برای آینده نیست.",
                "The simulator deducts a fixed round-trip fee (0.12% of trade value) from each result. Real order slippage and funding payments are not charged in these figures, so real-money results may be lower. Short data histories are also statistically weak, and past performance does not guarantee future results.",
              )}
            </p>
            <h3>{t("چه چیزی نمایش داده می‌شود", "What is shown")}</h3>
            <p>
              {t(
                "فقط مقادیر روزانه و تجمیعی تا پایان آخرین روز کامل UTC. شاخص سرمایه از ۱۰۰ شروع می‌شود و اندازهٔ حساب منتشر نمی‌شود. جزئیات معاملات منتشر نمی‌شود.",
                "Only daily, aggregated values up to the end of the last full UTC day. The equity index starts at 100 and account size is not published. Trade details are not published.",
              )}
            </p>
            <p className="forward-risk" role="note">
              {t(
                "هشدار ریسک: معامله در بازار فیوچرز ریسک از دست دادن سرمایه دارد و هیچ سودی تضمین نمی‌شود. این صفحه توصیهٔ سرمایه‌گذاری نیست.",
                "Risk warning: futures trading carries the risk of losing capital and no profit is guaranteed. This page is not investment advice.",
              )}
            </p>
            <p>
              <a className="landing-secondary" href={path("/") + "#backtest"}>
                {t("دیدن کارنامهٔ بک‌تست", "See the backtest record")}
              </a>{" "}
              <a className="landing-primary" href={path("/register/")}>
                {t("ساخت حساب", "Create account")}
              </a>
            </p>
          </section>
        </main>
        <SiteFooter lang={lang} />
      </div>
    </LangProvider>
  );
}
