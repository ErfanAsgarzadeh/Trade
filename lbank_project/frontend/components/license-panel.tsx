"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClient, errorText } from "@/lib/api";
import type { BillingSnapshot, Plans, Quote } from "@/lib/types";
import { faDate, faNumber, usd } from "@/lib/format";
import { Arrow, Heading } from "./shared";
interface Props {
  api: ApiClient;
  report: (e: unknown) => void;
  notify: (s: string) => void;
  onSnapshot: (s: BillingSnapshot) => void;
}
const orderLabels: Record<string, string> = {
  pending: "در انتظار بررسی",
  approved: "تأیید و صادر شد",
  cancelled: "لغوشده",
};
export default function LicensePanel({
  api,
  report,
  notify,
  onSnapshot,
}: Props) {
  const [plans, setPlans] = useState<Plans | null>(null),
    [snapshot, setSnapshot] = useState<BillingSnapshot | null>(null);
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
  const canQuote =
    !!snapshot && !pending && (!active || cap > (p?.cap_usd || 0));
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
  }, [api, cap, months, kind, canQuote, snapshot]);
  useEffect(() => {
    if (checkout && !dialog.current?.open) dialog.current?.showModal();
    else if (!checkout && dialog.current?.open) dialog.current.close();
  }, [checkout]);
  const tier = plans?.tiers.find((t) => t.cap_usd === cap),
    fullPrice = (tier?.prices_cents[String(months)] || 0) / 100;
  const saving = tier
    ? Math.round(
        100 * (1 - fullPrice / ((tier.prices_cents["1"] / 100) * months)),
      )
    : 0;
  const currentQuote =
    quote?.cap_usd === cap && quote.months === months && quote.kind === kind
      ? quote
      : null;
  const purchaseNote = pending
    ? "یک درخواست در انتظار بررسی دارید؛ ابتدا آن را تکمیل یا لغو کنید."
    : active && cap <= (p?.cap_usd || 0)
      ? "برای ارتقا، سقفی بالاتر از پلن فعلی انتخاب کنید. رشد سرمایه از سود در همین دوره نیازی به ارتقا ندارد."
      : quoteError ||
        "فعال‌سازی پس از تأیید پرداخت و سرمایهٔ حساب توسط پشتیبانی انجام می‌شود.";
  const alert =
    p?.state === "grace"
      ? "واریز جدید از سقف پلن عبور کرده است. مهلت ارتقا تا " +
        (p.grace_ends_at ? faDate(p.grace_ends_at) : "—") +
        " است؛ سپس فقط ورود جدید متوقف می‌شود."
      : p?.state === "capital_exceeded"
        ? "سقف سرمایه رد شده است؛ برای ادامهٔ ورود جدید، لایسنس ارتقایافته را نصب کنید. مدیریت معاملات باز ادامه دارد."
        : p?.state === "expired"
          ? "اعتبار لایسنس تمام شده است؛ برای ورودهای جدید اشتراک را تمدید کنید."
          : "";
  async function openCheckout() {
    if (!currentQuote) return;
    setBusy(true);
    try {
      const q = await api.request<Quote>("/api/me/license/quote", "POST", {
        cap_usd: cap,
        months,
        kind,
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
          request_key: checkout.requestKey,
          expected_price_cents: checkout.price_cents,
        },
      );
      setCheckout(null);
      await refresh();
      notify(
        "درخواست شما ثبت شد. کد پیگیری: " +
          r.id.slice(0, 8) +
          " · در انتظار بررسی پشتیبانی",
      );
    } catch (e) {
      setCheckoutError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function cancel(id: string) {
    if (!window.confirm("درخواست بررسی لایسنس لغو شود؟")) return;
    setBusy(true);
    try {
      await api.request(
        "/api/me/license/orders/" + encodeURIComponent(id) + "/cancel",
        "POST",
      );
      await refresh();
      notify("درخواست لغو شد.");
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
          title="لایسنس، متناسب با سرمایهٔ شما"
          description="هر سه ربات در تمام پلن‌ها. سرمایهٔ حساب را انتخاب کنید و دورهٔ مناسب خود را بسازید."
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
              ? "حساب متصل به لایسنس: " + p.account_id
              : "هنوز لایسنس فعالی ندارید."}
          </span>
          {p?.license_id && (
            <a
              id="download-license"
              href="/api/me/license/download"
              className="text-link"
              download="trade-license.json"
            >
              دانلود لایسنس امضاشده ↙
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
                notify("وضعیت لایسنس به‌روز شد.");
              } catch (e) {
                report(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            به‌روزرسانی وضعیت ↻
          </button>
        </div>
        <p className="note">
          وضعیت این بخش مربوط به لایسنس صادرشده است؛ اعمال آن روی ربات پس از نصب
          فایل توسط مدیر انجام می‌شود. واریز و برداشت‌های مبنای لایسنس با بررسی
          پشتیبانی ثبت می‌شوند.
        </p>
        <div className="plan-builder">
          <div className="plan-controls">
            <label htmlFor="capital-tier">
              سقف سرمایهٔ حساب <span className="field-hint">دلار آمریکا</span>
            </label>
            <select
              id="capital-tier"
              value={cap}
              disabled={loading || busy}
              onChange={(e) => setCap(Number(e.target.value))}
              aria-describedby="tier-help"
            >
              {!plans ? (
                <option value={10000}>در حال دریافت تعرفه‌ها…</option>
              ) : (
                plans.tiers.map((t) => (
                  <option key={t.cap_usd} value={t.cap_usd}>
                    تا {usd(t.cap_usd)}
                  </option>
                ))
              )}
            </select>
            <p id="tier-help" className="note">
              پلنی را انتخاب کنید که سرمایهٔ فعلی حسابتان را پوشش دهد.
            </p>
            <fieldset className="term-fieldset">
              <legend>مدت اشتراک</legend>
              <div className="term-switch">
                {[
                  [1, "یک‌ماهه"],
                  [3, "سه‌ماهه"],
                  [6, "شش‌ماهه"],
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
                ? "ارتقا با حفظ تاریخ پایان و مدت پلن فعلی انجام می‌شود. تمدید پس از پایان اعتبار در دسترس است."
                : ""}
            </p>
            <div className="plan-inclusions">
              <span>✓ شاهین، موج‌سوار و ققنوس</span>
              <span>✓ به‌روزرسانی و پشتیبانی نصب</span>
              <span>✓ یک حساب اختصاصی</span>
              <span>✓ مدیریت معاملات باز پس از انقضا</span>
            </div>
          </div>
          <div className="price-card">
            <div className="price-card-top">
              <span>پکیج هر سه ربات</span>
              <span className="price-badge">
                {active && canQuote
                  ? "ارتقای پلن"
                  : saving > 0
                    ? faNumber(saving) + "٪ صرفه‌جویی"
                    : "USD"}
              </span>
            </div>
            <div className="price-line">
              <strong id="plan-price">
                {canQuote && !currentQuote
                  ? "…"
                  : faNumber(
                      (currentQuote?.price_cents ?? fullPrice * 100) / 100,
                    )}
              </strong>
              <span>دلار</span>
            </div>
            <p id="monthly-equivalent">
              {active && currentQuote
                ? "مابه‌التفاوت تا " +
                  faDate(currentQuote.expires_at) +
                  " · پایان دوره تغییر نمی‌کند"
                : "معادل " +
                  usd(fullPrice / months) +
                  " در ماه · قیمت کل " +
                  faNumber(months) +
                  " ماه"}
            </p>
            <div className="price-divider" />
            <div className="price-meta">
              <span>سقف سرمایه</span>
              <strong>{usd(cap)}</strong>
            </div>
            <div className="price-meta">
              <span>نوع درخواست</span>
              <strong>
                {active
                  ? "ارتقای پلن فعال"
                  : p?.state === "expired"
                    ? "تمدید اشتراک"
                    : "اشتراک جدید"}
              </strong>
            </div>
            <button
              id="request-license"
              className="full"
              disabled={!currentQuote || busy || pending}
              onClick={openCheckout}
            >
              بررسی و ثبت درخواست ←
            </button>
            <p className="price-note">{purchaseNote}</p>
          </div>
        </div>
        <div className="policy-strip">
          <div>
            <span className="policy-icon">
              <Arrow />
            </span>
            <h3>رشد از سود، بدون ارتقای اجباری</h3>
            <p>
              سود ربات در طول دوره هزینهٔ اضافه ندارد؛ سرمایه در تمدید دوباره
              بررسی می‌شود.
            </p>
          </div>
          <div>
            <span className="policy-icon">＋</span>
            <h3>واریز جدید، با مهلت ارتقا</h3>
            <p>
              اگر سرمایهٔ مبنا از سقف بیشتر شود، ۷۲ ساعت برای ارتقا دارید؛ سپس
              فقط ورود جدید متوقف می‌شود.
            </p>
          </div>
          <div>
            <span className="policy-icon">◷</span>
            <h3>ارتقا با مابه‌التفاوت</h3>
            <p>
              برای ارتقای پلن فعال، فقط مابه‌التفاوت متناسب با زمان باقی‌مانده
              محاسبه می‌شود.
            </p>
          </div>
        </div>
        <details className="pricing-details">
          <summary>
            مقایسهٔ کامل تعرفه‌ها <span>＋</span>
          </summary>
          <div className="table-wrap">
            <table className="pricing-table">
              <caption className="sr-only">
                تعرفهٔ پکیج سه ربات، دلار آمریکا
              </caption>
              <thead>
                <tr>
                  <th>سقف سرمایه</th>
                  <th>یک‌ماهه</th>
                  <th>سه‌ماهه</th>
                  <th>شش‌ماهه</th>
                </tr>
              </thead>
              <tbody id="pricing-rows">
                {plans?.tiers.map((t) => (
                  <tr key={t.cap_usd}>
                    <td>{usd(t.cap_usd)}</td>
                    {["1", "3", "6"].map((m) => (
                      <td key={m}>{usd(t.prices_cents[m] / 100)}</td>
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
          title="درخواست‌های اشتراک"
          number="02 / ORDERS"
        />
        {!snapshot?.orders.length ? (
          <p className="empty-state">
            هنوز درخواستی ثبت نکرده‌اید. پلن مناسب خود را از بخش بالا انتخاب
            کنید.
          </p>
        ) : null}
        <div className="table-wrap">
          <table hidden={!snapshot?.orders.length}>
            <thead>
              <tr>
                {[
                  "کد پیگیری",
                  "پلن / دوره",
                  "مبلغ",
                  "تاریخ ثبت",
                  "وضعیت",
                  "عملیات",
                ].map((t) => (
                  <th key={t}>{t}</th>
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
                    {usd(o.cap_usd)} / {faNumber(o.months)} ماه
                  </td>
                  <td>{usd(o.price_cents / 100)}</td>
                  <td>{faDate(o.created * 1000)}</td>
                  <td>
                    <span className={"order-status " + o.status}>
                      {orderLabels[o.status] || o.status}
                    </span>
                  </td>
                  <td>
                    {o.status === "pending" ? (
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() => cancel(o.id)}
                        aria-label={"لغو درخواست " + o.id.slice(0, 8)}
                      >
                        لغو درخواست
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
          ثبت درخواست، پرداخت یا فعال‌سازی خودکار نیست؛ پشتیبانی آن را بررسی
          می‌کند.
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
          <h2 id="checkout-title">مرور درخواست لایسنس</h2>
          <p>
            {checkout &&
              "پکیج هر سه ربات، سقف " +
                usd(checkout.cap_usd) +
                "، " +
                faNumber(checkout.months) +
                " ماه" +
                (checkout.kind === "upgrade"
                  ? " · پایان اعتبار " + faDate(checkout.expires_at)
                  : " · شروع دوره پس از تأیید پشتیبانی")}
          </p>
          <div className="checkout-total">
            <span>مبلغ درخواست</span>
            <strong>{checkout ? usd(checkout.price_cents / 100) : ""}</strong>
          </div>
          <p className="note">
            پرداخت آنلاین در این پنل فعال نیست. فعال‌سازی پس از تأیید پرداخت،
            شناسه و سرمایهٔ حساب انجام می‌شود.
          </p>
          <label className="consent">
            <input
              id="checkout-consent"
              type="checkbox"
              checked={consent}
              disabled={busy}
              onChange={(e) => setConsent(e.target.checked)}
            />
            تعرفه، مدت و شرایط لایسنس یک حساب را خوانده‌ام.
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
              ثبت درخواست
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => setCheckout(null)}
            >
              بازگشت
            </button>
          </div>
        </div>
      </dialog>
    </>
  );
}
