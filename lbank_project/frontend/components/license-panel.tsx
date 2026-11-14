"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClient, errorText } from "@/lib/api";
import type { BillingSnapshot, Plans, Quote, Product } from "@/lib/types";
import { longDate, money, num } from "@/lib/format";
import { useLang } from "@/lib/lang";
import { Heading } from "./shared";
import PaymentPanel from "./payment-panel";
import { discountLabel, type Discount } from "@/lib/referral";

/** Discount lines under a price: invite discount, coupon and credit, each as a negative amount. */
function Discounts({
  items,
  listCents,
  usd,
}: {
  items?: Discount[];
  listCents?: number | null;
  usd: (v: number) => string;
}) {
  const { lang, t } = useLang();
  if (!items?.length || listCents == null) return null;
  return (
    <ul className="discount-lines" aria-label={t("تخفیف‌ها", "Discounts")}>
      <li>
        <span>{t("قیمت پلن", "Plan price")}</span>
        <s>{usd(listCents / 100)}</s>
      </li>
      {items.map((d) => (
        <li key={d.kind} className="discount">
          <span>{discountLabel(d, lang)}</span>
          <strong>
            {lang === "en"
              ? "−" + usd(d.cents / 100)
              : usd(d.cents / 100) + " کم"}
          </strong>
        </li>
      ))}
    </ul>
  );
}
interface Props {
  api: ApiClient;
  report: (e: unknown) => void;
  notify: (s: string) => void;
  onSnapshot: (s: BillingSnapshot) => void;
}
const orderLabels: Record<string, [string, string]> = {
  pending: ["در انتظار بررسی", "Awaiting review"],
  approved: ["تأیید و صادر شد", "Approved and issued"],
  cancelled: ["لغوشده", "Cancelled"],
  rejected: ["ردشده", "Rejected"],
};
export default function LicensePanel({
  api,
  report,
  notify,
  onSnapshot,
}: Props) {
  const { lang, t } = useLang();
  const usd = (value: number) => money(value, lang),
    faDate = (value: string | number) => longDate(value, lang),
    faNumber = (value: number) => num(value, lang);
  const [plans, setPlans] = useState<Plans | null>(null),
    [snapshot, setSnapshot] = useState<BillingSnapshot | null>(null);
  const [product, setProduct] = useState<Product>("autotrade");
  const [cap, setCap] = useState(10000),
    [months, setMonths] = useState(1),
    [quote, setQuote] = useState<Quote | null>(null);
  const [quoteError, setQuoteError] = useState(""),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false);
  const [checkout, setCheckout] = useState<
      (Quote & { requestKey: string }) | null
    >(null),
    [consent, setConsent] = useState(false),
    [checkoutError, setCheckoutError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null),
    mounted = useRef(false);
  const accept = useCallback(
    (p: Plans, s: BillingSnapshot) => {
      setPlans(p);
      setSnapshot(s);
      onSnapshot(s);
      const active =
        s.license.expires_at && Date.parse(s.license.expires_at) > Date.now();
      if (active) {
        setProduct(s.license.product || "autotrade");
        setCap(s.license.cap_usd!);
        setMonths(s.license.months!);
      }
    },
    [onSnapshot],
  );
  useEffect(() => {
    mounted.current = true;
    api
      .request<Plans>("/api/plans")
      .then(async (p) => {
        const s = await api.request<BillingSnapshot>("/api/me/license");
        if (mounted.current) accept(p, s);
      })
      .catch((e) => {
        if (mounted.current) report(e);
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });
    return () => {
      mounted.current = false;
    };
  }, [api, accept, report]);
  const refresh = async () => {
    const [p, s] = await Promise.all([
      api.request<Plans>("/api/plans"),
      api.request<BillingSnapshot>("/api/me/license"),
    ]);
    if (mounted.current) accept(p, s);
  };
  const p = snapshot?.license;
  const active = !!(p?.expires_at && Date.parse(p.expires_at) > Date.now());
  const kind = active ? "upgrade" : "subscription",
    pending = !!snapshot?.orders.some((o) => o.status === "pending");
  const selectedProduct = plans?.products.find(
    (item) => item.product === product,
  );
  const salesEnabled = selectedProduct?.sales_enabled === true;
  const productUpgrade =
    active &&
    p?.product === "signals" &&
    product === "autotrade" &&
    cap >= (p?.cap_usd || 0);
  const canQuote =
    salesEnabled &&
    !!snapshot &&
    !pending &&
    (!active ||
      (product === (p?.product || "autotrade") && cap > (p?.cap_usd || 0)) ||
      productUpgrade);
  useEffect(() => {
    let current = true;
    setQuote(null);
    setQuoteError("");
    if (canQuote)
      api
        .request<Quote>("/api/me/license/quote", "POST", {
          cap_usd: cap,
          months,
          kind,
          product,
        })
        .then((q) => {
          if (current) setQuote(q);
        })
        .catch((e) => {
          if (current) setQuoteError(errorText(e));
        });
    return () => {
      current = false;
    };
  }, [api, cap, months, kind, product, canQuote, snapshot]);
  useEffect(() => {
    if (checkout && !dialog.current?.open) dialog.current?.showModal();
    else if (!checkout && dialog.current?.open) dialog.current.close();
  }, [checkout]);
  const tier = selectedProduct?.tiers.find((t) => t.cap_usd === cap),
    fullPrice = (tier?.prices_cents[String(months)] || 0) / 100;
  const hasPrice = typeof tier?.prices_cents[String(months)] === "number";
  const saving =
    tier && tier.prices_cents["1"] && hasPrice
      ? Math.round(
          100 *
            (1 - fullPrice / (((tier.prices_cents["1"] || 0) / 100) * months)),
        )
      : 0;
  const currentQuote =
    quote?.cap_usd === cap &&
    quote.months === months &&
    quote.kind === kind &&
    quote.product === product
      ? quote
      : null;
  const purchaseNote = !salesEnabled
    ? t(
        "فروش این اشتراک تا تعیین و تأیید قیمت نهایی بسته است.",
        "This subscription is closed until final prices are set.",
      )
    : pending
      ? t(
          "یک درخواست در انتظار بررسی دارید؛ ابتدا آن را تکمیل یا لغو کنید.",
          "You have a request awaiting review; complete or cancel it first.",
        )
      : active && cap <= (p?.cap_usd || 0)
        ? t(
            "برای ارتقا، سقفی بالاتر از پلن فعلی انتخاب کنید. رشد سرمایه از سود در همین دوره نیازی به ارتقا ندارد.",
            "To upgrade, choose a higher cap than your current plan. Growth from profit during the period needs no upgrade.",
          )
        : quoteError ||
          (product === "signals"
            ? t(
                "فعال‌سازی سیگنال‌ها پس از تأیید پرداخت انجام می‌شود؛ اتصال صرافی لازم نیست.",
                "Signals are activated once payment is confirmed; no exchange connection needed.",
              )
            : t(
                "فعال‌سازی پس از تأیید پرداخت و سرمایهٔ حساب توسط پشتیبانی انجام می‌شود.",
                "Activation follows support's confirmation of payment and account capital.",
              ));
  const alert =
    p?.state === "grace"
      ? t(
          "واریز جدید از سقف پلن عبور کرده است. مهلت ارتقا تا ",
          "A new deposit took you over the plan cap. You can upgrade until ",
        ) +
        (p.grace_ends_at ? faDate(p.grace_ends_at) : "—") +
        t(
          " است؛ سپس فقط ورود جدید متوقف می‌شود.",
          "; after that only new entries stop.",
        )
      : p?.state === "capital_exceeded"
        ? t(
            "سقف سرمایه رد شده است؛ برای ادامهٔ ورود جدید، لایسنس ارتقایافته را نصب کنید. مدیریت معاملات باز ادامه دارد.",
            "The capital cap is exceeded; install an upgraded license to keep opening trades. Open trades are still managed.",
          )
        : p?.state === "expired"
          ? t(
              "اعتبار لایسنس تمام شده است؛ برای ورودهای جدید اشتراک را تمدید کنید.",
              "Your license has expired; renew to allow new entries.",
            )
          : "";
  async function openCheckout() {
    if (!currentQuote) return;
    setBusy(true);
    try {
      const q = await api.request<Quote>("/api/me/license/quote", "POST", {
        cap_usd: cap,
        months,
        kind,
        product,
      });
      setConsent(false);
      setCheckoutError("");
      setCheckout({ ...q, requestKey: crypto.randomUUID() });
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!checkout || !consent) return;
    setBusy(true);
    setCheckoutError("");
    try {
      const r = await api.request<{ id: string }>(
        "/api/me/license/orders",
        "POST",
        {
          cap_usd: checkout.cap_usd,
          months: checkout.months,
          kind: checkout.kind,
          product: checkout.product,
          request_key: checkout.requestKey,
          expected_price_cents: checkout.price_cents,
        },
      );
      setCheckout(null);
      await refresh();
      notify(
        t("درخواست شما ثبت شد. کد پیگیری: ", "Request submitted. Reference: ") +
          r.id.slice(0, 8) +
          t(" · در انتظار بررسی پشتیبانی", " · awaiting support review"),
      );
    } catch (e) {
      setCheckoutError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function cancel(id: string) {
    if (
      !window.confirm(
        t("درخواست بررسی لایسنس لغو شود؟", "Cancel this license request?"),
      )
    )
      return;
    setBusy(true);
    try {
      await api.request(
        "/api/me/license/orders/" + encodeURIComponent(id) + "/cancel",
        "POST",
      );
      await refresh();
      notify(t("درخواست لغو شد.", "Request cancelled."));
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section id="license-section" className="panel license-panel">
        <Heading
          eyebrow="A PLAN THAT GROWS WITH YOU"
          title={t(
            "لایسنس، متناسب با سرمایهٔ شما",
            "A license sized to your capital",
          )}
          description={t(
            "هر سه ربات در تمام پلن‌ها. سرمایهٔ حساب را انتخاب کنید و دورهٔ مناسب خود را بسازید.",
            "All three bots in every plan. Pick your account capital and the term that suits you.",
          )}
          number="01 / LICENSE"
        />
        <div
          id="license-alert"
          className="notice"
          role="status"
          hidden={!alert}
        >
          {alert}
        </div>
        <div className="license-detail">
          <span id="license-account">
            {p?.account_id
              ? t("حساب متصل به لایسنس: ", "Licensed account: ") + p.account_id
              : t(
                  "هنوز لایسنس فعالی ندارید.",
                  "You have no active license yet.",
                )}
          </span>
          {p?.license_id && (
            <a
              id="download-license"
              href="/api/me/license/download"
              className="text-link"
              download="trade-license.json"
            >
              {t("دانلود لایسنس امضاشده", "Download signed license")}
            </a>
          )}
          <button
            id="refresh-license"
            className="text-button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await refresh();
                notify(t("وضعیت لایسنس به‌روز شد.", "License status updated."));
              } catch (e) {
                report(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            {t("به‌روزرسانی وضعیت", "Refresh status")}
          </button>
        </div>
        <p className="note">
          {product === "signals"
            ? t(
                "اشتراک سیگنال پس از تأیید پرداخت در همین پنل فعال می‌شود؛ نیازی به کلید صرافی یا نصب فایل روی ربات ندارید.",
                "The signals subscription activates in this panel once payment is confirmed; no exchange key or bot file is needed.",
              )
            : t(
                "وضعیت این بخش مربوط به لایسنس صادرشده است؛ اعمال آن روی ربات پس از نصب فایل توسط مدیر انجام می‌شود. واریز و برداشت‌های مبنای لایسنس با بررسی پشتیبانی ثبت می‌شوند.",
                "This shows the issued license; it takes effect on the bot once the admin installs the file. Deposits and withdrawals for the license base are recorded after support review.",
              )}
        </p>
        <fieldset className="product-fieldset">
          <legend>
            {t("چه سرویسی می‌خواهید؟", "Which service do you want?")}
          </legend>
          <div className="product-options">
            <label
              className={
                product === "signals"
                  ? "product-option selected"
                  : "product-option"
              }
            >
              <input
                type="radio"
                name="product"
                value="signals"
                checked={product === "signals"}
                disabled={busy}
                onChange={() => setProduct("signals")}
              />
              <span className="eyebrow">SIGNALS</span>
              <strong>{t("فقط سیگنال", "Signals only")}</strong>
              <p>
                {t(
                  "سیگنال ورود، حد ضرر و هدف را در پنل ببینید؛ تصمیم و اجرای معامله با شماست.",
                  "See entry, stop-loss and target in your panel; the decision and the trade are yours.",
                )}
              </p>
              <span className="quiet-tag">
                {t(
                  "بدون کلید صرافی · بدون اجرای سفارش",
                  "No exchange key · no order execution",
                )}
              </span>
            </label>
            <label
              className={
                product === "autotrade"
                  ? "product-option selected"
                  : "product-option"
              }
            >
              <input
                type="radio"
                name="product"
                value="autotrade"
                checked={product === "autotrade"}
                disabled={busy}
                onChange={() => setProduct("autotrade")}
              />
              <span className="eyebrow">AUTOTRADE</span>
              <strong>{t("معاملهٔ خودکار", "Automated trading")}</strong>
              <p>
                {t(
                  "مجوز ورود و مدیریت معاملات با ربات، همراه با سیگنال‌ها.",
                  "A license for the bot to enter and manage trades, signals included.",
                )}
              </p>
              <span className="quiet-tag">
                {t(
                  "اجرای فعلی آزمایشی است؛ سفارش واقعی فعال نیست",
                  "Current execution is a trial; real orders are not active",
                )}
              </span>
            </label>
          </div>
        </fieldset>
        {!salesEnabled && (
          <div id="sales-closed" className="notice">
            {t(
              "قیمت نهایی این سرویس هنوز تأیید نشده است؛ امکان خرید و پرداخت بسته است.",
              "Final prices for this service are not confirmed yet; purchase and payment are closed.",
            )}
          </div>
        )}
        <div className="plan-builder">
          <div className="plan-controls">
            <label htmlFor="capital-tier">
              {t("سقف سرمایهٔ حساب", "Account capital cap")}{" "}
              <span className="field-hint">
                {t("دلار آمریکا", "US dollars")}
              </span>
            </label>
            <select
              id="capital-tier"
              value={cap}
              disabled={loading || busy}
              onChange={(e) => setCap(Number(e.target.value))}
              aria-describedby="tier-help"
            >
              {!selectedProduct ? (
                <option value={10000}>
                  {t("در حال دریافت تعرفه‌ها…", "Loading prices…")}
                </option>
              ) : (
                selectedProduct.tiers.map((x) => (
                  <option key={x.cap_usd} value={x.cap_usd}>
                    {t("تا ", "Up to ")}
                    {usd(x.cap_usd)}
                  </option>
                ))
              )}
            </select>
            <p id="tier-help" className="note">
              {t(
                "پلنی را انتخاب کنید که سرمایهٔ فعلی حسابتان را پوشش دهد.",
                "Choose a plan that covers your account's current capital.",
              )}
            </p>
            <fieldset className="term-fieldset">
              <legend>{t("مدت اشتراک", "Subscription term")}</legend>
              <div className="term-switch">
                {[
                  [1, t("یک‌ماهه", "1 month")],
                  [3, t("سه‌ماهه", "3 months")],
                  [6, t("شش‌ماهه", "6 months")],
                ].map(([n, label]) => (
                  <label key={n}>
                    <input
                      type="radio"
                      name="term"
                      value={n}
                      checked={months === n}
                      disabled={active || busy || loading}
                      onChange={() => setMonths(Number(n))}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <p id="term-help" className="note">
              {active
                ? t(
                    "ارتقا با حفظ تاریخ پایان و مدت پلن فعلی انجام می‌شود. تمدید پس از پایان اعتبار در دسترس است.",
                    "An upgrade keeps your current end date and term. Renewal is available after expiry.",
                  )
                : ""}
            </p>
            <div className="plan-inclusions">
              <span>
                ✓{" "}
                {t("شاهین، موج‌سوار و ققنوس", "Falcon, Wave Rider and Phoenix")}
              </span>
              <span>
                ✓ {t("به‌روزرسانی و پشتیبانی نصب", "Updates and setup support")}
              </span>
              <span>✓ {t("یک حساب اختصاصی", "One dedicated account")}</span>
              <span>
                ✓{" "}
                {product === "signals"
                  ? t(
                      "ورود، حد ضرر و اعتبار سیگنال",
                      "Entry, stop-loss and signal validity",
                    )
                  : t(
                      "مدیریت معاملات باز پس از انقضا",
                      "Open trades managed after expiry",
                    )}
              </span>
            </div>
          </div>
          <div className="price-card">
            <div className="price-card-top">
              <span>
                {product === "signals"
                  ? t("سیگنال هر سه ربات", "Signals from all three bots")
                  : t(
                      "معاملهٔ خودکار هر سه ربات",
                      "Automated trading, all three bots",
                    )}
              </span>
              <span className="price-badge">
                {active && canQuote
                  ? t("ارتقای پلن", "Plan upgrade")
                  : saving > 0
                    ? lang === "en"
                      ? `Save ${saving}%`
                      : faNumber(saving) + "٪ صرفه‌جویی"
                    : "USD"}
              </span>
            </div>
            <div className="price-line">
              <strong id="plan-price">
                {!hasPrice
                  ? t("تعیین نشده", "Not set")
                  : canQuote && !currentQuote
                    ? "…"
                    : faNumber(
                        (currentQuote?.price_cents ?? fullPrice * 100) / 100,
                      )}
              </strong>
              {hasPrice && <span>{t("دلار", "USD")}</span>}
            </div>
            <p id="monthly-equivalent">
              {!hasPrice
                ? t(
                    "پس از تأیید قیمت‌ها، فروش این سرویس باز می‌شود.",
                    "Sales open once prices are confirmed.",
                  )
                : active && currentQuote
                  ? t("مابه‌التفاوت تا ", "Prorated difference until ") +
                    faDate(currentQuote.expires_at) +
                    t(
                      " · پایان دوره تغییر نمی‌کند",
                      " · the end date stays the same",
                    )
                  : t("معادل ", "Equals ") +
                    usd(fullPrice / months) +
                    t(" در ماه · قیمت کل ", " per month · total for ") +
                    faNumber(months) +
                    t(" ماه", months === 1 ? " month" : " months")}
            </p>
            <Discounts
              items={currentQuote?.discounts}
              listCents={currentQuote?.list_price_cents}
              usd={usd}
            />
            <div className="price-divider" />
            <div className="price-meta">
              <span>{t("سقف سرمایه", "Capital cap")}</span>
              <strong>{usd(cap)}</strong>
            </div>
            <div className="price-meta">
              <span>{t("نوع درخواست", "Request type")}</span>
              <strong>
                {active
                  ? t("ارتقای پلن فعال", "Upgrade active plan")
                  : p?.state === "expired"
                    ? t("تمدید اشتراک", "Renew subscription")
                    : t("اشتراک جدید", "New subscription")}
              </strong>
            </div>
            <button
              id="request-license"
              className="full"
              disabled={!salesEnabled || !currentQuote || busy || pending}
              onClick={openCheckout}
            >
              {salesEnabled
                ? t("بررسی و ثبت درخواست", "Review and submit")
                : t("فروش فعلاً بسته است", "Sales are closed for now")}
            </button>
            <p className="price-note">{purchaseNote}</p>
          </div>
        </div>
        <div className="policy-strip">
          <div>
            <span className="policy-icon">✦</span>
            <h3>
              {t(
                "رشد از سود، بدون ارتقای اجباری",
                "Grow from profit, no forced upgrade",
              )}
            </h3>
            <p>
              {t(
                "سود ربات در طول دوره هزینهٔ اضافه ندارد؛ سرمایه در تمدید دوباره بررسی می‌شود.",
                "Profit made during the term costs nothing extra; capital is reviewed again at renewal.",
              )}
            </p>
          </div>
          <div>
            <span className="policy-icon">＋</span>
            <h3>
              {t(
                "واریز جدید، با مهلت ارتقا",
                "New deposits get an upgrade window",
              )}
            </h3>
            <p>
              {t(
                "اگر سرمایهٔ مبنا از سقف بیشتر شود، ۷۲ ساعت برای ارتقا دارید؛ سپس فقط ورود جدید متوقف می‌شود.",
                "If your base capital goes over the cap you have 72 hours to upgrade; after that only new entries stop.",
              )}
            </p>
          </div>
          <div>
            <span className="policy-icon">◷</span>
            <h3>{t("ارتقا با مابه‌التفاوت", "Upgrade for the difference")}</h3>
            <p>
              {t(
                "برای ارتقای پلن فعال، فقط مابه‌التفاوت متناسب با زمان باقی‌مانده محاسبه می‌شود.",
                "Upgrading an active plan costs only the difference for the time remaining.",
              )}
            </p>
          </div>
        </div>
        <details className="pricing-details">
          <summary>
            {t("مقایسهٔ کامل تعرفه‌ها", "Compare all prices")}{" "}
            <span aria-hidden="true">＋</span>
          </summary>
          <div className="table-wrap">
            <table className="pricing-table">
              <caption className="sr-only">
                {t(
                  "تعرفهٔ پکیج سه ربات، دلار آمریکا",
                  "Three-bot package prices, USD",
                )}
              </caption>
              <thead>
                <tr>
                  <th>{t("سقف سرمایه", "Capital cap")}</th>
                  <th>{t("یک‌ماهه", "1 month")}</th>
                  <th>{t("سه‌ماهه", "3 months")}</th>
                  <th>{t("شش‌ماهه", "6 months")}</th>
                </tr>
              </thead>
              <tbody id="pricing-rows">
                {selectedProduct?.tiers.map((x) => (
                  <tr key={x.cap_usd}>
                    <td>{usd(x.cap_usd)}</td>
                    {["1", "3", "6"].map((m) => (
                      <td key={m}>
                        {x.prices_cents[m] === null
                          ? t("تعیین نشده", "Not set")
                          : usd((x.prices_cents[m] || 0) / 100)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>
      <section className="panel" id="orders-section">
        <Heading
          eyebrow="SUBSCRIPTION HISTORY"
          title={t("درخواست‌های اشتراک", "Subscription requests")}
          number="02 / ORDERS"
        />
        {snapshot?.orders
          .filter((o) => o.status === "pending")
          .slice(0, 1)
          .map((o) =>
            o.price_cents === 0 ? (
              <p key={o.id} className="payment-panel note" role="status">
                {t(
                  "این سفارش کامل با اعتبار شما پرداخت شده و پرداخت دیگری لازم نیست؛ پس از بررسی پشتیبانی فعال می‌شود.",
                  "This order is fully paid with your credit; no payment is needed. It activates after review.",
                )}
              </p>
            ) : (
              <PaymentPanel
                key={o.id}
                api={api}
                orderId={o.id}
                onPaid={() => {
                  notify(t("پرداخت تأیید شد.", "Payment confirmed."));
                  void refresh().catch(report);
                }}
              />
            ),
          )}
        {!snapshot?.orders.length ? (
          <p className="empty-state">
            {t(
              "هنوز درخواستی ثبت نکرده‌اید. پلن مناسب خود را از بخش بالا انتخاب کنید.",
              "You have no requests yet. Choose a plan in the section above.",
            )}
          </p>
        ) : null}
        <div className="table-wrap">
          <table hidden={!snapshot?.orders.length}>
            <thead>
              <tr>
                {[
                  t("کد پیگیری", "Reference"),
                  t("پلن / دوره", "Plan / term"),
                  t("مبلغ", "Amount"),
                  t("تاریخ ثبت", "Submitted"),
                  t("وضعیت", "Status"),
                  t("عملیات", "Actions"),
                ].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody id="order-rows">
              {snapshot?.orders.map((o) => (
                <tr key={o.id}>
                  <td>
                    <bdi>{o.id.slice(0, 8)}</bdi>
                  </td>
                  <td>
                    {o.product === "signals"
                      ? t("سیگنال", "Signals")
                      : t("معاملهٔ خودکار", "Automated trading")}{" "}
                    · {usd(o.cap_usd)} / {faNumber(o.months)}{" "}
                    {t("ماه", o.months === 1 ? "month" : "months")}
                  </td>
                  <td>
                    {o.list_price_cents != null &&
                      o.list_price_cents !== o.price_cents && (
                        <>
                          <s className="muted">
                            {usd(o.list_price_cents / 100)}
                          </s>{" "}
                        </>
                      )}
                    {usd(o.price_cents / 100)}
                  </td>
                  <td>{faDate(o.created * 1000)}</td>
                  <td>
                    <span className={"order-status " + o.status}>
                      {orderLabels[o.status]?.[lang === "en" ? 1 : 0] ||
                        o.status}
                    </span>
                  </td>
                  <td>
                    {o.status === "pending" ? (
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() => cancel(o.id)}
                        aria-label={
                          t("لغو درخواست ", "Cancel request ") +
                          o.id.slice(0, 8)
                        }
                      >
                        {t("لغو درخواست", "Cancel request")}
                      </button>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="note">
          {t(
            "برای درخواست در انتظار، روش پرداخت را انتخاب کنید. سیگنال پس از تأیید پرداخت فعال می‌شود؛ معاملهٔ خودکار پس از بررسی حساب صرافی.",
            "For a pending request, choose a payment method. Signals activate once payment is confirmed; automated trading after the exchange account is checked.",
          )}
        </p>
      </section>
      <dialog
        id="checkout-dialog"
        ref={dialog}
        aria-labelledby="checkout-title"
        onCancel={(e) => {
          if (busy) e.preventDefault();
          else setCheckout(null);
        }}
      >
        <div className="dialog-body">
          <span className="eyebrow">ONE LAST LOOK</span>
          <h2 id="checkout-title">
            {t("مرور درخواست لایسنس", "Review your license request")}
          </h2>
          <p>
            {checkout &&
              (checkout.product === "signals"
                ? t("فقط سیگنال، سقف ", "Signals only, cap ")
                : t("معاملهٔ خودکار، سقف ", "Automated trading, cap ")) +
                usd(checkout.cap_usd) +
                t("، ", ", ") +
                faNumber(checkout.months) +
                t(" ماه", checkout.months === 1 ? " month" : " months") +
                (checkout.kind === "upgrade"
                  ? t(" · پایان اعتبار ", " · valid until ") +
                    faDate(checkout.expires_at)
                  : t(
                      " · شروع دوره پس از تأیید پشتیبانی",
                      " · term starts after support approval",
                    ))}
          </p>
          <Discounts
            items={checkout?.discounts}
            listCents={checkout?.list_price_cents}
            usd={usd}
          />
          <div className="checkout-total">
            <span>{t("مبلغ قابل پرداخت", "Amount to pay")}</span>
            <strong>{checkout ? usd(checkout.price_cents / 100) : ""}</strong>
          </div>
          {checkout?.price_cents === 0 && (
            <p className="note">
              {t(
                "اعتبار شما کل مبلغ را پوشش می‌دهد و پرداختی لازم نیست.",
                "Your credit covers the full amount; no payment is needed.",
              )}
            </p>
          )}
          <p className="note">
            {t(
              "بعد از ثبت درخواست، مبلغ را با USDT یا USDC مستقیم به کیف پول آوینا پرداخت می‌کنید و پرداخت خودکار روی شبکه تأیید می‌شود. برای معاملهٔ خودکار، شناسه و سرمایهٔ حساب صرافی هم بررسی می‌شود.",
              "After submitting, you pay in USDT or USDC straight to Avina's wallet and the payment is confirmed on-chain automatically. For automated trading, the exchange account ID and capital are also verified.",
            )}
          </p>
          <label className="consent">
            <input
              id="checkout-consent"
              type="checkbox"
              checked={consent}
              disabled={busy}
              onChange={(e) => setConsent(e.target.checked)}
            />
            {t(
              "تعرفه، مدت و شرایط لایسنس یک حساب را خوانده‌ام.",
              "I have read the price, term and single-account license terms.",
            )}
          </label>
          <p id="checkout-error" role="alert">
            {checkoutError}
          </p>
          <div className="dialog-actions">
            <button
              id="confirm-order"
              disabled={!consent || busy}
              onClick={confirm}
            >
              {t("ثبت درخواست", "Submit request")}
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => setCheckout(null)}
            >
              {t("بازگشت", "Back")}
            </button>
          </div>
        </div>
      </dialog>
    </>
  );
}
