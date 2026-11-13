"use client";
import { useEffect, useRef, useState } from "react";
import { ApiClient, errorText } from "@/lib/api";
import type { Plans, ProductPlan, Product } from "@/lib/types";
import { faDate, faNumber, usd } from "@/lib/format";
import { Heading } from "./shared";
import AdminBlog from "./admin-blog";

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
  ["overview", "نمای کلی"],
  ["orders", "کارتابل درخواست‌ها"],
  ["users", "کاربران"],
  ["pricing", "قیمت و فروش"],
  ["blog", "بلاگ"],
  ["audit", "سوابق عملیات"],
] as const;
const labels: Record<string, string> = {
  pending: "در انتظار بررسی",
  approved: "صادرشده",
  cancelled: "لغوشده",
  rejected: "ردشده",
  queued: "در صف صدور",
  running: "در حال صدور",
  failed: "صدور ناموفق",
  completed: "صادرشده",
};
const eventLabels: Record<string, string> = {
  role_changed: "تغییر نقش از مسیر سرور",
  user_disabled: "تعلیق دسترسی کاربر",
  user_enabled: "فعال‌سازی کاربر",
  order_rejected: "رد درخواست",
  approval_requested: "ارسال به صف صدور",
  license_issued: "صدور لایسنس",
  issuance_failed: "خطای صدور",
  pricing_saved: "ذخیرهٔ تعرفه",
  sales_closed: "بستن فروش",
  blog_created: "ساخت مقاله",
  blog_updated: "ویرایش مقاله",
  blog_deleted: "حذف مقاله",
};
function Pager({
  offset,
  total,
  onChange,
}: {
  offset: number;
  total: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="admin-pagination">
      <span>{faNumber(total)} مورد</span>
      <button
        className="secondary small"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - 30))}
      >
        قبلی
      </button>
      <button
        className="secondary small"
        disabled={offset + 30 >= total}
        onClick={() => onChange(offset + 30)}
      >
        بعدی
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
          <h1>کارتابل مدیریت سامانه</h1>
          <p>کاربران، درخواست‌ها و فروش؛ با دسترسی اختصاصی مدیر.</p>
          <span className="pill admin-role">مدیر سامانه</span>
        </div>
        <a className="button secondary" href="/dashboard/">
          بازگشت به پنل مشتری ←
        </a>
      </section>
      <div className="admin-layout">
        <nav className="admin-nav" aria-label="بخش‌های مدیریت">
          {tabs.map(([key, label]) => (
            <button
              key={key}
              id={"admin-tab-" + key}
              className={tab === key ? "active" : ""}
              aria-current={tab === key ? "page" : undefined}
              onClick={() => setTab(key)}
            >
              {label}
              <span aria-hidden="true">←</span>
            </button>
          ))}
        </nav>
        <div className="admin-content">
          {tab === "overview" && (
            <>
              <div className="stat-grid">
                {[
                  ["users", "کل کاربران"],
                  ["pending_orders", "درخواست در انتظار"],
                  ["issued_licenses", "لایسنس صادرشده"],
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
                        ? "تعداد کل صدور؛ شامل دوره‌های منقضی"
                        : "اطلاعات پایگاه دادهٔ سامانه"}
                    </p>
                  </article>
                ))}
              </div>
              <section className="panel">
                <Heading eyebrow="OPERATIONS" title="وضعیت سرویس‌ها" />
                <div className="admin-overview-services">
                  <article>
                    <h3>صف صدور لایسنس</h3>
                    <strong>
                      {data ? faNumber(data.counts.queued_approvals) : "—"}
                    </strong>
                    <p>در صف یا در حال امضا</p>
                    <p className="note">
                      {data?.issuer_last_seen
                        ? "آخرین فعالیت سرویس: " +
                          new Date(data.issuer_last_seen * 1000).toLocaleString(
                            "fa-IR",
                            { timeZone: "Asia/Tehran" },
                          )
                        : "سرویس صدور هنوز فعالیتی ثبت نکرده است."}
                    </p>
                  </article>
                  <article>
                    <h3>نیازمند رسیدگی</h3>
                    <strong>
                      {data ? faNumber(data.counts.failed_approvals) : "—"}
                    </strong>
                    <p>درخواست‌های صدور ناموفق</p>
                    <button
                      className="text-button"
                      onClick={() => setTab("orders")}
                    >
                      مشاهدهٔ درخواست‌ها ←
                    </button>
                  </article>
                </div>
                <p className="note">
                  تأیید مدیر ابتدا در صف ثبت می‌شود. صدور نهایی به سرویس امضای
                  جداگانه نیاز دارد؛ کلید خصوصی وارد مرورگر نمی‌شود.
                </p>
              </section>
              <section className="panel">
                <Heading eyebrow="SALES STATUS" title="وضعیت فروش محصولات" />
                {data?.pricing.products.map((p) => (
                  <div key={p.product} className="admin-status-row">
                    <strong>{p.label}</strong>
                    <span
                      className={
                        "order-status " +
                        (p.sales_enabled ? "approved" : "cancelled")
                      }
                    >
                      {p.sales_enabled ? "فروش باز" : "فروش بسته"}
                    </span>
                    <button
                      className="text-button"
                      onClick={() => setTab("pricing")}
                    >
                      مدیریت تعرفه ←
                    </button>
                  </div>
                ))}
                <button className="secondary" onClick={changed}>
                  به‌روزرسانی وضعیت ↻
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
          ? "دسترسی این کاربر فعال شود؟"
          : "دسترسی این کاربر به پنل تعلیق و نشست‌هایش بسته شود؟ این کار پوزیشن‌های ربات را نمی‌بندد.",
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
        title="مدیریت کاربران"
        description="تغییر وضعیت دسترسی به پنل؛ نقش مدیر فقط از مسیر سرور تغییر می‌کند."
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
          جست‌وجوی نام کاربری
        </label>
        <input
          id="admin-user-search"
          dir="ltr"
          value={search}
          maxLength={40}
          placeholder="username"
          onChange={(e) => setSearch(e.target.value)}
        />
        <button type="submit" className="secondary">
          جست‌وجو
        </button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {[
                "نام کاربری",
                "نقش",
                "دسترسی",
                "اتصال",
                "اجرای اختصاصی",
                "عملیات",
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
                <td>{u.role === "admin" ? "مدیر" : "مشتری"}</td>
                <td>{u.disabled ? "تعلیق‌شده" : "فعال"}</td>
                <td>{u.has_connection ? "ثبت‌شده" : "ندارد"}</td>
                <td>{u.has_runtime ? "متصل" : "متصل نیست"}</td>
                <td>
                  {u.role === "admin" ? (
                    <span className="note">مدیریت از مسیر سرور</span>
                  ) : (
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() => toggle(u)}
                    >
                      {u.disabled ? "فعال‌سازی" : "تعلیق دسترسی"}
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
        تعلیق ورود به پنل، جایگزین توقف ربات یا ابطال لایسنس نصب‌شده نیست.
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
        title="کارتابل درخواست‌های خرید"
        description="پرداخت و اطلاعات حساب را مستقل بررسی کنید؛ تأیید، درخواست امضا را در صف قرار می‌دهد."
      />
      <div className="admin-filters">
        <label htmlFor="admin-order-filter">وضعیت درخواست</label>
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
              {s === "all" ? "همه" : labels[s]}
            </option>
          ))}
        </select>
        <button
          id="admin-refresh-orders"
          className="secondary"
          onClick={() => setRevision((n) => n + 1)}
        >
          به‌روزرسانی ↻
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {[
                "کاربر / پیگیری",
                "محصول / دوره",
                "سرمایه",
                "مبلغ",
                "وضعیت",
                "عملیات",
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
                  {o.product === "signals" ? "فقط سیگنال" : "معاملهٔ خودکار"}
                  <small className="admin-row-note">
                    {faNumber(o.months)} ماه ·{" "}
                    {o.kind === "upgrade" ? "ارتقا" : "اشتراک"}
                  </small>
                </td>
                <td>{usd(o.cap_usd)}</td>
                <td>{usd(o.price_cents / 100)}</td>
                <td>
                  <span
                    className={
                      "order-status " +
                      (o.approval_state === "failed" ? "pending" : o.status)
                    }
                  >
                    {o.status === "pending" && o.approval_state
                      ? labels[o.approval_state] || o.approval_state
                      : labels[o.status]}
                  </span>
                  {o.error_code && (
                    <small className="admin-row-note">
                      اطلاعات، تعرفه و سرویس صدور را بررسی کنید.
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
                          ? "اصلاح و تلاش مجدد"
                          : "بررسی و تأیید"}
                      </button>
                      <button
                        className="text-button danger"
                        onClick={() =>
                          setSelection({ order: o, action: "reject" })
                        }
                      >
                        رد درخواست
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
        <p className="empty-state">درخواستی با این وضعیت وجود ندارد.</p>
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
              ? "رد درخواست"
              : "تأیید بررسی و ارسال برای صدور"}
          </h2>
          <p>
            {selection?.order.username} ·{" "}
            {selection && usd(selection.order.price_cents / 100)}
          </p>
          {selection?.action === "reject" ? (
            <>
              <label htmlFor="admin-reject-reason">دلیل رد درخواست</label>
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
                شناسهٔ رسید پرداخت تأییدشده
              </label>
              <input
                id="admin-payment-ref"
                name="payment_ref"
                dir="ltr"
                minLength={4}
                maxLength={120}
                required
              />
              {selection?.order.product === "autotrade" && (
                <>
                  <label htmlFor="admin-account-id">
                    شناسهٔ تأییدشدهٔ حساب، مانند exchange:uid
                  </label>
                  <input
                    id="admin-account-id"
                    name="account_id"
                    dir="ltr"
                    maxLength={120}
                    required
                  />
                  <label htmlFor="admin-equity">اکوییتی تأییدشده، دلار</label>
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
                پرداخت و، در صورت نیاز، شناسه و سرمایهٔ حساب را بررسی کرده‌ام.
              </label>
              <p className="note">
                این اقدام امضای لایسنس را به صف می‌فرستد. تا تکمیل صدور، اشتراک
                فعال نمی‌شود.
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
                ? "در حال ثبت…"
                : selection?.action === "reject"
                  ? "رد درخواست"
                  : "ارسال به صف صدور"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => setSelection(null)}
            >
              بازگشت
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
          title="تعرفه و وضعیت فروش"
          description="قیمت‌ها برای هر سرویس مستقل‌اند. ذخیرهٔ پیش‌نویس فروش همان محصول را می‌بندد؛ بازکردن فروش اقدام جداگانه است."
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
  const [values, setValues] = useState<Record<string, Record<string, string>>>(
      () =>
        Object.fromEntries(
          product.tiers.map((t) => [
            String(t.cap_usd),
            Object.fromEntries(
              ["1", "3", "6"].map((m) => [
                m,
                t.prices_cents[m] === null
                  ? ""
                  : String(t.prices_cents[m]! / 100),
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
          {product.sales_enabled ? "فروش باز" : "فروش بسته"}
        </span>
      </div>
      <form onSubmit={save}>
        <div className="table-wrap">
          <table className="admin-price-table">
            <caption className="sr-only">
              قیمت‌های {product.label} به دلار
            </caption>
            <thead>
              <tr>
                <th>سقف سرمایه</th>
                {["یک‌ماهه", "سه‌ماهه", "شش‌ماهه"].map((label) => (
                  <th key={label}>{label} / دلار</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {product.tiers.map((t) => (
                <tr key={t.cap_usd}>
                  <td>{usd(t.cap_usd)}</td>
                  {["1", "3", "6"].map((m) => (
                    <td key={m}>
                      <input
                        aria-label={
                          product.label + " " + t.cap_usd + " " + m + " ماه"
                        }
                        data-cap={t.cap_usd}
                        data-months={m}
                        type="number"
                        dir="ltr"
                        min="0.01"
                        max="200000"
                        step="0.01"
                        value={values[String(t.cap_usd)][m]}
                        disabled={busy}
                        required
                        onChange={(e) =>
                          setValues((v) => ({
                            ...v,
                            [t.cap_usd]: {
                              ...v[t.cap_usd],
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
          ذخیرهٔ پیش‌نویس و بستن فروش
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
              قیمت‌های ذخیره‌شده نهایی و آمادهٔ فروش هستند.
            </label>
            <button
              className="admin-open-sales"
              disabled={busy || !confirmed || !configured}
              onClick={() => sales(true)}
            >
              بازکردن فروش {product.label}
            </button>
          </>
        ) : (
          <button
            className="secondary danger admin-close-sales"
            disabled={busy}
            onClick={() => sales(false)}
          >
            بستن فروش {product.label}
          </button>
        )}
      </div>
      <p className="note">
        با تغییر تعرفه، درخواست‌های در انتظار با نسخهٔ قدیمی باید دوباره ثبت
        شوند. اشتراک‌های پرداخت‌شده با بستن فروش باطل نمی‌شوند.
      </p>
    </section>
  );
}

function Events({ api, report }: { api: ApiClient; report: Report }) {
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
        title="سوابق عملیات مدیریتی"
        description="عامل، زمان و نتیجهٔ تغییرات حساس در سامانه ثبت می‌شوند."
      />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {["زمان تهران", "عامل", "عملیات", "شناسهٔ موضوع"].map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data?.items.map((e) => (
              <tr key={e.id}>
                <td>
                  {new Date(e.at * 1000).toLocaleString("fa-IR", {
                    timeZone: "Asia/Tehran",
                  })}
                </td>
                <td>{e.actor || "اپراتور سرور"}</td>
                <td>
                  {eventLabels[e.action] || e.action}
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
