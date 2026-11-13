import ThemeSwitcher from "./theme-switcher";
import { BrandLogo } from "./shared";

// Header and footer shared by the landing page and the blog, so every public page links the same way.
export function SiteHeader({ home = false }: { home?: boolean }) {
  const prefix = home ? "" : "/";
  return (
    <header className="landing-header">
      <BrandLogo />
      <nav aria-label="ناوبری اصلی">
        <a href={prefix + "#why"}>چرا آوینا</a>
        <a href={prefix + "#backtest"}>کارنامهٔ پنج‌ساله</a>
        <a href={prefix + "#strategies"}>استراتژی‌ها</a>
        <a href={prefix + "#products"}>پلن‌ها</a>
        <a href="/blog/">بلاگ</a>
        <a href={prefix + "#faq"}>پرسش‌ها</a>
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
  );
}

export function SiteFooter() {
  return (
    <footer className="landing-footer">
      <BrandLogo />
      <p>
        آوینا، ربات معامله‌گر هوشمند از خانوادهٔ ARTAX. معامله در بازارهای مالی
        ریسک از دست دادن سرمایه دارد و نتایج بک‌تست تضمین‌کنندهٔ بازده آینده
        نیستند.
      </p>
      <nav aria-label="پیوندهای پایانی">
        <a href="/blog/">بلاگ</a>
        <a href="/#faq">پرسش‌های پرتکرار</a>
        <a href="/dashboard/">ورود</a>
        <a href="/register/">ثبت‌نام</a>
        <a href="/backtest/methodology-fa.md">روش بک‌تست</a>
      </nav>
    </footer>
  );
}
