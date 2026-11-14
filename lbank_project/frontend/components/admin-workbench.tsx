"use client";
import { useEffect, useRef, useState } from "react";
import { ApiClient, errorText } from "@/lib/api";
import type { Plans, ProductPlan, Product } from "@/lib/types";
import { dateTime, longDate, money, num } from "@/lib/format";
import { useLang } from "@/lib/lang";
import type { Lang } from "@/lib/i18n";
import { Heading } from "./shared";
import AdminBlog from "./admin-blog";
import AdminPayments from "./admin-payments";
import type { Invoice } from "./payment-panel";

type Report = (error: unknown) => void;
interface PageData<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}
interface AdminUser {
  id: string;
  username: string;
  email: string | null;
  role: string;
  disabled: number;
  has_runtime: number;
  has_connection: number;
}
interface AdminOrder {
  id: string;
  user_id: string;
  username: string;
  cap_usd: number;
  months: number;
  product: Product;
  kind: string;
  price_cents: number;
  status: string;
  created: number;
  approval_state: string | null;
  error_code: string | null;
  payment: Invoice | null;
}
interface EventRow {
  id: string;
  actor: string | null;
  action: string;
  target: string;
  details: Record<string, unknown>;
  at: number;
}
interface Overview {
  counts: Record<string, number>;
  pricing: Plans;
  issuer_last_seen: number | null;
  account_queue: { states: Record<string, number> };
}
const tabs = [
  ["overview", "نمای کلی", "Overview"],
  ["orders", "کارتابل درخواست‌ها", "Requests"],
  ["users", "کاربران", "Users"],
  ["pricing", "قیمت و فروش", "Pricing and sales"],
  ["payments", "پرداخت", "Payments"],
  ["blog", "بلاگ", "Blog"],
  ["audit", "سوابق عملیات", "Audit log"],
] as const;
type Pair = [string, string];
const LABELS: Record<string, Pair> = {
  pending: ["در انتظار بررسی", "Awaiting review"],
  approved: ["صادرشده", "Issued"],
  cancelled: ["لغوشده", "Cancelled"],
  rejected: ["ردشده", "Rejected"],
  queued: ["در صف صدور", "Queued for issuing"],
  running: ["در حال صدور", "Issuing"],
  failed: ["صدور ناموفق", "Issuing failed"],
  completed: ["صادرشده", "Issued"],
};
const EVENTS: Record<string, Pair> = {
  role_changed: ["تغییر نقش از مسیر سرور", "Role changed on the server"],
  user_disabled: ["تعلیق دسترسی کاربر", "User access suspended"],
  user_enabled: ["فعال‌سازی کاربر", "User enabled"],
  order_rejected: ["رد درخواست", "Request rejected"],
  approval_requested: ["ارسال به صف صدور", "Sent to the issuing queue"],
  license_issued: ["صدور لایسنس", "License issued"],
  issuance_failed: ["خطای صدور", "Issuing error"],
  pricing_saved: ["ذخیرهٔ تعرفه", "Prices saved"],
  sales_closed: ["بستن فروش", "Sales closed"],
  blog_created: ["ساخت مقاله", "Article created"],
  blog_updated: ["ویرایش مقاله", "Article updated"],
  blog_deleted: ["حذف مقاله", "Article deleted"],
  payment_received: ["دریافت پرداخت روی شبکه", "On-chain payment received"],
  payment_settings_saved: ["تغییر تنظیمات پرداخت", "Payment settings changed"],
};
const label = (table: Record<string, Pair>, key: string, lang: Lang) =>
  table[key]?.[lang === "en" ? 1 : 0];
function useFormat() {
  const { lang, t } = useLang();
  return {
    lang,
    t,
    usd: (v: number) => money(v, lang),
    faNumber: (v: number) => num(v, lang),
    faDate: (v: string | number) => longDate(v, lang),
    labels: (key: string) => label(LABELS, key, lang),
  };
}
function Pager({
  offset,
  total,
  onChange,
}: {
  offset: number;
  total: number;
  onChange: (n: number) => void;
}) {
  const { t, faNumber } = useFormat();
  return (
    <div className="admin-pagination">
      <span>
        {faNumber(total)} {t("مورد", "items")}
      </span>
      <button
        className="secondary small"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - 30))}
      >
        {t("قبلی", "Previous")}
      </button>
      <button
        className="secondary small"
        disabled={offset + 30 >= total}
        onClick={() => onChange(offset + 30)}
      >
        {t("بعدی", "Next")}
      </button>
    </div>
  );
}

export default function AdminWorkbench({
  api,
  report,
}: {
  api: ApiClient;
  report: Report;
}) {
  const { lang, t, faNumber } = useFormat();
  const [tab, setTab] = useState<(typeof tabs)[number][0]>("overview"),
    [revision, setRevision] = useState(0),
    [data, setData] = useState<Overview | null>(null);
  useEffect(() => {
    let current = true;
    api
      .request<Overview>("/api/admin/overview")
      .then((value) => {
        if (current) setData(value);
      })
      .catch((e) => {
        if (current) report(e);
      });
    return () => {
      current = false;
    };
  }, [api, report, revision, tab]);
  const changed = () => setRevision((n) => n + 1);
  return (
    <div id="admin-workbench">
      <section className="dashboard-hero">
        <div>
          <span className="eyebrow">AVINA / CONTROL ROOM</span>
          <h1>{t("کارتابل مدیریت سامانه", "Admin control room")}</h1>
          <p>
            {t(
              "کاربران، درخواست‌ها و فروش؛ با دسترسی اختصاصی مدیر.",
              "Users, requests and sales; for the administrator only.",
            )}
          </p>
          <span className="pill admin-role">
            {t("مدیر سامانه", "Administrator")}
          </span>
        </div>
        <a
          className="button secondary"
          href={lang === "en" ? "/en/dashboard/" : "/dashboard/"}
        >
          {t("بازگشت به پنل مشتری", "Back to customer panel")}
        </a>
      </section>
      <div className="admin-layout">
        <nav
          className="admin-nav"
          aria-label={t("بخش‌های مدیریت", "Admin sections")}
        >
          {tabs.map(([key, fa, en]) => (
            <button
              key={key}
              id={"admin-tab-" + key}
              className={tab === key ? "active" : ""}
              aria-current={tab === key ? "page" : undefined}
              onClick={() => setTab(key)}
            >
              {t(fa, en)}
            </button>
          ))}
        </nav>
        <div className="admin-content">
          {tab === "overview" && (
            <>
              <div className="stat-grid">
                {[
                  ["users", t("کل کاربران", "Total users")],
                  [
                    "pending_orders",
                    t("درخواست در انتظار", "Pending requests"),
                  ],
                  ["issued_licenses", t("لایسنس صادرشده", "Licenses issued")],
                ].map(([key, label], i) => (
                  <article className="stat-card" key={key}>
                    <div className="stat-label">
                      {label}
                      <span>0{i + 1}</span>
                    </div>
                    <strong id={"admin-count-" + key}>
                      {data ? faNumber(data.counts[key] || 0) : "—"}
                    </strong>
                    <p>
                      {key === "issued_licenses"
                        ? t(
                            "تعداد کل صدور؛ شامل دوره‌های منقضی",
                            "All issued, including expired terms",
                          )
                        : t(
                            "اطلاعات پایگاه دادهٔ سامانه",
                            "From the site database",
                          )}
                    </p>
                  </article>
                ))}
              </div>
              <section className="panel">
                <Heading
                  eyebrow="OPERATIONS"
                  title={t("وضعیت سرویس‌ها", "Service status")}
                />
                <div className="admin-overview-services">
                  <article>
                    <h3>{t("صف صدور لایسنس", "License issuing queue")}</h3>
                    <strong>
                      {data ? faNumber(data.counts.queued_approvals) : "—"}
                    </strong>
                    <p>{t("در صف یا در حال امضا", "Queued or being signed")}</p>
                    <p className="note">
                      {data?.issuer_last_seen
                        ? t("آخرین فعالیت سرویس: ", "Last service activity: ") +
                          dateTime(data.issuer_last_seen, lang)
                        : t(
                            "سرویس صدور هنوز فعالیتی ثبت نکرده است.",
                            "The issuing service has not reported in yet.",
                          )}
                    </p>
                  </article>
                  <article>
                    <h3>{t("نیازمند رسیدگی", "Needs attention")}</h3>
                    <strong>
                      {data ? faNumber(data.counts.failed_approvals) : "—"}
                    </strong>
                    <p>
                      {t("درخواست‌های صدور ناموفق", "Failed issuing requests")}
                    </p>
                    <button
                      className="text-button"
                      onClick={() => setTab("orders")}
                    >
                      {t("مشاهدهٔ درخواست‌ها", "View requests")}
                    </button>
                  </article>
                </div>
                <p className="note">
                  {t(
                    "تأیید مدیر ابتدا در صف ثبت می‌شود. صدور نهایی به سرویس امضای جداگانه نیاز دارد؛ کلید خصوصی وارد مرورگر نمی‌شود.",
                    "Admin approval is queued first. Final issuing needs the separate signing service; the private key never enters the browser.",
                  )}
                </p>
              </section>
              <section className="panel">
                <Heading
                  eyebrow="SALES STATUS"
                  title={t("وضعیت فروش محصولات", "Product sales status")}
                />
                {data?.pricing.products.map((p) => (
                  <div key={p.product} className="admin-status-row">
                    <strong>{p.label}</strong>
                    <span
                      className={
                        "order-status " +
                        (p.sales_enabled ? "approved" : "cancelled")
                      }
                    >
                      {p.sales_enabled
                        ? t("فروش باز", "Sales open")
                        : t("فروش بسته", "Sales closed")}
                    </span>
                    <button
                      className="text-button"
                      onClick={() => setTab("pricing")}
                    >
                      {t("مدیریت تعرفه", "Manage prices")}
                    </button>
                  </div>
                ))}
                <button className="secondary" onClick={changed}>
                  {t("به‌روزرسانی وضعیت", "Refresh status")}
                </button>
              </section>
            </>
          )}
          {tab === "users" && (
            <Users api={api} report={report} changed={changed} />
          )}
          {tab === "orders" && (
            <Orders api={api} report={report} changed={changed} />
          )}
          {tab === "pricing" && (
            <Pricing api={api} report={report} changed={changed} />
          )}
          {tab === "payments" && <AdminPayments api={api} report={report} />}
          {tab === "blog" && <AdminBlog api={api} report={report} />}
          {tab === "audit" && <Events api={api} report={report} />}
        </div>
      </div>
    </div>
  );
}

function Users({
  api,
  report,
  changed,
}: {
  api: ApiClient;
  report: Report;
  changed: () => void;
}) {
  const { t } = useFormat();
  const [search, setSearch] = useState(""),
    [query, setQuery] = useState(""),
    [offset, setOffset] = useState(0),
    [revision, setRevision] = useState(0),
    [busy, setBusy] = useState(false),
    [data, setData] = useState<PageData<AdminUser> | null>(null);
  useEffect(() => {
    let current = true;
    api
      .request<PageData<AdminUser>>(
        "/api/admin/users?search=" +
          encodeURIComponent(query) +
          "&offset=" +
          offset,
      )
      .then((d) => {
        if (current) setData(d);
      })
      .catch((e) => {
        if (current) report(e);
      });
    return () => {
      current = false;
    };
  }, [api, report, query, offset, revision]);
  async function toggle(user: AdminUser) {
    if (
      !window.confirm(
        user.disabled
          ? t("دسترسی این کاربر فعال شود؟", "Enable this user's access?")
          : t(
              "دسترسی این کاربر به پنل تعلیق و نشست‌هایش بسته شود؟ این کار پوزیشن‌های ربات را نمی‌بندد.",
              "Suspend this user's panel access and end their sessions? This does not close bot positions.",
            ),
      )
    )
      return;
    setBusy(true);
    try {
      await api.request("/api/admin/users/" + user.id, "PATCH", {
        disabled: !user.disabled,
      });
      setRevision((n) => n + 1);
      changed();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <Heading
        eyebrow="CUSTOMERS"
        title={t("مدیریت کاربران", "Users")}
        description={t(
          "تغییر وضعیت دسترسی به پنل؛ نقش مدیر فقط از مسیر سرور تغییر می‌کند.",
          "Change panel access; the admin role can only be changed on the server.",
        )}
      />
      <form
        className="admin-search"
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setQuery(search.trim());
        }}
      >
        <label className="sr-only" htmlFor="admin-user-search">
          {t("جست‌وجوی نام کاربری یا ایمیل", "Search username or email")}
        </label>
        <input
          id="admin-user-search"
          dir="ltr"
          value={search}
          maxLength={80}
          placeholder={t("نام کاربری یا ایمیل", "username or email")}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button type="submit" className="secondary">
          {t("جست‌وجو", "Search")}
        </button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {[
                t("نام کاربری", "Username"),
                t("ایمیل", "Email"),
                t("نقش", "Role"),
                t("دسترسی", "Access"),
                t("اتصال", "Connection"),
                t("اجرای اختصاصی", "Dedicated runtime"),
                t("عملیات", "Actions"),
              ].map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody id="admin-user-rows">
            {data?.items.map((u) => (
              <tr key={u.id}>
                <td>
                  <bdi>{u.username}</bdi>
                </td>
                <td>
                  <bdi dir="ltr">{u.email || "—"}</bdi>
                </td>
                <td>
                  {u.role === "admin"
                    ? t("مدیر", "Admin")
                    : t("مشتری", "Customer")}
                </td>
                <td>
                  {u.disabled
                    ? t("تعلیق‌شده", "Suspended")
                    : t("فعال", "Active")}
                </td>
                <td>
                  {u.has_connection
                    ? t("ثبت‌شده", "Saved")
                    : t("ندارد", "None")}
                </td>
                <td>
                  {u.has_runtime
                    ? t("متصل", "Connected")
                    : t("متصل نیست", "Not connected")}
                </td>
                <td>
                  {u.role === "admin" ? (
                    <span className="note">
                      {t("مدیریت از مسیر سرور", "Managed on the server")}
                    </span>
                  ) : (
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() => toggle(u)}
                    >
                      {u.disabled
                        ? t("فعال‌سازی", "Enable")
                        : t("تعلیق دسترسی", "Suspend access")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && (
        <Pager offset={offset} total={data.total} onChange={setOffset} />
      )}
      <p className="note">
        {t(
          "تعلیق ورود به پنل، جایگزین توقف ربات یا ابطال لایسنس نصب‌شده نیست.",
          "Suspending panel access does not stop a bot or revoke an installed license.",
        )}
      </p>
    </section>
  );
}

function Orders({
  api,
  report,
  changed,
}: {
  api: ApiClient;
  report: Report;
  changed: () => void;
}) {
  const { t, usd, faNumber, faDate, labels } = useFormat();
  const [status, setStatus] = useState("pending"),
    [offset, setOffset] = useState(0),
    [revision, setRevision] = useState(0),
    [data, setData] = useState<PageData<AdminOrder> | null>(null);
  const [selection, setSelection] = useState<{
      order: AdminOrder;
      action: "approve" | "reject";
    } | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [verified, setVerified] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null),
    form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    let current = true;
    api
      .request<PageData<AdminOrder>>(
        "/api/admin/orders?status=" + status + "&offset=" + offset,
      )
      .then((d) => {
        if (current) setData(d);
      })
      .catch((e) => {
        if (current) report(e);
      });
    return () => {
      current = false;
    };
  }, [api, report, status, offset, revision]);
  useEffect(() => {
    if (selection) {
      form.current?.reset();
      setVerified(false);
      setError("");
      dialog.current?.showModal();
    } else dialog.current?.close();
  }, [selection]);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selection) return;
    const values = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      if (selection.action === "reject")
        await api.request(
          "/api/admin/orders/" + selection.order.id + "/reject",
          "POST",
          { reason: values.get("reason") },
        );
      else
        await api.request(
          "/api/admin/orders/" + selection.order.id + "/approve",
          "POST",
          {
            payment_ref: values.get("payment_ref"),
            account_id:
              selection.order.product === "autotrade"
                ? values.get("account_id")
                : null,
            equity_usd:
              selection.order.product === "autotrade"
                ? values.get("equity_usd")
                : null,
            confirmation: "PAYMENT_AND_ACCOUNT_VERIFIED",
          },
        );
      setSelection(null);
      setRevision((n) => n + 1);
      changed();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <Heading
        eyebrow="APPROVAL DESK"
        title={t("کارتابل درخواست‌های خرید", "Purchase requests")}
        description={t(
          "پرداخت و اطلاعات حساب را مستقل بررسی کنید؛ تأیید، درخواست امضا را در صف قرار می‌دهد.",
          "Check the payment and account details independently; approving queues the signing request.",
        )}
      />
      <div className="admin-filters">
        <label htmlFor="admin-order-filter">
          {t("وضعیت درخواست", "Request status")}
        </label>
        <select
          id="admin-order-filter"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        >
          {["pending", "approved", "rejected", "cancelled", "all"].map((s) => (
            <option key={s} value={s}>
              {s === "all" ? t("همه", "All") : labels(s)}
            </option>
          ))}
        </select>
        <button
          id="admin-refresh-orders"
          className="secondary"
          onClick={() => setRevision((n) => n + 1)}
        >
          {t("به‌روزرسانی", "Refresh")}
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {[
                t("کاربر / پیگیری", "User / reference"),
                t("محصول / دوره", "Product / term"),
                t("سرمایه", "Capital"),
                t("مبلغ", "Amount"),
                t("پرداخت", "Payment"),
                t("وضعیت", "Status"),
                t("عملیات", "Actions"),
              ].map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody id="admin-order-rows">
            {data?.items.map((o) => (
              <tr key={o.id}>
                <td>
                  <bdi>{o.username}</bdi>
                  <small className="admin-row-note">
                    <bdi>{o.id.slice(0, 8)}</bdi> · {faDate(o.created * 1000)}
                  </small>
                </td>
                <td>
                  {o.product === "signals"
                    ? t("فقط سیگنال", "Signals only")
                    : t("معاملهٔ خودکار", "Automated trading")}
                  <small className="admin-row-note">
                    {faNumber(o.months)}{" "}
                    {t("ماه", o.months === 1 ? "month" : "months")} ·{" "}
                    {o.kind === "upgrade"
                      ? t("ارتقا", "Upgrade")
                      : t("اشتراک", "Subscription")}
                  </small>
                </td>
                <td>{usd(o.cap_usd)}</td>
                <td>{usd(o.price_cents / 100)}</td>
                <td>
                  {!o.payment ? (
                    <span className="note">
                      {t("هنوز پرداختی شروع نشده", "Not started")}
                    </span>
                  ) : o.payment.status === "paid" ? (
                    <>
                      <span className="pill success">
                        {t("پرداخت‌شده", "Paid")}
                      </span>
                      <small className="admin-row-note">
                        <bdi dir="ltr">
                          {o.payment.amount} {o.payment.token}
                        </bdi>{" "}
                        {o.payment.explorer_url && (
                          <a
                            href={o.payment.explorer_url}
                            target="_blank"
                            rel="noopener"
                          >
                            {t("تراکنش", "Transaction")}
                          </a>
                        )}
                      </small>
                    </>
                  ) : (
                    <small className="admin-row-note">
                      {t("فاکتور ", "Invoice ")}
                      <bdi dir="ltr">
                        {o.payment.amount} {o.payment.token}
                      </bdi>
                      {o.payment.status === "open"
                        ? t(" · در انتظار پرداخت", " · awaiting payment")
                        : t(" · منقضی", " · expired")}
                    </small>
                  )}
                </td>
                <td>
                  <span
                    className={
                      "order-status " +
                      (o.approval_state === "failed" ? "pending" : o.status)
                    }
                  >
                    {o.status === "pending" && o.approval_state
                      ? labels(o.approval_state) || o.approval_state
                      : labels(o.status)}
                  </span>
                  {o.error_code && (
                    <small className="admin-row-note">
                      {t(
                        "اطلاعات، تعرفه و سرویس صدور را بررسی کنید.",
                        "Check the details, the price and the issuing service.",
                      )}
                    </small>
                  )}
                </td>
                <td>
                  {o.status === "pending" && (
                    <div className="actions">
                      <button
                        className="text-button"
                        disabled={["queued", "running"].includes(
                          o.approval_state || "",
                        )}
                        onClick={() =>
                          setSelection({ order: o, action: "approve" })
                        }
                      >
                        {o.approval_state === "failed"
                          ? t("اصلاح و تلاش مجدد", "Fix and retry")
                          : t("بررسی و تأیید", "Review and approve")}
                      </button>
                      <button
                        className="text-button danger"
                        onClick={() =>
                          setSelection({ order: o, action: "reject" })
                        }
                      >
                        {t("رد درخواست", "Reject")}
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && !data.items.length && (
        <p className="empty-state">
          {t(
            "درخواستی با این وضعیت وجود ندارد.",
            "No requests with this status.",
          )}
        </p>
      )}
      {data && (
        <Pager offset={offset} total={data.total} onChange={setOffset} />
      )}
      <dialog
        ref={dialog}
        id="admin-order-dialog"
        onCancel={(e) => {
          if (busy) e.preventDefault();
          else setSelection(null);
        }}
      >
        <form ref={form} className="dialog-body" onSubmit={submit}>
          <span className="eyebrow">REVIEW REQUEST</span>
          <h2>
            {selection?.action === "reject"
              ? t("رد درخواست", "Reject request")
              : t(
                  "تأیید بررسی و ارسال برای صدور",
                  "Approve and send for issuing",
                )}
          </h2>
          <p>
            {selection?.order.username} ·{" "}
            {selection && usd(selection.order.price_cents / 100)}
          </p>
          {selection?.action === "reject" ? (
            <>
              <label htmlFor="admin-reject-reason">
                {t("دلیل رد درخواست", "Reason for rejection")}
              </label>
              <textarea
                id="admin-reject-reason"
                name="reason"
                minLength={3}
                maxLength={500}
                required
              />
            </>
          ) : (
            <>
              <label htmlFor="admin-payment-ref">
                {t("شناسهٔ رسید پرداخت تأییدشده", "Verified payment reference")}
              </label>
              <input
                id="admin-payment-ref"
                name="payment_ref"
                dir="ltr"
                defaultValue={selection?.order.payment?.tx_ref ?? ""}
                minLength={4}
                maxLength={120}
                required
              />
              {selection?.order.product === "autotrade" && (
                <>
                  <label htmlFor="admin-account-id">
                    {t(
                      "شناسهٔ تأییدشدهٔ حساب، مانند exchange:uid",
                      "Verified account ID, e.g. exchange:uid",
                    )}
                  </label>
                  <input
                    id="admin-account-id"
                    name="account_id"
                    dir="ltr"
                    maxLength={120}
                    required
                  />
                  <label htmlFor="admin-equity">
                    {t("اکوییتی تأییدشده، دلار", "Verified equity, USD")}
                  </label>
                  <input
                    id="admin-equity"
                    name="equity_usd"
                    dir="ltr"
                    type="number"
                    min="0.01"
                    step="0.01"
                    required
                  />
                </>
              )}
              <label className="consent">
                <input
                  id="admin-verified"
                  type="checkbox"
                  checked={verified}
                  onChange={(e) => setVerified(e.target.checked)}
                />
                {t(
                  "پرداخت و، در صورت نیاز، شناسه و سرمایهٔ حساب را بررسی کرده‌ام.",
                  "I have checked the payment and, where needed, the account ID and capital.",
                )}
              </label>
              <p className="note">
                {t(
                  "این اقدام امضای لایسنس را به صف می‌فرستد. تا تکمیل صدور، اشتراک فعال نمی‌شود.",
                  "This queues the license for signing. The subscription is not active until issuing completes.",
                )}
              </p>
            </>
          )}
          <p className="admin-error" role="alert">
            {error}
          </p>
          <div className="dialog-actions">
            <button
              id="admin-submit-review"
              disabled={busy || (selection?.action === "approve" && !verified)}
              type="submit"
            >
              {busy
                ? t("در حال ثبت…", "Saving…")
                : selection?.action === "reject"
                  ? t("رد درخواست", "Reject request")
                  : t("ارسال به صف صدور", "Send to issuing queue")}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => setSelection(null)}
            >
              {t("بازگشت", "Back")}
            </button>
          </div>
        </form>
      </dialog>
    </section>
  );
}

function Pricing({
  api,
  report,
  changed,
}: {
  api: ApiClient;
  report: Report;
  changed: () => void;
}) {
  const { t } = useFormat();
  const [data, setData] = useState<Plans | null>(null),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    let current = true;
    api
      .request<Plans>("/api/admin/pricing")
      .then((d) => {
        if (current) setData(d);
      })
      .catch((e) => {
        if (current) report(e);
      });
    return () => {
      current = false;
    };
  }, [api, report, revision]);
  return (
    <>
      <section className="panel">
        <Heading
          eyebrow="PRICING & SALES"
          title={t("تعرفه و وضعیت فروش", "Prices and sales status")}
          description={t(
            "قیمت‌ها برای هر سرویس مستقل‌اند. ذخیرهٔ پیش‌نویس فروش همان محصول را می‌بندد؛ بازکردن فروش اقدام جداگانه است.",
            "Each service has its own prices. Saving a draft closes sales for that product; opening sales is a separate step.",
          )}
        />
      </section>
      {data?.products.map((product) => (
        <PricingEditor
          key={product.product + product.version}
          product={product}
          api={api}
          report={report}
          done={() => {
            setRevision((n) => n + 1);
            changed();
          }}
        />
      ))}
    </>
  );
}
function PricingEditor({
  product,
  api,
  report,
  done,
}: {
  product: ProductPlan;
  api: ApiClient;
  report: Report;
  done: () => void;
}) {
  const { t, usd } = useFormat();
  const [values, setValues] = useState<Record<string, Record<string, string>>>(
      () =>
        Object.fromEntries(
          product.tiers.map((x) => [
            String(x.cap_usd),
            Object.fromEntries(
              ["1", "3", "6"].map((m) => [
                m,
                x.prices_cents[m] === null
                  ? ""
                  : String(x.prices_cents[m]! / 100),
              ]),
            ),
          ]),
        ),
    ),
    [busy, setBusy] = useState(false),
    [confirmed, setConfirmed] = useState(false);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.request("/api/admin/pricing/" + product.product, "PUT", {
        expected_version: product.version,
        prices: values,
      });
      done();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function sales(open: boolean) {
    if (open && !confirmed) return;
    setBusy(true);
    try {
      await api.request(
        "/api/admin/pricing/" + product.product + (open ? "/open" : "/close"),
        "POST",
        {
          expected_version: product.version,
          ...(open ? { confirmation: "FINAL_PRICES_CONFIRMED" } : {}),
        },
      );
      done();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  const configured = product.tiers.every((t) =>
    ["1", "3", "6"].every((m) => typeof t.prices_cents[m] === "number"),
  );
  return (
    <section className="panel" id={"admin-pricing-" + product.product}>
      <div className="section-heading">
        <h2>{product.label}</h2>
        <span className="order-status">
          {product.sales_enabled
            ? t("فروش باز", "Sales open")
            : t("فروش بسته", "Sales closed")}
        </span>
      </div>
      <form onSubmit={save}>
        <div className="table-wrap">
          <table className="admin-price-table">
            <caption className="sr-only">
              {t("قیمت‌های ", "Prices for ")}
              {product.label}
              {t(" به دلار", " in USD")}
            </caption>
            <thead>
              <tr>
                <th>{t("سقف سرمایه", "Capital cap")}</th>
                {[
                  t("یک‌ماهه", "1 month"),
                  t("سه‌ماهه", "3 months"),
                  t("شش‌ماهه", "6 months"),
                ].map((label) => (
                  <th key={label}>
                    {label} / {t("دلار", "USD")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {product.tiers.map((x) => (
                <tr key={x.cap_usd}>
                  <td>{usd(x.cap_usd)}</td>
                  {["1", "3", "6"].map((m) => (
                    <td key={m}>
                      <input
                        aria-label={
                          product.label +
                          " " +
                          x.cap_usd +
                          " " +
                          m +
                          t(" ماه", " months")
                        }
                        data-cap={x.cap_usd}
                        data-months={m}
                        type="number"
                        dir="ltr"
                        min="0.01"
                        max="200000"
                        step="0.01"
                        value={values[String(x.cap_usd)][m]}
                        disabled={busy}
                        required
                        onChange={(e) =>
                          setValues((v) => ({
                            ...v,
                            [x.cap_usd]: {
                              ...v[x.cap_usd],
                              [m]: e.target.value,
                            },
                          }))
                        }
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button className="secondary" type="submit" disabled={busy}>
          {t("ذخیرهٔ پیش‌نویس و بستن فروش", "Save draft and close sales")}
        </button>
      </form>
      <div className="admin-sales-controls">
        {!product.sales_enabled ? (
          <>
            <label className="consent">
              <input
                type="checkbox"
                checked={confirmed}
                disabled={busy || !configured}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              {t(
                "قیمت‌های ذخیره‌شده نهایی و آمادهٔ فروش هستند.",
                "The saved prices are final and ready for sale.",
              )}
            </label>
            <button
              className="admin-open-sales"
              disabled={busy || !confirmed || !configured}
              onClick={() => sales(true)}
            >
              {t("بازکردن فروش ", "Open sales: ")}
              {product.label}
            </button>
          </>
        ) : (
          <button
            className="secondary danger admin-close-sales"
            disabled={busy}
            onClick={() => sales(false)}
          >
            {t("بستن فروش ", "Close sales: ")}
            {product.label}
          </button>
        )}
      </div>
      <p className="note">
        {t(
          "با تغییر تعرفه، درخواست‌های در انتظار با نسخهٔ قدیمی باید دوباره ثبت شوند. اشتراک‌های پرداخت‌شده با بستن فروش باطل نمی‌شوند.",
          "After a price change, pending requests on the old version must be resubmitted. Closing sales does not cancel paid subscriptions.",
        )}
      </p>
    </section>
  );
}

function Events({ api, report }: { api: ApiClient; report: Report }) {
  const { lang, t } = useFormat();
  const [data, setData] = useState<PageData<EventRow> | null>(null),
    [offset, setOffset] = useState(0);
  useEffect(() => {
    let current = true;
    api
      .request<PageData<EventRow>>("/api/admin/audit?offset=" + offset)
      .then((d) => {
        if (current) setData(d);
      })
      .catch((e) => {
        if (current) report(e);
      });
    return () => {
      current = false;
    };
  }, [api, report, offset]);
  return (
    <section className="panel">
      <Heading
        eyebrow="AUDIT TRAIL"
        title={t("سوابق عملیات مدیریتی", "Admin audit log")}
        description={t(
          "عامل، زمان و نتیجهٔ تغییرات حساس در سامانه ثبت می‌شوند.",
          "Who made each sensitive change, when, and what happened.",
        )}
      />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {[
                t("زمان تهران", "Tehran time"),
                t("عامل", "Actor"),
                t("عملیات", "Action"),
                t("شناسهٔ موضوع", "Target ID"),
              ].map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data?.items.map((e) => (
              <tr key={e.id}>
                <td>{dateTime(e.at, lang)}</td>
                <td>{e.actor || t("اپراتور سرور", "Server operator")}</td>
                <td>
                  {label(EVENTS, e.action, lang) || e.action}
                  {typeof e.details.reason === "string" && (
                    <small className="admin-row-note">{e.details.reason}</small>
                  )}
                </td>
                <td>
                  <bdi>{e.target}</bdi>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && (
        <Pager offset={offset} total={data.total} onChange={setOffset} />
      )}
    </section>
  );
}
