import snapshot from "@/public/backtest/five-year-summary.json";
import { money, num, percent } from "@/lib/format";
import { localPath, pick, type Lang } from "@/lib/i18n";
import { LangProvider } from "@/lib/lang";
import BacktestMotion from "./backtest-motion";
import PublicProducts from "./public-products";
import { SiteFooter, SiteHeader } from "./site-chrome";
import LatestPosts from "./latest-posts";

const MONTHS: Record<Lang, string[]> = {
  fa: ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن", "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

/** The months of a calendar year that the backtest actually covers, from its monthly series. */
function coverage(year: number, lang: Lang) {
  const months = snapshot.monthly
    .filter((m) => m.month.startsWith(year + "-"))
    .map((m) => Number(m.month.slice(5)));
  if (!months.length) return "";
  const first = Math.min(...months),
    last = Math.max(...months),
    t = pick(lang);
  const span =
    first === last
      ? MONTHS[lang][first - 1]
      : MONTHS[lang][first - 1] + t(" تا ", "–") + MONTHS[lang][last - 1];
  return `${span} (${num(months.length, lang)} ${t("ماه", months.length === 1 ? "month" : "months")})`;
}

function content(lang: Lang) {
  const t = pick(lang);
  const steps = [
    {
      name: t("حساب بسازید و پلن را انتخاب کنید", "Create an account and pick a plan"),
      text: t(
        "ثبت‌نام کمتر از یک دقیقه طول می‌کشد. پلن سیگنال یا معاملهٔ خودکار را متناسب با سرمایه‌تان انتخاب کنید.",
        "Sign-up takes under a minute. Choose the signals plan or automated trading to match your capital.",
      ),
    },
    {
      name: t("حساب صرافی خودتان را وصل کنید", "Connect your own exchange account"),
      text: t(
        "کلید API را بدون دسترسی برداشت بسازید و در پنل ثبت کنید. پول از حساب صرافی شما خارج نمی‌شود.",
        "Create an API key without withdrawal permission and add it in your panel. Your funds never leave your exchange account.",
      ),
    },
    {
      name: t("معاملات را در پنل دنبال کنید", "Follow every trade in your panel"),
      text: t(
        "سیگنال‌ها، پوزیشن‌های باز، حد ضررها و نتیجهٔ هر معامله را لحظه‌به‌لحظه در پنل اختصاصی ببینید.",
        "See signals, open positions, stop-losses and the result of every trade in your private panel, live.",
      ),
    },
  ];
  // The same questions feed the visible FAQ and its structured data, so the two can never disagree.
  const faqs = [
    {
      q: t("آوینا چیست و چه کاری انجام می‌دهد؟", "What is Avina and what does it do?"),
      a: t(
        "آوینا یک ربات معامله‌گر هوشمند ارز دیجیتال از خانوادهٔ ARTAX است که شبانه‌روز روی بازار فیوچرز معامله می‌کند و برای هر معامله حد ضرر و اندازهٔ پوزیشن مشخص دارد.",
        "Avina is a smart crypto trading bot from the ARTAX family. It trades futures around the clock, with a defined stop-loss and position size for every trade.",
      ),
    },
    {
      q: t("آیا باید پولم را به آوینا واریز کنم؟", "Do I have to deposit money with Avina?"),
      a: t(
        "نه. سرمایه در حساب صرافی خودتان می‌ماند. آوینا فقط با کلید API معامله می‌کند و این کلید باید بدون دسترسی برداشت ساخته شود.",
        "No. Your capital stays in your own exchange account. Avina trades only through an API key, which must be created without withdrawal permission.",
      ),
    },
    {
      q: t("آیا ربات معامله‌گر آوینا سود را تضمین می‌کند؟", "Does the Avina trading bot guarantee profit?"),
      a: t(
        "نه. هیچ ربات تریدری نمی‌تواند سود را تضمین کند. کارنامهٔ پنج‌ساله یک شبیه‌سازی تاریخی است، نه نتیجهٔ حساب زنده. معامله در بازار فیوچرز ریسک از دست دادن سرمایه دارد.",
        "No. No trading bot can guarantee profit. The five-year record is a historical simulation, not a live account result. Futures trading carries the risk of losing capital.",
      ),
    },
    {
      q: t("تفاوت پلن سیگنال با معاملهٔ خودکار چیست؟", "What is the difference between signals and automated trading?"),
      a: t(
        "در پلن سیگنال، نقطهٔ ورود، حد ضرر و هدف را دریافت می‌کنید و خودتان معامله را اجرا می‌کنید؛ کلید صرافی لازم نیست. در پلن معاملهٔ خودکار، ربات ورود و مدیریت معامله را انجام می‌دهد.",
        "With signals you receive the entry, stop-loss and target and place the trade yourself; no exchange key is needed. With automated trading the bot enters and manages the trade for you.",
      ),
    },
    {
      q: t("حد ضرر در آوینا چطور کار می‌کند؟", "How do stop-losses work in Avina?"),
      a: t(
        "هر پوزیشن از لحظهٔ ورود حد ضرر ثبت‌شده روی خود صرافی دارد. ربات بعد از هر تغییر، حد ضرر را دوباره از صرافی می‌خواند تا مطمئن شود درست ثبت شده است.",
        "Every position has a stop-loss placed on the exchange itself from the moment it opens. After every change the bot reads the stop back from the exchange to confirm it is in place.",
      ),
    },
    {
      q: t("نتایج بک‌تست آوینا را چطور بررسی کنم؟", "How can I check Avina's backtest results?"),
      a: t(
        "دادهٔ روزانهٔ پنج سال، خلاصهٔ نتایج و روش محاسبه در همین صفحه قابل دانلود است. کارمزد، لغزش قیمت و فاندینگ در مدل لحاظ شده‌اند و محدودیت‌های شبیه‌سازی هم نوشته شده است.",
        "Five years of daily data, the results summary and the calculation method can be downloaded on this page. Fees, slippage and funding are included, and the simulation's limits are stated.",
      ),
    },
  ];
  return { steps, faqs };
}

export default function Landing({ lang = "fa" }: { lang?: Lang }) {
  const t = pick(lang),
    path = (p: string) => localPath(lang, p);
  const { steps, faqs } = content(lang);
  const faqSchema = JSON.stringify({
    "@context": "https://schema.org",
    "@type": "FAQPage",
    inLanguage: lang,
    mainEntity: faqs.map((item) => ({
      "@type": "Question",
      name: item.q,
      acceptedAnswer: { "@type": "Answer", text: item.a },
    })),
  }).replace(/</g, "\\u003c");
  const pct = (value: number) => percent(value, lang);
  const methodology =
    lang === "en" ? "/backtest/methodology-en.md" : "/backtest/methodology-fa.md";
  return (
    <LangProvider lang={lang}>
      <div className="landing" id="landing-page">
        <a className="skip-link" href="#landing-main">
          {t("رفتن به محتوا", "Skip to content")}
        </a>
        <SiteHeader home lang={lang} />
        <main id="landing-main">
          <section className="landing-hero" aria-labelledby="hero-title">
            <div className="hero-orbit-background" aria-hidden="true" />
            <div className="landing-hero-copy">
              <h1 id="hero-title">
                <span className="hero-kicker">
                  {t("ربات معامله‌گر هوشمند ارز دیجیتال", "Smart crypto trading bot")}
                </span>
                {t("بازار هیچ‌وقت نمی‌خوابد.", "The market never sleeps.")}
                <br />
                <em>{t("آوینا هم.", "Neither does Avina.")}</em>
              </h1>
              <p className="landing-intro">
                {t(
                  "آوینا ربات ترید فیوچرز است که شبانه‌روز معامله می‌کند؛ بدون ترس، بدون طمع، با حد ضرر ثبت‌شده روی خود صرافی و اندازهٔ پوزیشن متناسب با سرمایهٔ شما. سرمایه همیشه در حساب صرافی خودتان می‌ماند.",
                  "Avina is a futures trading bot that works around the clock: no fear, no greed, a stop-loss placed on the exchange itself and position sizes matched to your capital. Your funds always stay in your own exchange account.",
                )}
              </p>
              <dl className="hero-stats">
                <div>
                  <dt>{t("رشد سالانهٔ مرکب (CAGR)", "Compound annual growth (CAGR)")}</dt>
                  <dd>{pct(snapshot.cagr_pct)}</dd>
                </div>
                <div>
                  <dt>{t("بازهٔ آزمون", "Test period")}</dt>
                  <dd>{t("۵ سال", "5 years")}</dd>
                </div>
                <div className="proof-risk">
                  <dt>{t("بیشترین افت سرمایه", "Max drawdown")}</dt>
                  <dd>{pct(snapshot.max_minute_dd_pct)}</dd>
                </div>
              </dl>
              <div className="landing-hero-actions">
                <a className="landing-primary" href="#backtest">
                  {t("کارنامهٔ پنج‌ساله را ببینید", "See the five-year record")}
                </a>
                <a className="landing-secondary" href={path("/register/")}>
                  {t("شروع با آوینا", "Start with Avina")}
                </a>
              </div>
              <p className="hero-disclosure">
                {t(
                  "شبیه‌سازی تاریخی با هزینه‌های مدل‌شده؛ نتیجهٔ حساب زنده نیست و عملکرد آینده را تضمین نمی‌کند.",
                  "Historical simulation with modeled costs; not a live account result and no guarantee of future performance.",
                )}
              </p>
            </div>
            <div className="landing-hero-visual">
              <BacktestMotion />
            </div>
          </section>
          <div className="landing-proof-strip">
            <div>
              <span>{t("بازهٔ کامل آزمون", "Full test period")}</span>
              <strong>
                {t("۵ سال", "5 years")} / {num(snapshot.days, lang)} {t("روز", "days")}
              </strong>
            </div>
            <div>
              <span>{t("سرمایهٔ اولیه", "Starting capital")}</span>
              <strong>{money(snapshot.initial, lang)}</strong>
            </div>
            <div>
              <span>{t("ارزش شبیه‌سازی‌شدهٔ پایان دوره", "Simulated final value")}</span>
              <strong>{money(Math.round(snapshot.final), lang)}</strong>
            </div>
            <div>
              <span>{t("رشد سالانهٔ مرکب", "CAGR")}</span>
              <strong>{pct(snapshot.cagr_pct)}</strong>
            </div>
            <div className="proof-risk">
              <span>{t("بیشترین افت سرمایهٔ دقیقه‌ای", "Max minute drawdown")}</span>
              <strong>{pct(snapshot.max_minute_dd_pct)}</strong>
            </div>
          </div>
          <section id="why" className="landing-section">
            <div className="landing-section-heading">
              <div>
                <span className="eyebrow">WHY AVINA</span>
                <h2>{t("انضباطی که انسان‌ها کم می‌آورند.", "The discipline people run short of.")}</h2>
              </div>
              <p>
                {t(
                  "بیشتر ضررها از تصمیم‌های احساسی و ریسک کنترل‌نشده می‌آیند. آوینا برای همین ساخته شده که قوانین را هر بار، بدون استثنا، اجرا کند.",
                  "Most losses come from emotional decisions and uncontrolled risk. Avina is built to follow its rules every time, without exception.",
                )}
              </p>
            </div>
            <div className="strategy-cards">
              {[
                {
                  code: "01",
                  label: "NON-CUSTODIAL",
                  name: t("سرمایه در حساب خودتان", "Funds stay in your account"),
                  text: t(
                    "آوینا به حساب صرافی شما وصل می‌شود و فقط معامله می‌کند. هیچ واریزی به ما لازم نیست و کلید API شما بدون دسترسی برداشت ثبت می‌شود.",
                    "Avina connects to your exchange account and only trades. You never deposit with us, and your API key is registered without withdrawal permission.",
                  ),
                },
                {
                  code: "02",
                  label: "REAL STOP-LOSS",
                  name: t("حد ضرر واقعی روی صرافی", "A real stop-loss on the exchange"),
                  text: t(
                    "هر پوزیشن از لحظهٔ ورود حد ضرر ثبت‌شده روی خود صرافی دارد و ربات بعد از هر تغییر، آن را دوباره از صرافی می‌خواند و تأیید می‌کند.",
                    "Every position carries a stop-loss on the exchange from the moment it opens, and the bot reads it back to confirm it after every change.",
                  ),
                },
                {
                  code: "03",
                  label: "RISK ENGINE",
                  name: t("مدیریت ریسک چندلایه", "Layered risk management"),
                  text: t(
                    "سقف ریسک هر معامله، سقف ریسک کل، توقف ورود در ضرر روزانه و افت سرمایه، و اندازهٔ پوزیشن متناسب با موجودی لحظه‌ای حساب.",
                    "Per-trade and total risk caps, entry stops on daily loss and drawdown, and position sizes matched to your live balance.",
                  ),
                },
                {
                  code: "04",
                  label: "TRANSPARENT",
                  name: t("شفاف و قابل بررسی", "Transparent and verifiable"),
                  text: t(
                    "کارنامهٔ پنج‌ساله با دادهٔ روزانه و روش محاسبه منتشر شده و همهٔ معاملات و وضعیت ربات‌ها در پنل اختصاصی شما دیده می‌شود.",
                    "The five-year record is published with daily data and its method, and every trade and bot status is visible in your private panel.",
                  ),
                },
              ].map((item) => (
                <article key={item.code}>
                  <div className="strategy-card-head">
                    <span>{item.code}</span>
                    <small>{item.label}</small>
                  </div>
                  <h3>{item.name}</h3>
                  <p>{item.text}</p>
                </article>
              ))}
            </div>
          </section>
          <section id="backtest" className="landing-section results-section">
            <div className="landing-section-heading">
              <div>
                <span className="eyebrow">EVIDENCE BEFORE DECISION</span>
                <h2>{t("کارنامه، پیش از تصمیم.", "The record, before you decide.")}</h2>
              </div>
              <p>
                {t(
                  "پنج سال اجرای شبیه‌سازی‌شدهٔ هر سه ربات روی یک حساب، با سرمایه‌گذاری مجدد سود. دادهٔ روزانه و روش محاسبه را خودتان دانلود و بررسی کنید.",
                  "Five simulated years of all three bots on one account, with profits reinvested. Download the daily data and the method and check them yourself.",
                )}
              </p>
            </div>
            <div className="results-layout">
              <article className="result-feature">
                <span>
                  {t(
                    "از ۱ ژانویهٔ ۲۰۲۱ تا ۳۱ دسامبر ۲۰۲۵ UTC",
                    "1 January 2021 to 31 December 2025 UTC",
                  )}
                </span>
                <h3>
                  <bdi>{money(snapshot.initial, lang)}</bdi>
                  <span className="result-to">{t("به", "to")}</span>
                  <bdi>{money(Math.round(snapshot.final), lang)}</bdi>
                </h3>
                <p>
                  {t("رشد سالانهٔ مرکب: ", "Compound annual growth: ")}
                  <strong>{pct(snapshot.cagr_pct)}</strong>
                  {t(" · بازده کل مدل: ", " · Total model return: ")}
                  <strong>{pct(snapshot.return_pct)}</strong>
                  {t(
                    ". رشد مرکب و اندازه‌گذاری مجدد معاملات در این نتیجه اثر دارند؛ این عدد، وعدهٔ بازده آینده نیست.",
                    ". Compounding and re-sizing shape this result; it is not a promise of future returns.",
                  )}
                </p>
                <div className="results-downloads">
                  <a href="/backtest/five-year-daily.csv" download>
                    {t("دریافت دادهٔ روزانه", "Download daily data")}
                  </a>
                  <a href="/backtest/five-year-summary.json" download>
                    {t("دریافت خلاصه و فرض‌ها", "Download summary and assumptions")}
                  </a>
                  <a href={methodology} download>
                    {t("روش محاسبه", "Calculation method")}
                  </a>
                </div>
              </article>
              <div className="annual-result-table">
                <table>
                  <caption>
                    {t("ارزش شبیه‌سازی‌شدهٔ پایان هر سال", "Simulated value at each year end")}
                  </caption>
                  <thead>
                    <tr>
                      <th>{t("سال میلادی", "Year")}</th>
                      <th>{t("ماه‌های آزمون", "Months tested")}</th>
                      <th>{t("ارزش حساب", "Account value")}</th>
                      <th>{t("بازده همان سال", "Return that year")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.annual.map((row) => (
                      <tr key={row.year}>
                        <td>{lang === "en" ? row.year : num(row.year, lang)}</td>
                        <td className="annual-months">{coverage(row.year, lang)}</td>
                        <td>{money(Math.round(row.equity), lang)}</td>
                        <td>
                          <bdi
                            className={
                              row.return_pct < 0
                                ? "financial-loss"
                                : "financial-profit"
                            }
                          >
                            {row.return_pct > 0 ? "+" : ""}
                            {pct(row.return_pct)}
                          </bdi>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <details className="methodology-details">
              <summary>
                {t("بک‌تست با چه فرض‌هایی محاسبه شده؟", "What assumptions does the backtest use?")}{" "}
                <span aria-hidden="true">＋</span>
              </summary>
              <div className="methodology-grid">
                <div>
                  <h3>{t("داده و سناریو", "Data and scenario")}</h3>
                  <p>
                    {t(
                      "قیمت‌های Binance USDⓈ-M futures، سه ربات روی یک حساب، سرمایهٔ اولیهٔ ۱۰٬۰۰۰ دلار، بدون واریز یا برداشت و با سرمایه‌گذاری مجدد سود. هر USDT برابر یک دلار فرض شده است.",
                      "Binance USDⓈ-M futures prices, three bots on one account, $10,000 starting capital, no deposits or withdrawals, profits reinvested. One USDT is assumed to equal one dollar.",
                    )}
                  </p>
                </div>
                <div>
                  <h3>{t("هزینه و ریسک مدل", "Costs and model risk")}</h3>
                  <p>
                    {t(
                      "کارمزد ۰٫۰۶٪ هر طرف، لغزش ۲ واحد پایه در هر fill، فاندینگ ثبت‌شده، اهرم ۵ و سقف مارجین مشترک ۸۰٪. عمق بازار و مدل کامل لیکوییدیشن با Mark Price بازسازی نشده‌اند.",
                      "0.06% fee per side, 2 basis points of slippage per fill, recorded funding, 5x leverage and an 80% shared margin cap. Order-book depth and full mark-price liquidation are not modeled.",
                    )}
                  </p>
                </div>
                <div>
                  <h3>{t("معنای نمودار و افت سرمایه", "What the chart and drawdown mean")}</h3>
                  <p>
                    {t(
                      "منحنی از ارزش پایان روز روی محور لگاریتمی ساخته شده است. DD از بدترین افت پایان دقیقه محاسبه می‌شود؛ افت تیک و داخل دقیقه در این عدد نیست.",
                      "The curve plots end-of-day value on a log scale. Drawdown uses the worst minute-close decline; tick and intra-minute moves are not included.",
                    )}
                  </p>
                </div>
                <div>
                  <h3>{t("حدود نتیجه", "Limits of the result")}</h3>
                  <p>
                    {t(
                      "این اجرای زندهٔ صرافی یا تست رو به جلوی مستقل نیست. تنظیمات پژوهش روی گذشته آزموده شده‌اند و نتیجه ریسک انتخاب تنظیمات براساس تاریخچه دارد. هیچ سودی تضمین نمی‌شود.",
                      "This is not a live exchange run or an independent forward test. The settings were tested on past data, so the result carries the risk of fitting to history. No profit is guaranteed.",
                    )}
                  </p>
                </div>
              </div>
            </details>
          </section>
          <section id="strategies" className="landing-section">
            <div className="landing-section-heading">
              <div>
                <span className="eyebrow">THREE ENGINES, ONE ACCOUNT</span>
                <h2>{t("سه موتور. یک حساب. ریسک پخش‌شده.", "Three engines. One account. Spread risk.")}</h2>
              </div>
              <p>
                {t(
                  "سه ربات مستقل که هر کدام بازار را به روش خودش می‌خواند؛ وقتی یکی ساکت است، دیگری فرصت را می‌بیند. ریسک هر سه از یک بودجهٔ مشترک کنترل می‌شود. منطق معاملاتی ربات‌ها اختصاصی است و منتشر نمی‌شود.",
                  "Three independent bots, each reading the market its own way; when one is quiet, another finds the opportunity. All three draw on one shared risk budget. The trading logic is proprietary and not published.",
                )}
              </p>
            </div>
            <div className="strategy-cards">
              {[
                { code: "S", name: t("شاهین", "Falcon") },
                { code: "M", name: t("موج‌سوار", "Wave Rider") },
                { code: "G", name: t("ققنوس", "Phoenix") },
              ].map((bot) => (
                <article key={bot.code}>
                  <div className="strategy-card-head">
                    <span>{bot.code}</span>
                    <small>AVINA ENGINE</small>
                  </div>
                  <h3>{bot.name}</h3>
                  <p>
                    {t(
                      "موتور مستقل با قوانین ورود و خروج خودش، حد ضرر روی صرافی و سهم مشخص از بودجهٔ ریسک حساب.",
                      "An independent engine with its own entry and exit rules, an on-exchange stop-loss and a fixed share of the account's risk budget.",
                    )}
                  </p>
                </article>
              ))}
            </div>
          </section>
          <section id="how" className="landing-section">
            <div className="landing-section-heading">
              <div>
                <span className="eyebrow">HOW IT WORKS</span>
                <h2>{t("شروع کار با آوینا در سه قدم.", "Get started with Avina in three steps.")}</h2>
              </div>
              <p>
                {t(
                  "راه‌اندازی ربات معامله‌گر نباید پیچیده باشد. از ثبت‌نام تا دیدن اولین سیگنال، همه‌چیز در پنل خودتان انجام می‌شود.",
                  "Setting up a trading bot should not be complicated. From sign-up to your first signal, everything happens in your own panel.",
                )}
              </p>
            </div>
            <ol className="landing-steps">
              {steps.map((step, index) => (
                <li key={step.name}>
                  <span aria-hidden="true">{num(index + 1, lang)}</span>
                  <h3>{step.name}</h3>
                  <p>{step.text}</p>
                </li>
              ))}
            </ol>
          </section>
          <section id="products" className="landing-section landing-products">
            <div>
              <span className="eyebrow">CHOOSE YOUR PLAN</span>
              <h2>
                {t("سیگنال برای تصمیم خودتان.", "Signals for your own decisions.")}
                <br />
                {t("یا معاملهٔ خودکار با آوینا.", "Or automated trading with Avina.")}
              </h2>
              <p>
                {t(
                  "حساب بسازید، پلن را بر اساس سرمایه‌تان انتخاب کنید و با USDT یا USDC پرداخت کنید. فعال‌سازی پس از تأیید پرداخت انجام می‌شود.",
                  "Create an account, choose a plan for your capital and pay in USDT or USDC. Your plan is activated once the payment is confirmed.",
                )}
              </p>
              <a className="landing-primary" href={path("/register/")}>
                {t("شروع با آوینا", "Start with Avina")}
              </a>
            </div>
            <PublicProducts />
          </section>
          <section id="blog" className="landing-section">
            <div className="landing-section-heading">
              <div>
                <span className="eyebrow">AVINA JOURNAL</span>
                <h2>{t("یاد بگیرید، بعد معامله کنید.", "Learn first, then trade.")}</h2>
              </div>
              <p>
                {t(
                  "راهنماهای کوتاه دربارهٔ ربات ترید، حد ضرر و مدیریت ریسک در بازار فیوچرز.",
                  "Short guides on trading bots, stop-losses and risk management in futures.",
                )}{" "}
                <a href={path("/blog/")}>{t("همهٔ مقاله‌ها", "All articles")}</a>
              </p>
            </div>
            <LatestPosts />
          </section>
          <section id="faq" className="landing-section">
            <div className="landing-section-heading">
              <div>
                <span className="eyebrow">FAQ</span>
                <h2>{t("پرسش‌های پرتکرار دربارهٔ ربات آوینا.", "Frequently asked questions about Avina.")}</h2>
              </div>
              <p>
                {t(
                  "پاسخ کوتاه و روشن به سؤال‌هایی که پیش از شروع برای بیشتر معامله‌گرها پیش می‌آید.",
                  "Short, clear answers to the questions most traders ask before they start.",
                )}
              </p>
            </div>
            <div className="landing-faq">
              {faqs.map((item) => (
                <details key={item.q}>
                  <summary>
                    <h3>{item.q}</h3>
                    <span aria-hidden="true">＋</span>
                  </summary>
                  <p>{item.a}</p>
                </details>
              ))}
            </div>
            <script
              type="application/ld+json"
              dangerouslySetInnerHTML={{ __html: faqSchema }}
            />
          </section>
          <section className="landing-closing">
            <span className="eyebrow">AVINA by ARTAX</span>
            <h2>
              {t("آوینا را با شواهد بسنجید،", "Judge Avina by its evidence,")}
              <br />
              <em>{t("نه با وعده.", "not by promises.")}</em>
            </h2>
            <div>
              <a className="landing-primary" href="#backtest">
                {t("بررسی نتایج بک‌تست", "Review the backtest")}
              </a>
              <a className="landing-secondary" href={path("/dashboard/")}>
                {t("ورود به پنل", "Sign in")}
              </a>
            </div>
          </section>
        </main>
        <SiteFooter lang={lang} />
      </div>
    </LangProvider>
  );
}
