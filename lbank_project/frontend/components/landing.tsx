import ThemeSwitcher from "./theme-switcher";
import snapshot from "@/public/backtest/five-year-summary.json";
import { faNumber, usd } from "@/lib/format";
import BacktestMotion from "./backtest-motion";
import PublicProducts from "./public-products";
import { Arrow } from "./shared";

export default function Landing() {
  return (
    <div className="landing" id="landing-page">
      <a className="skip-link" href="#landing-main">
        رفتن به محتوا
      </a>
      <header className="landing-header">
        <a className="logo" href="/" aria-label="Trade، صفحه اصلی">
          <span className="logo-mark">T</span>
          <span className="brand">
            TRADE<span className="brand-dot">/</span>
          </span>
        </a>
        <nav aria-label="ناوبری اصلی">
          <a href="#backtest">نتایج بک‌تست</a>
          <a href="#strategies">سه استراتژی</a>
          <a href="#products">سرویس‌ها</a>
        </nav>
        <div className="landing-header-actions">
          <ThemeSwitcher />
          <a href="/dashboard/" className="landing-login">
            ورود به پنل
          </a>
          <a href="/register/" className="landing-signup">
            شروع رایگان <span aria-hidden="true">←</span>
          </a>
        </div>
      </header>
      <main id="landing-main">
        <section className="landing-hero" aria-labelledby="hero-title">
          <div className="hero-orbit-background" aria-hidden="true" />
          <div className="landing-hero-copy">
            <div className="landing-eyebrow">
              <span />
              پنج سال بک‌تست روی داده‌های بازار
            </div>
            <h1 id="hero-title">
              سه ربات.
              <br />
              پنج سال داده.
              <br />
              <em>یک مسیر قابل بررسی.</em>
            </h1>
            <p className="landing-intro">
              شاهین، موج‌سوار و ققنوس؛ سه استراتژی در یک حساب مشترک. قبل از
              انتخاب، مسیر سرمایه و ریسک را با چشم خودتان ببینید.
            </p>
            <div className="landing-hero-actions">
              <a className="landing-primary" href="#backtest">
                نتیجهٔ پنج‌ساله را ببینید <span aria-hidden="true">←</span>
              </a>
              <a className="landing-secondary" href="/register/">
                ساخت حساب رایگان ←
              </a>
            </div>
            <div className="hero-context">
              <span>۲۰۲۱ تا پایان ۲۰۲۵</span>
              <span>بدون F</span>
              <span>بدون برداشت</span>
            </div>
            <p className="hero-disclosure">
              شبیه‌سازی تاریخی با هزینه‌های مدل‌شده؛ نتیجهٔ حساب زنده نیست و
              عملکرد آینده را تضمین نمی‌کند.
            </p>
          </div>
          <div className="landing-hero-visual">
            <div className="strategy-pills" aria-hidden="true">
              <span>
                <i>S</i> شاهین
              </span>
              <span>
                <i>M</i> موج‌سوار
              </span>
              <span>
                <i>G</i> ققنوس
              </span>
            </div>
            <BacktestMotion />
            <div className="visual-caption">
              <span className="caption-line" />
              منحنی بر اساس ارزش روزانهٔ ثبت‌شده در خروجی بک‌تست رسم شده است.
            </div>
          </div>
        </section>
        <div className="landing-proof-strip">
          <div>
            <span>بازهٔ کامل آزمون</span>
            <strong>۵ سال / {faNumber(snapshot.days)} روز</strong>
          </div>
          <div>
            <span>شروع حساب مشترک</span>
            <strong>{usd(snapshot.initial)}</strong>
          </div>
          <div>
            <span>ارزش شبیه‌سازی‌شدهٔ پایان دوره</span>
            <strong>{usd(Math.round(snapshot.final))}</strong>
          </div>
          <div className="proof-risk">
            <span>بیشترین افت سرمایهٔ دقیقه‌ای</span>
            <strong>
              {faNumber(Number(snapshot.max_minute_dd_pct.toFixed(1)))}٪
            </strong>
          </div>
        </div>
        <section id="backtest" className="landing-section results-section">
          <div className="landing-section-heading">
            <div>
              <span className="eyebrow">EVIDENCE BEFORE DECISION</span>
              <h2>عدد نهایی، فقط بخشی از داستان است.</h2>
            </div>
            <p>
              این نتیجه برای هر سه ربات با سرمایه‌گذاری مجدد سود و تنظیمات پژوهش
              است؛ نه سناریوی برداشت سود و خرید طلا.
            </p>
          </div>
          <div className="results-layout">
            <article className="result-feature">
              <span>از ۱ ژانویهٔ ۲۰۲۱ تا ۳۱ دسامبر ۲۰۲۵ UTC</span>
              <h3>
                <bdi>{usd(snapshot.initial)}</bdi>
                <Arrow />
                <bdi>{usd(Math.round(snapshot.final))}</bdi>
              </h3>
              <p>
                بازده کل مدل:{" "}
                <strong>
                  {faNumber(Number(snapshot.return_pct.toFixed(1)))}٪
                </strong>
                . رشد مرکب و اندازه‌گذاری مجدد معاملات در این نتیجه اثر دارند؛
                این عدد، وعدهٔ بازده آینده نیست.
              </p>
              <div className="results-downloads">
                <a href="/backtest/five-year-daily.csv" download>
                  دریافت دادهٔ روزانه ←
                </a>
                <a href="/backtest/five-year-summary.json" download>
                  دریافت خلاصه و فرض‌ها ←
                </a>
                <a href="/backtest/methodology-fa.md" download>
                  روش محاسبه ←
                </a>
              </div>
            </article>
            <div className="annual-result-table">
              <table>
                <caption>ارزش شبیه‌سازی‌شدهٔ پایان هر سال</caption>
                <thead>
                  <tr>
                    <th>سال میلادی</th>
                    <th>ارزش حساب</th>
                    <th>بازده همان سال</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.annual.map((row) => (
                    <tr key={row.year}>
                      <td>{faNumber(row.year)}</td>
                      <td>{usd(Math.round(row.equity))}</td>
                      <td>
                        <bdi
                          className={
                            row.return_pct < 0
                              ? "financial-loss"
                              : "financial-profit"
                          }
                        >
                          {row.return_pct > 0 ? "+" : ""}
                          {faNumber(Number(row.return_pct.toFixed(1)))}٪
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
              بک‌تست با چه فرض‌هایی محاسبه شده؟ <span>＋</span>
            </summary>
            <div className="methodology-grid">
              <div>
                <h3>داده و سناریو</h3>
                <p>
                  قیمت‌های Binance USDⓈ-M futures، سه ربات روی یک حساب، سرمایهٔ
                  اولیهٔ ۱۰٬۰۰۰ دلار، بدون F، بدون واریز یا برداشت و با
                  سرمایه‌گذاری مجدد سود. هر USDT برابر یک دلار فرض شده است.
                </p>
              </div>
              <div>
                <h3>هزینه و ریسک مدل</h3>
                <p>
                  کارمزد ۰٫۰۶٪ هر طرف، لغزش ۲ واحد پایه در هر fill، فاندینگ
                  ثبت‌شده، اهرم ۵ و سقف مارجین مشترک ۸۰٪. عمق بازار و مدل کامل
                  لیکوییدیشن با Mark Price بازسازی نشده‌اند.
                </p>
              </div>
              <div>
                <h3>معنای نمودار و افت سرمایه</h3>
                <p>
                  منحنی از ارزش پایان روز روی محور لگاریتمی ساخته شده است. DD از
                  بدترین افت پایان دقیقه محاسبه می‌شود؛ افت تیک و داخل دقیقه در
                  این عدد نیست.
                </p>
              </div>
              <div>
                <h3>حدود نتیجه</h3>
                <p>
                  این اجرای زندهٔ LBank یا تست رو به جلوی مستقل نیست. تنظیمات
                  پژوهش روی گذشته آزموده شده‌اند و نتیجه ریسک انتخاب تنظیمات
                  براساس تاریخچه دارد. هیچ سودی تضمین نمی‌شود.
                </p>
              </div>
            </div>
          </details>
        </section>
        <section id="strategies" className="landing-section">
          <div className="landing-section-heading">
            <div>
              <span className="eyebrow">THREE WAYS TO READ THE MARKET</span>
              <h2>یک بازار. سه نگاه متفاوت.</h2>
            </div>
            <p>
              استراتژی‌ها رفتار یکسانی ندارند؛ هر کدام با منطق ورود و مدیریت
              ریسک خودش کار می‌کند.
            </p>
          </div>
          <div className="strategy-cards">
            {[
              {
                code: "S",
                name: "شاهین",
                label: "BREAKOUT",
                text: "دنبال‌کردن شکست‌های روند با Donchian و Kumo؛ همراه با مدیریت استاپ و قواعد حفظ سود.",
              },
              {
                code: "M",
                name: "موج‌سوار",
                label: "TREND PULLBACK",
                text: "جست‌وجوی پولبک در روند با EMA و RSI؛ تأیید ورود و دنبال‌کردن مسیر با استاپ متحرک.",
              },
              {
                code: "G",
                name: "ققنوس",
                label: "PRICE ACTION",
                text: "بررسی رفتار قیمت و Key Reversal، با فیلتر رژیم بازار و مدیریت زمان و ریسک معامله.",
              },
            ].map((bot) => (
              <article key={bot.code}>
                <div className="strategy-card-head">
                  <span>{bot.code}</span>
                  <small>{bot.label}</small>
                </div>
                <h3>{bot.name}</h3>
                <p>{bot.text}</p>
              </article>
            ))}
          </div>
        </section>
        <section id="products" className="landing-section landing-products">
          <div>
            <span className="eyebrow">CHOOSE YOUR WORKFLOW</span>
            <h2>
              سیگنال برای تصمیم شما.
              <br />
              یا اجرای مدیریت‌شدهٔ ربات.
            </h2>
            <p>
              حساب بسازید و نوع سرویس را انتخاب کنید. قیمت و وضعیت فروش هر محصول
              مستقل است و در پنل به‌روز نمایش داده می‌شود.
            </p>
            <a className="landing-primary" href="/register/">
              ساخت حساب رایگان ←
            </a>
          </div>
          <PublicProducts />
        </section>
        <section className="landing-closing">
          <span className="eyebrow">START WITH THE EVIDENCE</span>
          <h2>
            اول بررسی کنید.
            <br />
            <em>بعد انتخاب کنید.</em>
          </h2>
          <div>
            <a className="landing-primary" href="#backtest">
              بررسی نتایج بک‌تست ←
            </a>
            <a className="landing-secondary" href="/dashboard/">
              ورود به پنل ←
            </a>
          </div>
        </section>
      </main>
      <footer className="landing-footer">
        <a className="brand" href="/">
          TRADE /
        </a>
        <p>نتایج بک‌تست تضمین‌کنندهٔ بازده آینده نیستند.</p>
        <nav>
          <a href="/dashboard/">ورود</a>
          <a href="/register/">ثبت‌نام</a>
          <a href="/backtest/methodology-fa.md">روش بک‌تست</a>
        </nav>
      </footer>
    </div>
  );
}
