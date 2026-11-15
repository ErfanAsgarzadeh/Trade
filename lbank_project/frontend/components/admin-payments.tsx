"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiClient, ApiError, errorText } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useLang } from "@/lib/lang";
import { Heading } from "./shared";
import TotpField from "./totp-field";

interface Settings {
  tron_address: string;
  bsc_address: string;
  invoice_minutes: number;
  auto_approve_signals: boolean;
  bsc_rpc: string;
  trongrid_url: string;
  bsc_rpc_verify: string;
  tron_verify_url: string;
  auto_approve_max_usd: number;
  verify_ok: boolean;
  verify_failures: number;
  verify_failed_at: number | null;
  methods: { network: string; token: string; label: string }[];
  watcher_seen: number | null;
  checked: { tron: number | null; bsc: number | null };
}
interface Transfer {
  tx_ref: string;
  network: string;
  token: string;
  from_address: string;
  amount: string | null;
  seen: number;
  status: "matched" | "unmatched";
  order_id: string | null;
  explorer_url: string;
}

function AttachForm({
  api,
  report,
  transfer,
  done,
}: {
  api: ApiClient;
  report: (e: unknown) => void;
  transfer: Transfer;
  done: () => void;
}) {
  const { t } = useLang();
  const [order, setOrder] = useState(""),
    [busy, setBusy] = useState(false);
  async function attach(e: React.FormEvent) {
    e.preventDefault();
    const amount = transfer.amount ?? "?";
    if (
      !window.confirm(
        t(
          `این واریز به مبلغ ${amount} ${transfer.token} به عنوان پرداخت کامل سفارش ${order} ثبت شود؟ این کار برگشت‌پذیر نیست.`,
          `Record this transfer of ${amount} ${transfer.token} as full payment for order ${order}? This cannot be undone.`,
        ),
      )
    )
      return;
    setBusy(true);
    try {
      await api.request("/api/admin/payments/transfers/attach", "POST", {
        tx_ref: transfer.tx_ref,
        order_id: order.trim(),
      });
      done();
    } catch (err) {
      report(err);
    } finally {
      setBusy(false);
    }
  }
  if (transfer.status !== "unmatched" || transfer.amount === null) return null;
  return (
    <form className="admin-row-note" onSubmit={attach}>
      <label className="sr-only" htmlFor={"attach-" + transfer.tx_ref}>
        {t("کد سفارش", "Order reference")}
      </label>
      <input
        id={"attach-" + transfer.tx_ref}
        dir="ltr"
        value={order}
        pattern="[0-9a-fA-F\-]{8,36}"
        minLength={8}
        maxLength={36}
        required
        placeholder={t("کد سفارش", "Order reference")}
        onChange={(e) => setOrder(e.target.value)}
      />
      <button className="text-button" type="submit" disabled={busy}>
        {t("وصل به سفارش", "Attach to order")}
      </button>
    </form>
  );
}

export default function AdminPayments({
  api,
  report,
}: {
  api: ApiClient;
  report: (e: unknown) => void;
}) {
  const { t, lang } = useLang();
  const [settings, setSettings] = useState<Settings | null>(null),
    [transfers, setTransfers] = useState<Transfer[]>([]),
    [form, setForm] = useState({
      tron_address: "",
      bsc_address: "",
      invoice_minutes: 60,
      auto_approve_signals: false,
      auto_approve_max_usd: 500,
    }),
    [totp, setTotp] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const load = useCallback(
    () =>
      api
        .request<{ settings: Settings; transfers: Transfer[] }>(
          "/api/admin/payments",
        )
        .then((d) => {
          setSettings(d.settings);
          setTransfers(d.transfers);
          setForm({
            tron_address: d.settings.tron_address,
            bsc_address: d.settings.bsc_address,
            invoice_minutes: d.settings.invoice_minutes,
            auto_approve_signals: d.settings.auto_approve_signals,
            auto_approve_max_usd: d.settings.auto_approve_max_usd,
          });
        })
        .catch(report),
    [api, report],
  );
  useEffect(() => {
    void load();
  }, [load]);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (
      settings &&
      (form.tron_address !== settings.tron_address ||
        form.bsc_address !== settings.bsc_address) &&
      !window.confirm(
        t(
          "آدرس دریافت تغییر می‌کند. مطمئن شوید آدرس متعلق به کیف پول خودتان است و آن را از داخل Trust Wallet کپی کرده‌اید. ادامه می‌دهید؟",
          "The receiving address will change. Make sure it is your own wallet and that you copied it from Trust Wallet. Continue?",
        ),
      )
    )
      return;
    setBusy(true);
    setMessage("");
    try {
      await api.request("/api/admin/payments", "PUT", {
        ...form,
        bsc_rpc: settings?.bsc_rpc,
        trongrid_url: settings?.trongrid_url,
        bsc_rpc_verify: settings?.bsc_rpc_verify,
        tron_verify_url: settings?.tron_verify_url,
        totp,
      });
      setTotp("");
      setMessage(t("تنظیمات پرداخت ذخیره شد.", "Payment settings saved."));
      void load();
    } catch (err) {
      setMessage(
        err instanceof ApiError && err.status === 422
          ? t(
              "آدرس معتبر نیست. آدرس TRON با T شروع می‌شود و آدرس BNB Smart Chain با 0x.",
              "That address is not valid. A TRON address starts with T and a BNB Smart Chain address with 0x.",
            )
          : errorText(err),
      );
    } finally {
      setBusy(false);
    }
  }
  const status = (time: number | null) =>
    time ? dateTime(time, lang) : t("هنوز بررسی نشده", "Not checked yet");
  return (
    <>
      <section className="panel" id="admin-payments">
        <Heading
          eyebrow="PAYMENTS"
          title={t("دریافت USDT و USDC", "Receiving USDT and USDC")}
          description={t(
            "پرداخت‌ها مستقیم به کیف پول Trust Wallet شما می‌روند. سایت فقط آدرس عمومی را می‌داند و هیچ کلید خصوصی یا عبارت بازیابی‌ای لازم ندارد.",
            "Payments go straight to your Trust Wallet. The site only knows the public address and never needs a private key or recovery phrase.",
          )}
        />
        <form className="admin-payment-form" onSubmit={save}>
          <label htmlFor="pay-tron">
            {t("آدرس TRON برای USDT (TRC20)", "TRON address for USDT (TRC20)")}
          </label>
          <input
            id="pay-tron"
            dir="ltr"
            placeholder="T…"
            value={form.tron_address}
            onChange={(e) =>
              setForm((f) => ({ ...f, tron_address: e.target.value.trim() }))
            }
          />
          <label htmlFor="pay-bsc">
            {t(
              "آدرس BNB Smart Chain برای USDT و USDC (BEP20)",
              "BNB Smart Chain address for USDT and USDC (BEP20)",
            )}
          </label>
          <input
            id="pay-bsc"
            dir="ltr"
            placeholder="0x…"
            value={form.bsc_address}
            onChange={(e) =>
              setForm((f) => ({ ...f, bsc_address: e.target.value.trim() }))
            }
          />
          <p className="field-hint">
            {t(
              "در Trust Wallet: Receive، سپس USDT روی TRON یا BNB Smart Chain را انتخاب و آدرس را کپی کنید. خالی گذاشتن هر آدرس، آن روش پرداخت را خاموش می‌کند.",
              "In Trust Wallet: Receive, choose USDT on TRON or BNB Smart Chain, and copy the address. Leaving an address empty turns that payment method off.",
            )}
          </p>
          <label htmlFor="pay-minutes">
            {t(
              "مهلت پرداخت هر فاکتور (دقیقه)",
              "Time to pay each invoice (minutes)",
            )}
          </label>
          <input
            id="pay-minutes"
            type="number"
            dir="ltr"
            min={15}
            max={1440}
            value={form.invoice_minutes}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                invoice_minutes: Number(e.target.value),
              }))
            }
          />
          <label className="consent">
            <input
              type="checkbox"
              checked={form.auto_approve_signals}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  auto_approve_signals: e.target.checked,
                }))
              }
            />
            {t(
              "پس از تأیید پرداخت روی شبکه، اشتراک «فقط سیگنال» خودکار برای صدور لایسنس فرستاده شود (به نام شما). معاملهٔ خودکار همیشه بررسی دستی حساب صرافی را لازم دارد.",
              "After on-chain confirmation, send signals-only subscriptions for license issuing automatically (in your name). Automated trading always needs a manual exchange-account check.",
            )}
          </label>
          <label htmlFor="pay-max">
            {t(
              "سقف دلاری تأیید خودکار سفارش",
              "Automatic approval ceiling (USD)",
            )}
          </label>
          <input
            id="pay-max"
            type="number"
            dir="ltr"
            min={0}
            max={1000000}
            value={form.auto_approve_max_usd}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                auto_approve_max_usd: Number(e.target.value),
              }))
            }
          />
          <p className="field-hint">
            {t(
              "سفارش پرداخت‌شده‌ای که قیمتش بالاتر از این سقف باشد، برای تأیید دستی می‌ماند.",
              "A paid order priced above this ceiling waits for your manual approval.",
            )}
          </p>
          <TotpField id="pay-totp" value={totp} onChange={setTotp} />
          <button type="submit" disabled={busy}>
            {t("ذخیرهٔ تنظیمات پرداخت", "Save payment settings")}
          </button>
          <p className="admin-error" role="status">
            {message}
          </p>
        </form>
        {settings && !settings.verify_ok && (
          <p id="verify-warning" className="admin-error" role="alert">
            {t(
              "تأیید منبع دوم در حال شکست است؛ پرداخت‌های جدید ثبت نمی‌شوند تا منبع دوم همان تراکنش را تأیید کند.",
              "Second-source verification is failing; new payments are not recorded until the second source confirms the same transaction.",
            )}{" "}
            <bdi dir="ltr">
              {settings.verify_failures}
              {settings.verify_failed_at
                ? " · " + dateTime(settings.verify_failed_at, lang)
                : ""}
            </bdi>
          </p>
        )}
        <div className="admin-overview-services">
          <article>
            <h3>{t("سرویس بررسی پرداخت", "Payment checker")}</h3>
            <p>{status(settings?.watcher_seen ?? null)}</p>
            <p className="note">
              {t(
                "این سرویس در Docker با نام payment-worker اجرا می‌شود و هر ۲۰ ثانیه شبکه را بررسی می‌کند.",
                "This runs in Docker as payment-worker and checks the networks every 20 seconds.",
              )}
            </p>
          </article>
          <article>
            <h3>TRON</h3>
            <p>
              {t("آخرین بررسی موفق: ", "Last successful check: ") +
                status(settings?.checked.tron ?? null)}
            </p>
          </article>
          <article>
            <h3>BNB Smart Chain</h3>
            <p>
              {t("آخرین بررسی موفق: ", "Last successful check: ") +
                status(settings?.checked.bsc ?? null)}
            </p>
          </article>
        </div>
      </section>
      <section className="panel">
        <Heading
          eyebrow="INCOMING TRANSFERS"
          title={t("واریزهای دریافتی", "Incoming transfers")}
          description={t(
            "همهٔ واریزهای تأییدشده به آدرس‌های شما. واریزی که با هیچ فاکتوری جور نشده (مبلغ یا شبکهٔ اشتباه، پرداخت دیرتر از ۲۴ ساعت) را دستی بررسی کنید. اگر صرافی کارمزد را از مبلغ کم کرده، واریز را همین‌جا به سفارش مشتری وصل کنید و سپس درخواست را تأیید کنید.",
            "Every confirmed transfer to your addresses. Check unmatched ones (wrong amount or network, paid more than 24 hours late) by hand. If the customer's exchange deducted its fee, attach the transfer to their order here, then approve the request.",
          )}
        />
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {[
                  t("زمان", "Time"),
                  t("شبکه", "Network"),
                  t("مبلغ", "Amount"),
                  t("وضعیت", "Status"),
                  t("شناسه", "Reference"),
                ].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {transfers.map((x) => (
                <tr key={x.tx_ref}>
                  <td>{dateTime(x.seen, lang)}</td>
                  <td>
                    {x.token} · {x.network === "tron" ? "TRC20" : "BEP20"}
                  </td>
                  <td>
                    <bdi dir="ltr">{x.amount ?? t("غیرعادی", "unusual")}</bdi>
                  </td>
                  <td>
                    <span
                      className={
                        "pill " +
                        (x.status === "matched" ? "success" : "warning")
                      }
                    >
                      {x.status === "matched"
                        ? t("پرداخت سفارش", "Order paid")
                        : t("بدون فاکتور", "Unmatched")}
                    </span>
                  </td>
                  <td>
                    <a href={x.explorer_url} target="_blank" rel="noopener">
                      <bdi dir="ltr">{x.tx_ref.slice(0, 22)}…</bdi>
                    </a>
                    <AttachForm
                      api={api}
                      report={report}
                      transfer={x}
                      done={() => void load()}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!transfers.length && (
          <p className="empty-state">
            {t("هنوز واریزی ثبت نشده است.", "No transfers yet.")}
          </p>
        )}
      </section>
    </>
  );
}
