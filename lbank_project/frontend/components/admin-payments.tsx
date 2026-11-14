"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiClient, ApiError, errorText } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useLang } from "@/lib/lang";
import { Heading } from "./shared";

interface Settings {
  tron_address: string;
  bsc_address: string;
  invoice_minutes: number;
  auto_approve_signals: boolean;
  bsc_rpc: string;
  trongrid_url: string;
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
    }),
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
      });
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
          <button type="submit" disabled={busy}>
            {t("ذخیرهٔ تنظیمات پرداخت", "Save payment settings")}
          </button>
          <p className="admin-error" role="status">
            {message}
          </p>
        </form>
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
            "همهٔ واریزهای تأییدشده به آدرس‌های شما. واریزی که با هیچ فاکتوری جور نشده (مبلغ یا شبکهٔ اشتباه، پرداخت دیرتر از ۲۴ ساعت) را دستی بررسی کنید و از کارتابل درخواست‌ها با همین شناسه تأیید کنید.",
            "Every confirmed transfer to your addresses. Check unmatched ones (wrong amount or network, paid more than 24 hours late) by hand and approve the request with this reference.",
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
