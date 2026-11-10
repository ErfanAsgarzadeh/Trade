"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiClient, ApiError, SessionChanged, errorText } from "@/lib/api";
import type { BillingSnapshot, Me } from "@/lib/types";
import { licenseLabels, usd, faDate } from "@/lib/format";
import { Arrow } from "./shared";
import LicensePanel from "./license-panel";
import AccountPanel from "./account-panel";
import Robots from "./robots";
import Pwa from "./pwa";
import Signals from "./signals";
import AdminWorkbench from "./admin-workbench";

export default function Portal({
  initialMode = "login",
}: {
  initialMode?: "login" | "register" | "admin";
}) {
  const registering = initialMode === "register";
  const adminMode = initialMode === "admin";
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
      setMessage("رمز عبور و تکرار آن یکسان نیستند.");
      setBusy(false);
      return;
    }
    try {
      await api.request(registering ? "/api/register" : "/api/login", "POST", {
        username: data.get("username"),
        password: data.get("password"),
        ...(registering
          ? { password_confirmation: data.get("password_confirmation") }
          : {}),
      });
      form.reset();
      const me = await api.request<Me>("/api/me");
      api.csrf = me.csrf;
      if (registering) {
        window.location.assign("/");
        return;
      }
      setUser(me);
    } catch (error) {
      if (registering && error instanceof ApiError && error.status === 409)
        setMessage("این نام کاربری قابل استفاده نیست؛ نام دیگری انتخاب کنید.");
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
      setMessage("از حساب خارج شدید.");
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
        رفتن به محتوا
      </a>
      <header className="topbar">
        <a className="logo" href="/" aria-label="Trade، صفحه اصلی">
          <span className="logo-mark" aria-hidden="true">
            T
          </span>
          <span className="brand">
            TRADE<span className="brand-dot">/</span>
          </span>
        </a>
        <div className="topbar-meta">
          <span className="system-dot" aria-hidden="true" />
          <span>فضای اختصاصی معامله‌گر</span>
        </div>
        <div className="topbar-actions">
          <Pwa notify={setMessage} />
          {user?.role === "admin" && !adminMode && (
            <a id="admin-link" className="text-link" href="/admin/">
              کارتابل مدیریت
            </a>
          )}
          {user && (
            <button
              id="logout"
              className="secondary small"
              disabled={busy}
              onClick={logout}
            >
              خروج از حساب
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
              <span className="eyebrow">THREE STRATEGIES. ONE SPACE.</span>
              <h1>
                سه ربات.
                <br />
                یک حساب.
                <br />
                <em>کنترل در دست شما.</em>
              </h1>
              <p>
                شاهین، موج‌سوار و ققنوس؛ وضعیت حساب و اشتراک خود را در یک فضای
                ساده دنبال کنید.
              </p>
              <div className="strategy-tags">
                <span>
                  <Arrow /> شاهین
                </span>
                <span>≈ موج‌سوار</span>
                <span>✦ ققنوس</span>
              </div>
              <div className="orbit-art" aria-hidden="true">
                <div className="orbit o1" />
                <div className="orbit o2" />
                <div className="orbit o3" />
                <span className="orbit-center">
                  T<span>/</span>
                </span>
                <span className="orbit-node n1">
                  <Arrow />
                </span>
                <span className="orbit-node n2">≈</span>
                <span className="orbit-node n3">✦</span>
              </div>
            </div>
            <div className="login-card">
              <span className="eyebrow">خوش آمدید</span>
              <h2>
                {registering ? "ساخت حساب کاربری" : "ورود به حساب کاربری"}
              </h2>
              <p>
                {registering
                  ? "ثبت‌نام کنید؛ نوع اشتراک را بعد از ورود انتخاب می‌کنید."
                  : "برای دیدن سیگنال‌ها و مدیریت اشتراک وارد شوید."}
              </p>
              <form
                id={registering ? "register-form" : "login-form"}
                onSubmit={login}
              >
                <label htmlFor="username">نام کاربری</label>
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
                  نام کاربری انگلیسی با حروف کوچک، عدد و خط تیره؛ حداقل دو
                  کاراکتر.
                </p>
                <label htmlFor="password">رمز عبور</label>
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
                      تکرار رمز عبور
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
                      رمز عبور حداقل ۱۲ کاراکتر باشد. ثبت‌نام به معنی خرید یا
                      شروع معامله نیست.
                    </p>
                  </>
                )}
                <button
                  type="submit"
                  className="full"
                  disabled={!ready || busy}
                >
                  {!ready
                    ? "در حال بررسی نشست…"
                    : busy
                      ? "در حال ورود…"
                      : registering
                        ? "ساخت حساب"
                        : "ورود به پنل"}{" "}
                  <span aria-hidden="true">←</span>
                </button>
              </form>
              <p className="note login-foot">
                {registering ? "از قبل حساب دارید؟ " : "هنوز حساب ندارید؟ "}
                <a
                  className="text-link"
                  href={registering ? "/" : "/register/"}
                >
                  {registering ? "ورود به حساب" : "ساخت حساب رایگان"}
                </a>
              </p>
            </div>
          </section>
        ) : adminMode ? (
          user.role === "admin" ? (
            <AdminWorkbench api={api} report={report} />
          ) : (
            <section id="admin-forbidden" className="panel">
              <h1>دسترسی مدیریتی ندارید</h1>
              <p>این بخش فقط برای مدیر سامانه است.</p>
              <a className="button" href="/">
                بازگشت به پنل خودم
              </a>
            </section>
          )
        ) : (
          <div id="account-panel" key={user.username}>
            <nav className="section-nav" aria-label="بخش‌های پنل">
              {[
                ["overview", "نمای کلی"],
                ["license-section", "لایسنس و تعرفه‌ها"],
                ["signals-section", "سیگنال‌ها"],
                ...(p?.product !== "signals"
                  ? [["connection-section", "حساب صرافی"]]
                  : []),
                ...(p?.product !== "signals"
                  ? [["robot-section", "ربات‌ها"]]
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
                  حساب <bdi>{user.username}</bdi>
                </h1>
                <p>فضایی برای مدیریت حساب، ربات‌ها و مسیر پیش رو.</p>
                <div className="hero-badges">
                  <span className="pill">
                    {p?.product === "signals"
                      ? "اشتراک فقط سیگنال"
                      : "اجرای ربات: آزمایشی"}
                  </span>
                  <span className="quiet-tag">سه استراتژی در یک پکیج</span>
                </div>
              </div>
              <div className="hero-art" aria-hidden="true">
                <div className="mini-ring" />
                <Arrow />
                <small>SHAHIN / MOJSAVAR / GHOGHNOUS</small>
              </div>
            </section>
            <div className="stat-grid">
              <article className="stat-card">
                <div className="stat-label">
                  وضعیت لایسنس <span>01</span>
                </div>
                <strong id="license-state">
                  {p ? licenseLabels[p.state] || "نامشخص" : "در حال دریافت…"}
                </strong>
                <p id="license-expiry">
                  {p?.expires_at
                    ? "پایان اعتبار: " + faDate(p.expires_at)
                    : "با انتخاب پلن شروع کنید"}
                </p>
              </article>
              <article className="stat-card">
                <div className="stat-label">
                  سقف سرمایهٔ پلن <span>02</span>
                </div>
                <strong id="license-cap">
                  {p?.cap_usd ? usd(p.cap_usd) : "—"}
                </strong>
                <p>برای یک حساب · هر سه ربات</p>
              </article>
              <article className="stat-card">
                <div className="stat-label">
                  {p?.product === "signals"
                    ? "بازهٔ سرمایهٔ انتخابی"
                    : "سرمایهٔ مبنای لایسنس"}{" "}
                  <span>03</span>
                </div>
                <strong id="license-funded">
                  {p?.funded_capital_usd !== undefined
                    ? usd(Number(p.funded_capital_usd))
                    : "—"}
                </strong>
                <p>
                  {p?.product === "signals"
                    ? "سرمایهٔ هدف انتخابی شما؛ بدون اتصال به صرافی"
                    : "سرمایهٔ تأییدشده و خالص واریزها؛ بدون سود دوره"}
                </p>
              </article>
            </div>
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
              <span className="brand">TRADE /</span>
              <p>معامله‌گری با ریسک همراه است. هیچ بازدهی تضمین نمی‌شود.</p>
            </div>
          </div>
        )}
      </main>
      <footer>
        <span>TRADE ©</span>
        <span>شاهین · موج‌سوار · ققنوس</span>
        <span>طراحی‌شده برای وب و موبایل</span>
      </footer>
    </>
  );
}
