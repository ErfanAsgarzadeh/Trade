"use client";
import type { Cell } from "@/lib/types";
import { localPath, type Lang } from "@/lib/i18n";
import { useLang } from "@/lib/lang";
export function BrandLogo({
  compact = false,
  lang,
}: {
  compact?: boolean;
  lang?: Lang;
}) {
  const context = useLang().lang;
  const current = lang ?? context;
  return (
    <a
      className="logo"
      href={localPath(current, "/")}
      aria-label={current === "en" ? "Avina home" : "Avina، صفحهٔ اصلی"}
    >
      <img
        className="logo-mark"
        src="/portal-assets/avina-mark.png"
        alt=""
        width={44}
        height={24}
      />
      <span className="brand-lockup">
        <span className="brand">AVINA</span>
        {!compact && <span className="brand-parent">by ARTAX</span>}
      </span>
    </a>
  );
}
export function Arrow() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 19 19 5M5 5h14v14" />
    </svg>
  );
}
export function Heading({
  eyebrow,
  title,
  description,
  number,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  number?: string;
}) {
  return (
    <div className="section-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {number && <span className="section-number">{number}</span>}
    </div>
  );
}
export function DataTable({
  headers,
  rows,
  financialColumns = [],
  sideColumns = [],
}: {
  headers: string[];
  rows: Cell[][];
  financialColumns?: number[];
  sideColumns?: number[];
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((v, j) => (
                <td key={j}>
                  {financialColumns.includes(j) ? (
                    <FinancialValue value={v} />
                  ) : sideColumns.includes(j) ? (
                    <span
                      className={
                        String(v).toLowerCase() === "long"
                          ? "financial-profit"
                          : String(v).toLowerCase() === "short"
                            ? "financial-loss"
                            : undefined
                      }
                    >
                      {v ?? "—"}
                    </span>
                  ) : (
                    (v ?? "—")
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <EmptyRows />}
    </div>
  );
}

function EmptyRows() {
  const { t } = useLang();
  return <p className="note">{t("داده‌ای برای نمایش وجود ندارد.", "Nothing to show yet.")}</p>;
}

/** Presentation only: preserve the source precision, add an explicit signed status. */
export function FinancialValue({ value }: { value: Cell }) {
  const { t } = useLang();
  const numeric =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim() !== ""
        ? Number(value)
        : NaN;
  if (!Number.isFinite(numeric)) return <span>{value ?? "—"}</span>;
  const status = numeric > 0 ? "profit" : numeric < 0 ? "loss" : "neutral";
  return (
    <bdi
      className={"financial-value financial-" + status}
      aria-label={
        (numeric > 0
          ? t("سود", "Profit")
          : numeric < 0
            ? t("زیان", "Loss")
            : t("بدون تغییر", "No change")) +
        ": " +
        String(value)
      }
    >
      {numeric > 0 && !String(value).trimStart().startsWith("+") ? "+" : ""}
      {value}
    </bdi>
  );
}
