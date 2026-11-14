"use client";
import ThemeSwitcher from "./theme-switcher";
import { useCallback, useEffect, useState } from "react";
import { ApiClient, ApiError, SessionChanged, errorText } from "@/lib/api";
import type { BillingSnapshot, Me } from "@/lib/types";
import { licenseLabel, longDate, money } from "@/lib/format";
import { otherPath, type Lang } from "@/lib/i18n";
import { LangProvider, useLang } from "@/lib/lang";
import { BrandLogo } from "./shared";
import LicensePanel from "./license-panel";
import AccountPanel from "./account-panel";
import ProfilePanel from "./profile-panel";
import Robots from "./robots";
import Pwa from "./pwa";
import Signals from "./signals";
import AdminWorkbench from "./admin-workbench";

type Mode = "login" | "register" | "admin";

export default function Portal({
  initialMode = "login",
  lang = "fa",
}: {
  initialMode?: Mode;
  lang?: Lang;
}) {
  return (
    <LangProvider lang={lang}>
      <PortalBody initialMode={initialMode} />
    </LangProvider>
  );
}

function PortalBody({ initialMode }: { initialMode: Mode }) {
  const { lang, t, path } = useLang();
  const registering = initialMode === "register";
  const adminMode = initialMode === "admin";
  const here = registering
    ? "/register/"
    : adminMode
      ? "/admin/"
      : "/dashboard/";
  const [api] = useState(() => new ApiClient());
  const [user, setUser] = useState<Me | null>(null),
    [ready, setReady] = useState(false),
    [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false),
    [billing, setBilling] = useState<BillingSnapshot | null>(null);
  const report = useCallback((error: unknown) => {
    if (!(error instanceof SessionChanged)) setMessage(errorText(error));
  }, []);
  useEffect(() => {
    let mounted = true;
    api.onUnauthorized = () => {
      setUser(null);
      setBilling(null);
    };
    api
      .request<Me>("/api/me")
      .then((me) => {
        if (mounted) {
          api.csrf = me.csrf;
          setUser(me);
        }
      })
      .catch((error) => {
        if (!(error instanceof ApiError && error.status === 401) && mounted)
          report(error);
      })
      .finally(() => {
        if (mounted) setReady(true);
      });
    return () => {
      mounted = false;
      api.onUnauthorized = undefined;
      api.invalidate();
    };
  }, [api, report]);
  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const form = event.currentTarget,
      data = new FormData(form);
    if (
      registering &&
      data.get("password") !== data.get("password_confirmation")
    ) {
      setMessage(
        t("رمز عبور و تکرار آن یکسان نیستند.", "The passwords do not match."),
      );
      setBusy(false);
      return;
    }
    try {
      await api.request(registering ? "/api/register" : "/api/login", "POST", {
        username: data.get("username"),
        password: data.get("password"),
        ...(registering
          ? {
              password_confirmation: data.get("password_confirmation"),
              email: data.get("email"),
            }
          : {}),
      });
      form.reset();
      const me = await api.request<Me>("/api/me");
      api.csrf = me.csrf;
      if (registering) {
        window.location.assign(path("/dashboard/"));
        return;
      }
      setUser(me);
    } catch (error) {
      if (registering && error instanceof ApiError && error.status === 409)
        setMessage(
          t(
            "این نام کاربری یا ایمیل قبلاً استفاده شده است؛ مورد دیگری انتخاب کنید.",
            "That username or email is already in use; choose another.",
          ),
        );
      else if (registering && error instanceof ApiError && error.status === 422)
        setMessage(
          t(
            "اطلاعات را بررسی کنید: نام کاربری انگلیسی، ایمیل معتبر و رمز حداقل ۱۲ کاراکتر.",
            "Check the details: a lowercase username, a valid email and a password of at least 12 characters.",
          ),
        );
      else report(error);
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    setBusy(true);
    try {
      await api.request("/api/logout", "POST");
      api.invalidate();
      setUser(null);
      setBilling(null);
      setMessage(t("از حساب خارج شدید.", "You are signed out."));
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  const p = billing?.license;
  return (
    <>
      <a className="skip-link" href="#main">
        {t("رفتن به محتوا", "Skip to content")}
      </a>
      <header className="topbar">
        <BrandLogo compact />
        <div className="topbar-meta">
          <span className="system-dot" aria-hidden="true" />
          <span>
            {t("فضای اختصاصی معامله‌گر", "Your private trading space")}
          </span>
        </div>
        <div className="topbar-actions">
          <a
            className="language-link"
            href={otherPath(lang, here)}
            hrefLang={lang === "fa" ? "en" : "fa"}
            lang={lang === "fa" ? "en" : "fa"}
          >
            {lang === "fa" ? "English" : "فارسی"}
          </a>
          <ThemeSwitcher />
          <Pwa notify={setMessage} />
          {user?.role === "admin" && !adminMode && (
            <a id="admin-link" className="text-link" href={path("/admin/")}>
              {t("کارتابل مدیریت", "Admin")}
            </a>
          )}
          {user && (
            <button
              id="logout"
              className="secondary small"
              disabled={busy}
              onClick={logout}
            >
              {t("خروج از حساب", "Sign out")}
            </button>
          )}
        </div>
      </header>
      <main id="main">
        <p id="message" role="status" aria-live="polite">
          {message}
        </p>
        {!user ? (
          <section id="login-panel" className="login-layout">
            <div className="login-story">
              <span className="eyebrow">THREE ENGINES. ONE SPACE.</span>
              <h1>
                {t("سه ربات.", "Three bots.")}
                <br />
                {t("یک حساب.", "One account.")}
                <br />
                <em>{t("کنترل در دست شما.", "You stay in control.")}</em>
              </h1>
              <p>
                {t(
                  "وضعیت حساب، سیگنال‌ها و اشتراک خود را در یک فضای ساده دنبال کنید.",
                  "Follow your account, signals and subscription in one simple space.",
                )}
              </p>
              <div className="strategy-tags">
                <span>{t("شاهین", "Falcon")}</span>
                <span>{t("موج‌سوار", "Wave Rider")}</span>
                <span>{t("ققنوس", "Phoenix")}</span>
              </div>
              <div className="orbit-art" aria-hidden="true">
                <div className="orbit o1" />
                <div className="orbit o2" />
                <div className="orbit o3" />
                <span className="orbit-center">
                  A<span>/</span>
                </span>
                <span className="orbit-node n1">S</span>
                <span className="orbit-node n2">M</span>
                <span className="orbit-node n3">G</span>
              </div>
            </div>
            <div className="login-card">
              <span className="eyebrow">{t("خوش آمدید", "Welcome")}</span>
              <h2>
                {registering
                  ? t("ساخت حساب کاربری", "Create your account")
                  : t("ورود به حساب کاربری", "Sign in to your account")}
              </h2>
              <p>
                {registering
                  ? t(
                      "ثبت‌نام کنید؛ نوع اشتراک را بعد از ورود انتخاب می‌کنید.",
                      "Sign up now; you choose a subscription after signing in.",
                    )
                  : t(
                      "برای دیدن سیگنال‌ها و مدیریت اشتراک وارد شوید.",
                      "Sign in to see signals and manage your subscription.",
                    )}
              </p>
              <form
                id={registering ? "register-form" : "login-form"}
                onSubmit={login}
              >
                <label htmlFor="username">{t("نام کاربری", "Username")}</label>
                <input
                  id="username"
                  name="username"
                  dir="ltr"
                  autoComplete="username"
                  pattern="[a-z](?:[a-z0-9]|-)+"
                  aria-describedby="username-help"
                  minLength={2}
                  maxLength={40}
                  placeholder="username"
                  required
                />
                <p id="username-help" className="note">
                  {t(
                    "نام کاربری انگلیسی با حروف کوچک، عدد و خط تیره؛ حداقل دو کاراکتر.",
                    "Lowercase letters, numbers and dashes; at least two characters.",
                  )}
                </p>
                {registering && (
                  <>
                    <label htmlFor="email">{t("ایمیل", "Email")}</label>
                    <input
                      id="email"
                      name="email"
                      type="email"
                      dir="ltr"
                      autoComplete="email"
                      maxLength={254}
                      placeholder="you@example.com"
                      required
                    />
                  </>
                )}
                <label htmlFor="password">{t("رمز عبور", "Password")}</label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  dir="ltr"
                  autoComplete={
                    registering ? "new-password" : "current-password"
                  }
                  minLength={12}
                  maxLength={128}
                  placeholder="••••••••••••"
                  required
                />
                {registering && (
                  <>
                    <label htmlFor="password-confirmation">
                      {t("تکرار رمز عبور", "Confirm password")}
                    </label>
                    <input
                      id="password-confirmation"
                      name="password_confirmation"
                      type="password"
                      dir="ltr"
                      autoComplete="new-password"
                      minLength={12}
                      maxLength={128}
                      required
                    />
                    <p className="note">
                      {t(
                        "رمز عبور حداقل ۱۲ کاراکتر باشد. ثبت‌نام به معنی خرید یا شروع معامله نیست.",
                        "Use at least 12 characters. Signing up does not buy anything or start trading.",
                      )}
                    </p>
                  </>
                )}
                <button
                  type="submit"
                  className="full"
                  disabled={!ready || busy}
                >
                  {!ready
                    ? t("در حال بررسی نشست…", "Checking session…")
                    : busy
                      ? t("در حال ورود…", "Signing in…")
                      : registering
                        ? t("ساخت حساب", "Create account")
                        : t("ورود به پنل", "Sign in")}
                </button>
              </form>
              <p className="note login-foot">
                {registering
                  ? t("از قبل حساب دارید؟ ", "Already have an account? ")
                  : t("هنوز حساب ندارید؟ ", "No account yet? ")}
                <a
                  className="text-link"
                  href={path(registering ? "/dashboard/" : "/register/")}
                >
                  {registering
                    ? t("ورود به حساب", "Sign in")
                    : t("ساخت حساب رایگان", "Create a free account")}
                </a>
              </p>
            </div>
          </section>
        ) : adminMode ? (
          user.role === "admin" ? (
            <AdminWorkbench api={api} report={report} />
          ) : (
            <section id="admin-forbidden" className="panel">
              <h1>
                {t("دسترسی مدیریتی ندارید", "You do not have admin access")}
              </h1>
              <p>
                {t(
                  "این بخش فقط برای مدیر سامانه است.",
                  "This area is for the site administrator only.",
                )}
              </p>
              <a className="button" href={path("/dashboard/")}>
                {t("بازگشت به پنل خودم", "Back to my panel")}
              </a>
            </section>
          )
        ) : (
          <div id="account-panel" key={user.username}>
            <nav
              className="section-nav"
              aria-label={t("بخش‌های پنل", "Panel sections")}
            >
              {[
                ["overview", t("نمای کلی", "Overview")],
                ["profile-section", t("اطلاعات کاربری", "Profile")],
                [
                  "license-section",
                  t("لایسنس و تعرفه‌ها", "License and pricing"),
                ],
                ["signals-section", t("سیگنال‌ها", "Signals")],
                ...(p?.product !== "signals"
                  ? [
                      [
                        "connection-section",
                        t("حساب صرافی", "Exchange account"),
                      ],
                    ]
                  : []),
                ...(p?.product !== "signals"
                  ? [["robot-section", t("ربات‌ها", "Bots")]]
                  : []),
              ].map(([id, label]) => (
                <a key={id} href={"#" + id} className="nav-link">
                  {label}
                </a>
              ))}
            </nav>
            <section id="overview" className="dashboard-hero">
              <div>
                <span className="eyebrow">YOUR TRADING WORKSPACE</span>
                <h1 id="welcome">
                  {t("حساب ", "Account ")}
                  <bdi>{user.username}</bdi>
                </h1>
                <p>
                  {t(
                    "فضایی برای مدیریت حساب، ربات‌ها و مسیر پیش رو.",
                    "A place to manage your account, your bots and what comes next.",
                  )}
                </p>
                <div className="hero-badges">
                  <span className="pill">
                    {p?.product === "signals"
                      ? t("اشتراک فقط سیگنال", "Signals-only subscription")
                      : t("اجرای ربات: آزمایشی", "Bot execution: trial")}
                  </span>
                  <span className="quiet-tag">
                    {t(
                      "سه استراتژی در یک پکیج",
                      "Three strategies, one package",
                    )}
                  </span>
                </div>
              </div>
              <div className="hero-art" aria-hidden="true">
                <div className="mini-ring" />
                <small>AVINA · S / M / G</small>
              </div>
            </section>
            <div className="stat-grid">
              <article className="stat-card">
                <div className="stat-label">
                  {t("وضعیت لایسنس", "License status")} <span>01</span>
                </div>
                <strong id="license-state">
                  {p
                    ? licenseLabel(p.state, lang) || t("نامشخص", "Unknown")
                    : t("در حال دریافت…", "Loading…")}
                </strong>
                <p id="license-expiry">
                  {p?.expires_at
                    ? t("پایان اعتبار: ", "Valid until: ") +
                      longDate(p.expires_at, lang)
                    : t("با انتخاب پلن شروع کنید", "Start by choosing a plan")}
                </p>
              </article>
              <article className="stat-card">
                <div className="stat-label">
                  {t("سقف سرمایهٔ پلن", "Plan capital cap")} <span>02</span>
                </div>
                <strong id="license-cap">
                  {p?.cap_usd ? money(p.cap_usd, lang) : "—"}
                </strong>
                <p>
                  {t(
                    "برای یک حساب · هر سه ربات",
                    "One account · all three bots",
                  )}
                </p>
              </article>
              <article className="stat-card">
                <div className="stat-label">
                  {p?.product === "signals"
                    ? t("بازهٔ سرمایهٔ انتخابی", "Chosen capital range")
                    : t("سرمایهٔ مبنای لایسنس", "License base capital")}{" "}
                  <span>03</span>
                </div>
                <strong id="license-funded">
                  {p?.funded_capital_usd !== undefined
                    ? money(Number(p.funded_capital_usd), lang)
                    : "—"}
                </strong>
                <p>
                  {p?.product === "signals"
                    ? t(
                        "سرمایهٔ هدف انتخابی شما؛ بدون اتصال به صرافی",
                        "Your chosen target capital; no exchange connection",
                      )
                    : t(
                        "سرمایهٔ تأییدشده و خالص واریزها؛ بدون سود دوره",
                        "Verified capital and net deposits; excluding period profit",
                      )}
                </p>
              </article>
            </div>
            <ProfilePanel
              api={api}
              email={user.email ?? null}
              onEmail={(email) => setUser((u) => (u ? { ...u, email } : u))}
              notify={setMessage}
              report={report}
            />
            <LicensePanel
              api={api}
              report={report}
              notify={setMessage}
              onSnapshot={setBilling}
            />
            <Signals api={api} entitlement={p} report={report} />
            {p?.product !== "signals" && (
              <AccountPanel api={api} report={report} notify={setMessage} />
            )}
            {p?.product !== "signals" && <Robots api={api} report={report} />}
            <div className="bottom-note">
              <span className="brand">AVINA</span>
              <p>
                {t(
                  "معامله‌گری با ریسک همراه است. هیچ بازدهی تضمین نمی‌شود.",
                  "Trading involves risk. No return is guaranteed.",
                )}
              </p>
            </div>
          </div>
        )}
      </main>
      <footer>
        <span>AVINA by ARTAX ©</span>
        <span>
          {t("شاهین · موج‌سوار · ققنوس", "Falcon · Wave Rider · Phoenix")}
        </span>
        <span>
          {t("طراحی‌شده برای وب و موبایل", "Built for web and mobile")}
        </span>
      </footer>
    </>
  );
}
