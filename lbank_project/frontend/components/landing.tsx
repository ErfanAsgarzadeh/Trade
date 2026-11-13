import ThemeSwitcher from "./theme-switcher";
import snapshot from "@/public/backtest/five-year-summary.json";
import { faNumber, usd } from "@/lib/format";
import BacktestMotion from "./backtest-motion";
import PublicProducts from "./public-products";
import { Arrow, BrandLogo } from "./shared";

export default function Landing() {
  return (
    <div className="landing" id="landing-page">
      <a className="skip-link" href="#landing-main">
        رفتن به محتوا
      </a>
      <header className="landing-header">
        <BrandLogo />
        <nav aria-label="ناوبری اصلی">
          <a href="#why">چرا آوینا</a>
          <a href="#backtest">کارنامهٔ پنج‌ساله</a>
          <a href="#strategies">استراتژی‌ها</a>
          <a href="#products">پلن‌ها</a>
        </nav>
        <div className="landing-header-actions">
          <ThemeSwitcher />
          <a href="/dashboard/" className="landing-login">
            ورود به پنل
          </a>
          <a href="/register/" className="landing-signup">
            ساخت حساب <span aria-hidden="true">←</span>
          </a>
        </div>
      </header>
      <main id="landing-main">
        <section className="landing-hero" aria-labelledby="hero-title">
          <div className="hero-orbit-background" aria-hidden="true" />
          <div className="landing-hero-copy">
            <div className="landing-eyebrow">
              <span />
              SMART TRADING BOT · by ARTAX
            </div>
            <h1 id="hero-title">
              بازار هیچ‌وقت نمی‌خوابد.
              <br />
              <em>آوینا هم.</em>
            </h1>
            <p className="landing-intro">
              آوینا سه استراتژی معاملاتی را شبانه‌روز روی بازار فیوچرز اجرا
              می‌کند؛ بدون ترس، بدون طمع، با حد ضرر ثبت‌شده روی خود صرافی و
              اندازهٔ پوزیشن متناسب با سرمایهٔ شما. سرمایه همیشه در حساب صرافی
              خودتان می‌ماند.
            </p>
            <div className="landing-hero-actions">
              <a className="landing-primary" href="#backtest">
                کارنامهٔ پنج‌ساله را ببینید <span aria-hidden="true">←</span>
              </a>
              <a className="landing-secondary" href="/register/">
                شروع با آوینا ←
              </a>
            </div>
            <div className="hero-context">
              <span>اجرای ۲۴/۷</span>
              <span>حد ضرر روی صرافی</span>
              <span>سرمایه در حساب خودتان</span>
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
        <section id="why" className="landing-section">
          <div className="landing-section-heading">
            <div>
              <span className="eyebrow">WHY AVINA</span>
              <h2>انضباطی که انسان‌ها کم می‌آورند.</h2>
            </div>
            <p>
              بیشتر ضررها از تصمیم‌های احساسی و ریسک کنترل‌نشده می‌آیند. آوینا
              برای همین ساخته شده که قوانین را هر بار، بدون استثنا، اجرا کند.
            </p>
          </div>
          <div className="strategy-cards">
            {[
              {
                code: "01",
                label: "NON-CUSTODIAL",
                name: "سرمایه در حساب خودتان",
                text: "آوینا به حساب صرافی شما وصل می‌شود و فقط معامله می‌کند. هیچ واریزی به ما لازم نیست و کلید API شما بدون دسترسی برداشت ثبت می‌شود.",
              },
              {
                code: "02",
                label: "REAL STOP-LOSS",
                name: "حد ضرر واقعی روی صرافی",
                text: "هر پوزیشن از لحظهٔ ورود حد ضرر ثبت‌شده روی خود صرافی دارد و ربات بعد از هر تغییر، آن را دوباره از صرافی می‌خواند و تأیید می‌کند.",
              },
              {
                code: "03",
                label: "RISK ENGINE",
                name: "مدیریت ریسک چندلایه",
                text: "سقف ریسک هر معامله، سقف ریسک کل، توقف ورود در ضرر روزانه و افت سرمایه، و اندازهٔ پوزیشن متناسب با موجودی لحظه‌ای حساب.",
              },
              {
                code: "04",
                label: "TRANSPARENT",
                name: "شفاف و قابل بررسی",
                text: "کارنامهٔ پنج‌ساله با دادهٔ روزانه و روش محاسبه منتشر شده و همهٔ معاملات و وضعیت ربات‌ها در پنل اختصاصی شما دیده می‌شود.",
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
              <h2>کارنامه، پیش از تصمیم.</h2>
            </div>
            <p>
              پنج سال اجرای شبیه‌سازی‌شدهٔ هر سه استراتژی روی یک حساب، با
              سرمایه‌گذاری مجدد سود. دادهٔ روزانه و روش محاسبه را خودتان دانلود و
              بررسی کنید.
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
                  اولیهٔ ۱۰٬۰۰۰ دلار، بدون واریز یا برداشت و با
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
              <span className="eyebrow">THREE ENGINES, ONE ACCOUNT</span>
              <h2>سه موتور. یک حساب. ریسک پخش‌شده.</h2>
            </div>
            <p>
              هر استراتژی بازار را از زاویهٔ خودش می‌خواند؛ وقتی یکی ساکت است،
              دیگری فرصت را می‌بیند. ریسک هر سه از یک بودجهٔ مشترک کنترل می‌شود.
            </p>
          </div>
          <div className="strategy-cards">
            {[
              {
                code: "S",
                name: "شاهین",
                label: "BREAKOUT",
                text: "شکار شکست‌های قدرتمند روند با Donchian و ابر ایچیموکو؛ با حد ضرر متحرک و قفل سود وقتی معامله به سود می‌رسد.",
              },
              {
                code: "M",
                name: "موج‌سوار",
                label: "TREND PULLBACK",
                text: "ورود در پولبک‌های روند با EMA و RSI؛ صبر برای تأیید، سوار شدن بر موج و همراهی با حد ضرر دنباله‌دار.",
              },
              {
                code: "G",
                name: "ققنوس",
                label: "PRICE ACTION",
                text: "خواندن رفتار قیمت و الگوهای برگشتی کلیدی، با فیلتر رژیم بازار؛ برای لحظه‌هایی که روند نفسش می‌بُرد.",
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
            <span className="eyebrow">CHOOSE YOUR PLAN</span>
            <h2>
              سیگنال برای تصمیم خودتان.
              <br />
              یا معاملهٔ خودکار با آوینا.
            </h2>
            <p>
              حساب بسازید، پلن را بر اساس سرمایه‌تان انتخاب کنید و با USDT یا
              USDC پرداخت کنید. فعال‌سازی پس از تأیید خودکار پرداخت انجام
              می‌شود.
            </p>
            <a className="landing-primary" href="/register/">
              شروع با آوینا ←
            </a>
          </div>
          <PublicProducts />
        </section>
        <section className="landing-closing">
          <span className="eyebrow">AVINA by ARTAX</span>
          <h2>
            آوینا را با شواهد بسنجید،
            <br />
            <em>نه با وعده.</em>
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
        <BrandLogo />
        <p>
          آوینا، ربات معامله‌گر هوشمند از خانوادهٔ ARTAX. معامله در بازارهای
          مالی ریسک از دست دادن سرمایه دارد و نتایج بک‌تست تضمین‌کنندهٔ بازده
          آینده نیستند.
        </p>
        <nav>
          <a href="/dashboard/">ورود</a>
          <a href="/register/">ثبت‌نام</a>
          <a href="/backtest/methodology-fa.md">روش بک‌تست</a>
        </nav>
      </footer>
    </div>
  );
}
