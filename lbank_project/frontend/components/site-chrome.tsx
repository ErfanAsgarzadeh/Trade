import ThemeSwitcher from "./theme-switcher";
import { BrandLogo } from "./shared";
import { localPath, otherPath, pick, type Lang } from "@/lib/i18n";

/** Link to the same page in the other language. */
export function LanguageLink({ lang, path }: { lang: Lang; path: string }) {
  return (
    <a
      className="language-link"
      href={otherPath(lang, path)}
      hrefLang={lang === "fa" ? "en" : "fa"}
      lang={lang === "fa" ? "en" : "fa"}
    >
      {lang === "fa" ? "English" : "فارسی"}
    </a>
  );
}

// Header and footer shared by the landing page and the blog, so every public page links the same way.
export function SiteHeader({
  home = false,
  lang = "fa",
  page = "/",
}: {
  home?: boolean;
  lang?: Lang;
  page?: string;
}) {
  const t = pick(lang),
    path = (p: string) => localPath(lang, p);
  const anchor = (id: string) => (home ? "#" + id : path("/") + "#" + id);
  return (
    <header className="landing-header">
      <BrandLogo lang={lang} />
      <nav aria-label={t("ناوبری اصلی", "Main navigation")}>
        <a href={anchor("why")}>{t("چرا آوینا", "Why Avina")}</a>
        <a href={anchor("backtest")}>{t("کارنامهٔ پنج‌ساله", "Five-year record")}</a>
        <a href={anchor("products")}>{t("پلن‌ها", "Plans")}</a>
        <a href={path("/blog/")}>{t("بلاگ", "Blog")}</a>
        <a href={anchor("faq")}>{t("پرسش‌ها", "FAQ")}</a>
      </nav>
      <div className="landing-header-actions">
        <LanguageLink lang={lang} path={page} />
        <ThemeSwitcher />
        <a href={path("/dashboard/")} className="landing-login">
          {t("ورود به پنل", "Sign in")}
        </a>
        <a href={path("/register/")} className="landing-signup">
          {t("ساخت حساب", "Create account")}
        </a>
      </div>
    </header>
  );
}

export function SiteFooter({ lang = "fa" }: { lang?: Lang }) {
  const t = pick(lang),
    path = (p: string) => localPath(lang, p);
  return (
    <footer className="landing-footer">
      <BrandLogo lang={lang} />
      <p>
        {t(
          "آوینا، ربات معامله‌گر هوشمند از خانوادهٔ ARTAX. معامله در بازارهای مالی ریسک از دست دادن سرمایه دارد و نتایج بک‌تست تضمین‌کنندهٔ بازده آینده نیستند.",
          "Avina, a smart trading bot from the ARTAX family. Trading financial markets carries the risk of losing capital, and backtest results do not guarantee future returns.",
        )}
      </p>
      <nav aria-label={t("پیوندهای پایانی", "Footer links")}>
        <a href={path("/blog/")}>{t("بلاگ", "Blog")}</a>
        <a href={path("/") + "#faq"}>{t("پرسش‌های پرتکرار", "FAQ")}</a>
        <a href={path("/dashboard/")}>{t("ورود", "Sign in")}</a>
        <a href={path("/register/")}>{t("ثبت‌نام", "Sign up")}</a>
        <a
          href={
            lang === "en"
              ? "/backtest/methodology-en.md"
              : "/backtest/methodology-fa.md"
          }
        >
          {t("روش بک‌تست", "Backtest method")}
        </a>
      </nav>
    </footer>
  );
}
