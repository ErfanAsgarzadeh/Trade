"use client";
import { useEffect, useState } from "react";
import { ApiClient, errorText } from "@/lib/api";
import { useLang } from "@/lib/lang";

type Status = {
  directory_found: boolean;
  hidden: boolean;
  runtime_updated: string | null;
  days: number;
  last_snapshot: string | null;
  available: boolean;
};

/** Data-source status of the public forward test and the switch that hides the public page. */
export default function AdminForward({ api }: { api: ApiClient }) {
  const { t } = useLang();
  const [status, setStatus] = useState<Status | null>(null),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let current = true;
    api
      .request<Status>("/api/admin/forward-test")
      .then((v) => current && setStatus(v))
      .catch((e) => current && setMessage(errorText(e)));
    return () => {
      current = false;
    };
  }, [api]);
  const toggle = async () => {
    if (!status) return;
    setBusy(true);
    setMessage("");
    try {
      setStatus(
        await api.request<Status>("/api/admin/forward-test", "PUT", {
          hidden: !status.hidden,
        }),
      );
    } catch (e) {
      setMessage(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const yes = t("بله", "Yes"),
    no = t("خیر", "No");
  return (
    <section
      className="panel"
      id="admin-forward-test"
      aria-labelledby="admin-forward-title"
    >
      <h2 id="admin-forward-title">{t("فوروارد تست", "Forward test")}</h2>
      {status ? (
        <>
          <dl className="forward-admin">
            <div>
              <dt>{t("پوشهٔ داده پیدا شد", "Data directory found")}</dt>
              <dd>{status.directory_found ? yes : no}</dd>
            </div>
            <div>
              <dt>{t("آخرین به‌روزرسانی اجرا", "Last runtime update")}</dt>
              <dd>{status.runtime_updated ?? "-"}</dd>
            </div>
            <div>
              <dt>{t("روزهای داده", "Days of data")}</dt>
              <dd>{status.days}</dd>
            </div>
            <div>
              <dt>{t("آخرین ذخیرهٔ روزانه", "Last daily snapshot")}</dt>
              <dd>{status.last_snapshot ?? "-"}</dd>
            </div>
            <div>
              <dt>{t("نمایش عمومی", "Public page")}</dt>
              <dd>
                {status.hidden ? t("پنهان", "Hidden") : t("نمایان", "Visible")}
              </dd>
            </div>
          </dl>
          <button
            type="button"
            className="secondary"
            onClick={toggle}
            disabled={busy}
          >
            {status.hidden
              ? t("نمایش صفحهٔ عمومی", "Show the public page")
              : t("پنهان‌کردن صفحهٔ عمومی", "Hide the public page")}
          </button>
        </>
      ) : (
        <p>{t("در حال بارگذاری...", "Loading...")}</p>
      )}
      {message && (
        <p role="alert" className="error">
          {message}
        </p>
      )}
    </section>
  );
}
