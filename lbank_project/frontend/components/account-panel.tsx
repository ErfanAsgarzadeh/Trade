"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClient } from "@/lib/api";
import type { Connection, Exchange } from "@/lib/types";
import { dateTime, stateLabel } from "@/lib/format";
import { useLang } from "@/lib/lang";
import { DataTable, Heading } from "./shared";
interface Props {
  api: ApiClient;
  report: (e: unknown) => void;
  notify: (s: string) => void;
}
const emptyCredentials = { api_key: "", secret: "", passphrase: "", uid: "" };
export default function AccountPanel({ api, report, notify }: Props) {
  const { lang, t } = useLang();
  const state = (key: string) => stateLabel(key, lang);
  const [catalog, setCatalog] = useState<Exchange[]>([]),
    [connection, setConnection] = useState<Connection | null>(null);
  const [exchange, setExchange] = useState("thetruetrade"),
    [market, setMarket] = useState("futures"),
    [credentials, setCredentials] = useState(emptyCredentials),
    [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const venue = catalog.find((v) => v.id === exchange),
    fields = venue?.required_fields[market] || [];
  const refresh = useCallback(async () => {
    const epoch = generation.current;
    const c = await api.request<Connection>("/api/me/connection");
    if (epoch === generation.current) setConnection(c);
  }, [api]);
  useEffect(() => {
    let mounted = true;
    Promise.all([
      api.request<{ exchanges: Exchange[] }>("/api/exchanges"),
      api.request<Connection>("/api/me/connection"),
    ])
      .then(([result, c]) => {
        if (!mounted) return;
        setCatalog(result.exchanges);
        setConnection(c);
        const v =
          result.exchanges.find(
            (v) => v.id === (c.configured ? c.exchange_id : "thetruetrade"),
          ) || result.exchanges[0];
        if (v) {
          setExchange(v.id);
          setMarket(
            c.configured && v.markets.includes(c.market!)
              ? c.market!
              : v.markets.includes("spot")
                ? "spot"
                : v.markets[0],
          );
        }
      })
      .catch((e) => {
        if (mounted) report(e);
      });
    return () => {
      mounted = false;
      generation.current++;
    };
  }, [api, report]);
  useEffect(() => {
    if (
      !["queued", "refreshing", "retrying"].includes(
        connection?.account?.status || "",
      )
    )
      return;
    const timer = setTimeout(
      () => refresh().catch(report),
      15000 + Math.random() * 5000,
    );
    return () => clearTimeout(timer);
  }, [connection, refresh, report]);
  function changeExchange(id: string) {
    setCredentials(emptyCredentials);
    setExchange(id);
    const v = catalog.find((v) => v.id === id);
    setMarket(v?.markets.includes("spot") ? "spot" : v?.markets[0] || "");
  }
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    generation.current++;
    try {
      await api.request("/api/me/connection", "PUT", {
        exchange_id: exchange,
        market,
        api_key: credentials.api_key,
        secret: credentials.secret,
        passphrase: credentials.passphrase || null,
        uid: credentials.uid || null,
      });
      setCredentials(emptyCredentials);
      await refresh();
      notify(state("saved_unverified")!);
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function check() {
    setBusy(true);
    try {
      await api.request("/api/me/connection/refresh", "POST");
      await refresh();
      notify(
        t(
          "درخواست بررسی ثبت شد؛ نتیجه پس از بررسی نمایش داده می‌شود.",
          "Check requested; the result appears once it is done.",
        ),
      );
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function disconnect() {
    if (!window.confirm(t("اتصال ذخیره‌شده حذف شود؟", "Remove the saved connection?")))
      return;
    setBusy(true);
    generation.current++;
    try {
      await api.request("/api/me/connection", "DELETE");
      setCredentials(emptyCredentials);
      await refresh();
      notify(t("اتصال حذف شد.", "Connection removed."));
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  const snapshot = connection?.account?.snapshot;
  const field = (
    name: keyof typeof emptyCredentials,
    label: string,
    min: number,
    max: number,
  ) => (
    <>
      <label htmlFor={"credential-" + name}>{label}</label>
      <input
        id={"credential-" + name}
        type="password"
        dir="ltr"
        autoComplete="off"
        minLength={min}
        maxLength={max}
        required
        value={credentials[name]}
        onChange={(e) =>
          setCredentials((v) => ({ ...v, [name]: e.target.value }))
        }
      />
    </>
  );
  return (
    <section id="connection-section" className="panel">
      <Heading
        eyebrow="CONNECTED TO YOUR ACCOUNT"
        title={t("حساب صرافی شما", "Your exchange account")}
        description={t(
          "اتصال حساب و مشاهدهٔ موجودی، در فضای اختصاصی شما.",
          "Connect your account and see your balance in your private space.",
        )}
        number="03 / ACCOUNT"
      />
      <div className="grid">
        <div>
          <form id="connection-form" onSubmit={save}>
            <fieldset
              className="connection-fields"
              disabled={busy || !catalog.length}
            >
              <div className="form-pair">
                <div>
                  <label htmlFor="exchange-id">{t("صرافی", "Exchange")}</label>
                  <select
                    id="exchange-id"
                    value={exchange}
                    onChange={(e) => changeExchange(e.target.value)}
                    required
                  >
                    {catalog.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="market">{t("نوع حساب", "Account type")}</label>
                  <select
                    id="market"
                    value={market}
                    onChange={(e) => {
                      setMarket(e.target.value);
                      setCredentials(emptyCredentials);
                    }}
                  >
                    {venue?.markets.map((m) => (
                      <option key={m} value={m}>
                        {m === "spot"
                          ? "Spot"
                          : t("Futures / قرارداد دائمی", "Futures / perpetual")}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              {field("api_key", "API Key", 8, 512)}
              <label htmlFor="api-secret">Secret Key</label>
              <textarea
                id="api-secret"
                dir="ltr"
                autoComplete="off"
                minLength={8}
                maxLength={8192}
                required
                value={credentials.secret}
                onChange={(e) =>
                  setCredentials((v) => ({ ...v, secret: e.target.value }))
                }
              />
              {fields.includes("password") &&
                field("passphrase", "Passphrase", 1, 512)}
              {fields.includes("uid") &&
                field("uid", t("شناسهٔ حساب", "Account ID"), 1, 128)}
              <button type="submit">{t("ثبت کلیدهای حساب", "Save account keys")}</button>
            </fieldset>
          </form>
          <p className="note">
            {t(
              "برای مشاهدهٔ موجودی، کلید فقط‌خواندنی و بدون مجوز برداشت کافی است. ثبت کلید به معنی شروع معامله نیست؛ معاملات خودکار واقعی هنوز فعال نیستند.",
              "A read-only key without withdrawal permission is enough to see your balance. Saving a key does not start trading; real automated trades are not active yet.",
            )}
          </p>
        </div>
        <div className="connection-summary">
          <span className="eyebrow">CONNECTION STATUS</span>
          <h3 id="connection-status">
            {connection?.configured
              ? (catalog.find((v) => v.id === connection.exchange_id)?.name ||
                  connection.exchange_id) +
                " · " +
                connection.market +
                " · " +
                (state(connection.account?.status || "") ||
                  state("saved_unverified"))
              : t("حسابی ثبت نشده", "No account connected")}
          </h3>
          <div className="actions">
            <button
              id="refresh-account"
              className="secondary"
              disabled={busy || !connection?.configured}
              onClick={check}
            >
              {t("بررسی اتصال و دریافت موجودی", "Check connection and load balance")}
            </button>
            <button
              id="disconnect"
              className="text-button"
              disabled={busy || !connection?.configured}
              onClick={disconnect}
            >
              {t("حذف اتصال", "Remove connection")}
            </button>
          </div>
          <p className="note">
            {connection?.account?.checked_at
              ? t("آخرین بررسی: ", "Last checked: ") +
                dateTime(connection.account.checked_at, lang)
              : ""}
          </p>
          <DataTable
            headers={[
              t("دارایی", "Asset"),
              t("آزاد", "Free"),
              t("قفل‌شده", "Locked"),
              t("کل", "Total"),
            ]}
            rows={(snapshot?.balances || []).map((b) => [
              b.asset,
              b.free,
              b.locked,
              b.total,
            ])}
          />
          <p className="note">
            {snapshot?.balance_scope
              ? t("محدودهٔ موجودی: ", "Balance scope: ") + snapshot.balance_scope
              : ""}
          </p>
          <h3 className="positions-title">
            {t("پوزیشن‌های حساب صرافی", "Exchange account positions")}
          </h3>
          <DataTable
            financialColumns={[5]}
            sideColumns={[1]}
            headers={[
              t("نماد", "Symbol"),
              t("جهت", "Side"),
              t("قرارداد", "Contracts"),
              t("ورود", "Entry"),
              t("قیمت فعلی", "Mark price"),
              t("سود شناور", "Unrealized PnL"),
              t("اهرم", "Leverage"),
            ]}
            rows={(snapshot?.positions || []).map((p) => [
              p.symbol,
              p.side,
              p.contracts,
              p.entry_price,
              p.mark_price,
              p.unrealized_pnl,
              p.leverage,
            ])}
          />
          {snapshot &&
            connection?.market === "futures" &&
            !snapshot.positions_complete && (
              <p className="note">
                {t(
                  "فهرست ممکن است شامل همهٔ قراردادها یا صفحات حساب نباشد.",
                  "This list may not include every contract or account page.",
                )}
              </p>
            )}
          <p className="note">
            {t(
              "موجودی صرافی و سرمایهٔ آزمایشی ربات جدا هستند. حذف اتصال از پنل، کلید را در صرافی باطل نمی‌کند.",
              "Your exchange balance and the bot's trial capital are separate. Removing the connection here does not revoke the key at the exchange.",
            )}
          </p>
        </div>
      </div>
    </section>
  );
}
