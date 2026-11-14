"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiClient, ApiError, errorText } from "@/lib/api";
import { useLang } from "@/lib/lang";
import { injectedWallet, isTrustWallet, payWithWallet } from "@/lib/wallet";
import QrCode from "./qr-code";

interface Method {
  network: "tron" | "bsc";
  token: "USDT" | "USDC";
  label: string;
}
export interface Invoice {
  id: string;
  network: "tron" | "bsc";
  token: string;
  label: string;
  address: string;
  amount: string;
  amount_micro: number;
  status: "open" | "expired" | "replaced" | "paid" | "cancelled";
  expires: number;
  tx_ref: string | null;
  contract: string;
  decimals: number;
  trust_link: string;
  explorer_url: string | null;
}

/** Pay a pending order in USDT/USDC straight to the site owner's wallet; the server confirms it on-chain. */
export default function PaymentPanel({
  api,
  orderId,
  onPaid,
}: {
  api: ApiClient;
  orderId: string;
  onPaid: () => void;
}) {
  const { t } = useLang();
  const [methods, setMethods] = useState<Method[] | null>(null),
    [invoice, setInvoice] = useState<Invoice | null>(null),
    [busy, setBusy] = useState(false),
    [note, setNote] = useState(""),
    [now, setNow] = useState(() => Date.now() / 1000),
    [wallet, setWallet] = useState<"none" | "trust" | "other">("none");
  const load = useCallback(async () => {
    try {
      setInvoice(
        await api.request<Invoice>(`/api/me/license/orders/${orderId}/invoice`),
      );
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) setNote(errorText(e));
    }
  }, [api, orderId]);
  useEffect(() => {
    const found = injectedWallet();
    setWallet(found ? (isTrustWallet(found) ? "trust" : "other") : "none");
    api
      .request<{ methods: Method[] }>("/api/me/payment-methods")
      .then((d) => setMethods(d.methods))
      .catch((e) => setNote(errorText(e)));
    void load();
  }, [api, load]);
  // Watch for the on-chain confirmation while the invoice can still be paid.
  useEffect(() => {
    if (!invoice || !["open", "expired"].includes(invoice.status)) return;
    const poll = setInterval(load, 10000),
      clock = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(clock);
    };
  }, [invoice, load]);
  useEffect(() => {
    if (invoice?.status === "paid") onPaid();
  }, [invoice?.status, onPaid]);

  async function choose(method: Method) {
    setBusy(true);
    setNote("");
    try {
      setInvoice(
        await api.request<Invoice>(
          `/api/me/license/orders/${orderId}/invoice`,
          "POST",
          {
            network: method.network,
            token: method.token,
          },
        ),
      );
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function connectAndPay() {
    if (!invoice) return;
    setBusy(true);
    setNote("");
    try {
      await payWithWallet(invoice);
      setNote(
        t(
          "تراکنش از کیف پول ارسال شد. تأیید روی شبکه معمولاً کمتر از یک دقیقه طول می‌کشد و این صفحه خودکار به‌روز می‌شود.",
          "The wallet sent the transaction. Network confirmation usually takes under a minute; this page updates by itself.",
        ),
      );
    } catch (e) {
      const code = (e as { code?: number }).code;
      setNote(
        code === 4001
          ? t(
              "پرداخت در کیف پول لغو شد.",
              "Payment was cancelled in the wallet.",
            )
          : t(
              "کیف پول پرداخت را انجام نداد. می‌توانید با دکمهٔ Trust Wallet یا کد QR پرداخت کنید.",
              "The wallet did not complete the payment. You can pay with the Trust Wallet button or the QR code.",
            ),
      );
    } finally {
      setBusy(false);
    }
  }
  const copy = (text: string, what: string) => {
    void navigator.clipboard?.writeText(text);
    setNote(what);
  };
  const left = invoice ? Math.max(0, Math.round(invoice.expires - now)) : 0;
  const minutes = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  const live =
    invoice && (invoice.status === "open" || invoice.status === "expired");

  if (methods && !methods.length && !invoice)
    return (
      <div className="payment-panel" id="payment-panel">
        <p className="note">
          {t(
            "پرداخت آنلاین هنوز فعال نشده است؛ پشتیبانی برای پرداخت با شما هماهنگ می‌کند.",
            "Online payment is not enabled yet; support will arrange payment with you.",
          )}
        </p>
      </div>
    );
  return (
    <div className="payment-panel" id="payment-panel">
      <span className="eyebrow">PAY WITH USDT / USDC</span>
      <h3>
        {t("پرداخت مستقیم با تتر یا USDC", "Pay directly with USDT or USDC")}
      </h3>
      <p className="note">
        {t(
          "مبلغ مستقیم به کیف پول آوینا می‌رود و بعد از تأیید شبکه، خودکار ثبت می‌شود؛ نیازی به وارد کردن هش تراکنش نیست.",
          "The payment goes straight to Avina's wallet and is recorded automatically once the network confirms it; no transaction hash needed.",
        )}
      </p>
      <div
        className="payment-methods"
        role="group"
        aria-label={t("روش پرداخت", "Payment method")}
      >
        {(methods ?? []).map((m) => {
          const selected =
            invoice?.network === m.network &&
            invoice?.token === m.token &&
            live;
          return (
            <button
              key={m.network + m.token}
              type="button"
              className={selected ? "active" : "secondary"}
              aria-pressed={!!selected}
              disabled={busy || invoice?.status === "paid"}
              onClick={() => choose(m)}
            >
              {m.label}
            </button>
          );
        })}
      </div>
      {invoice?.status === "paid" ? (
        <div className="payment-paid" role="status">
          <strong>{t("پرداخت تأیید شد.", "Payment confirmed.")}</strong>
          <p>
            {t(
              "سفارش شما برای فعال‌سازی ثبت شد. ",
              "Your order is now queued for activation. ",
            )}
            {invoice.explorer_url && (
              <a href={invoice.explorer_url} target="_blank" rel="noopener">
                {t("مشاهدهٔ تراکنش", "View transaction")}
              </a>
            )}
          </p>
        </div>
      ) : (
        live && (
          <div className="payment-invoice" id="payment-invoice">
            <div className="payment-qr">
              <QrCode
                value={invoice.trust_link}
                label={t(
                  "کد QR پرداخت؛ با دوربین گوشی اسکن کنید تا Trust Wallet با مبلغ و آدرس باز شود",
                  "Payment QR code; scan with your phone camera to open Trust Wallet with the amount and address",
                )}
              />
              <small>
                {t("با دوربین گوشی اسکن کنید", "Scan with your phone camera")}
              </small>
            </div>
            <div className="payment-details">
              <span className="field-hint">
                {t("دقیقاً همین مبلغ را بفرستید", "Send exactly this amount")}
              </span>
              <div className="payment-amount">
                <bdi dir="ltr">
                  {invoice.amount} {invoice.token}
                </bdi>
                <button
                  type="button"
                  className="secondary small"
                  onClick={() =>
                    copy(invoice.amount, t("مبلغ کپی شد.", "Amount copied."))
                  }
                >
                  {t("کپی", "Copy")}
                </button>
              </div>
              <span className="field-hint">
                {t("شبکه: ", "Network: ")}
                <strong>{invoice.label}</strong>
              </span>
              <span className="field-hint">
                {t("آدرس کیف پول", "Wallet address")}
              </span>
              <div className="payment-address">
                <bdi dir="ltr">{invoice.address}</bdi>
                <button
                  type="button"
                  className="secondary small"
                  onClick={() =>
                    copy(invoice.address, t("آدرس کپی شد.", "Address copied."))
                  }
                >
                  {t("کپی", "Copy")}
                </button>
              </div>
              <div className="payment-actions">
                {invoice.network === "bsc" && wallet !== "none" && (
                  <button type="button" disabled={busy} onClick={connectAndPay}>
                    {wallet === "trust"
                      ? t(
                          "اتصال و پرداخت با Trust Wallet",
                          "Connect and pay with Trust Wallet",
                        )
                      : t(
                          "اتصال و پرداخت با کیف پول",
                          "Connect and pay with your wallet",
                        )}
                  </button>
                )}
                <a className="button secondary" href={invoice.trust_link}>
                  {t(
                    "پرداخت در اپ Trust Wallet",
                    "Pay in the Trust Wallet app",
                  )}
                </a>
              </div>
              <p className="note" role="status">
                {invoice.status === "expired"
                  ? t(
                      "مهلت این مبلغ تمام شده است. اگر پرداخت کرده‌اید تا ۲۴ ساعت شناسایی می‌شود؛ وگرنه روش پرداخت را دوباره انتخاب کنید تا مبلغ تازه بگیرید.",
                      "This amount has expired. A payment already sent is still recognized for 24 hours; otherwise choose the method again for a fresh amount.",
                    )
                  : t(
                      `منتظر پرداخت · ${minutes} تا پایان مهلت · وضعیت هر ۱۰ ثانیه بررسی می‌شود.`,
                      `Waiting for payment · ${minutes} left · checked every 10 seconds.`,
                    )}
              </p>
              <p className="note warning-text">
                {t(
                  "فقط روی همین شبکه و دقیقاً همین مبلغ بفرستید؛ کارمزد شبکه جداست. مبلغ دیگر یا شبکهٔ دیگر خودکار شناسایی نمی‌شود و باید با پشتیبانی پیگیری شود.",
                  "Send only on this network and exactly this amount; the network fee is separate. A different amount or network is not recognized automatically and needs support.",
                )}
              </p>
            </div>
          </div>
        )
      )}
      {note && (
        <p className="note" role="status">
          {note}
        </p>
      )}
    </div>
  );
}
