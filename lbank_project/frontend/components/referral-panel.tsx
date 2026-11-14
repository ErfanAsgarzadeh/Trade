"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiClient, ApiError, errorText } from "@/lib/api";
import { dateTime, money, num, percent } from "@/lib/format";
import { useLang } from "@/lib/lang";
import {
  offerText,
  rewardText,
  type ProgramConfig,
  type RefereeOffer,
} from "@/lib/referral";
import { Heading } from "./shared";

interface Reward {
  id: string;
  kind: "credit" | "coupon";
  value: number;
  remaining: number;
  source: "referral" | "admin";
  referee: string;
  note: string;
  created: number;
  available_at: number;
  expires: number | null;
  state: "available" | "pending" | "used" | "expired" | "void";
}
interface Account {
  enabled: boolean;
  code?: string;
  program?: ProgramConfig | null;
  referred?: { code: string; offer: RefereeOffer | null; used: number } | null;
  can_attach?: boolean;
  stats?: { signups: number; paying: number; earned_cents: number };
  balance_cents?: number;
  pending_cents?: number;
  coupons?: { percent: number; expires: number | null }[];
  rewards?: Reward[];
}

const STATES: Record<Reward["state"], [string, string]> = {
  available: ["قابل استفاده", "Available"],
  pending: ["در دورهٔ انتظار", "On hold"],
  used: ["استفاده‌شده", "Used"],
  expired: ["منقضی", "Expired"],
  void: ["باطل‌شده", "Voided"],
};

/** Invite friends: personal code and link, what the program pays, earned credit and coupons. */
export default function ReferralPanel({
  api,
  notify,
  report,
  onEnabled,
}: {
  api: ApiClient;
  notify: (s: string) => void;
  report: (e: unknown) => void;
  onEnabled?: (enabled: boolean) => void;
}) {
  const { lang, t, path } = useLang();
  const [data, setData] = useState<Account | null>(null),
    [editing, setEditing] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const load = useCallback(
    () =>
      api
        .request<Account>("/api/me/referral")
        .then((d) => {
          setData(d);
          onEnabled?.(d.enabled);
        })
        .catch(report),
    [api, report, onEnabled],
  );
  useEffect(() => {
    void load();
  }, [load]);
  if (!data?.enabled || !data.code) return null;
  const usd = (cents: number) => money(cents / 100, lang);
  const link = `${window.location.origin}${path("/register/")}?ref=${data.code}`;
  const offer = offerText(data.program?.referee, lang);
  const reward = rewardText(data.program?.referrer, lang);
  const share = t(
    `با کد دعوت من در آوینا ثبت‌نام کن${offer ? " و " + offer + " بگیر" : ""}: `,
    `Join Avina with my invite code${offer ? " and get " + offer : ""}: `,
  );
  const copy = (text: string, done: string) => {
    void navigator.clipboard?.writeText(text);
    notify(done);
  };
  async function submit(
    event: React.FormEvent<HTMLFormElement>,
    route: string,
    method: "PUT" | "POST",
    done: string,
  ) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code") || "");
    setBusy(true);
    setError("");
    try {
      await api.request(route, method, { code });
      setEditing(false);
      notify(done);
      await load();
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? t(
              "این کد قابل استفاده نیست؛ ممکن است تکراری باشد، مال خودتان باشد یا مهلت افزودن کد گذشته باشد.",
              "This code can't be used: it may be taken, your own, or the time to add a code has passed.",
            )
          : e instanceof ApiError && e.status === 422
            ? t(
                "کد معتبر نیست. از حروف انگلیسی، عدد و خط تیره استفاده کنید.",
                "That code is not valid. Use letters, numbers and dashes.",
              )
            : errorText(e),
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel referral-panel" id="referral-section">
      <Heading
        eyebrow="INVITE FRIENDS"
        title={t("دعوت دوستان", "Invite friends")}
        number="REFERRAL"
      />
      {data.program &&
      (data.program.referee.type !== "none" ||
        data.program.referrer.type !== "none") ? (
        <div className="referral-offer">
          {offer && (
            <p>
              <strong>{t("دوست شما: ", "Your friend: ")}</strong>
              {offer}
            </p>
          )}
          {reward.text && (
            <p>
              <strong>{t("شما: ", "You: ")}</strong>
              {reward.text}
            </p>
          )}
          {reward.tiers.length > 0 && (
            <ul>
              {reward.tiers.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="note">
          {t(
            "در حال حاضر برنامهٔ پاداش فعالی نیست، اما دعوت‌های شما ثبت می‌شود.",
            "There is no active reward program right now, but your invites are still recorded.",
          )}
        </p>
      )}
      <div className="referral-code">
        <div>
          <span className="field-hint">
            {t("کد دعوت شما", "Your invite code")}
          </span>
          <strong dir="ltr" id="referral-code">
            {data.code}
          </strong>
        </div>
        <div className="referral-actions">
          <button
            type="button"
            className="secondary small"
            onClick={() => copy(data.code!, t("کد کپی شد.", "Code copied."))}
          >
            {t("کپی کد", "Copy code")}
          </button>
          <button
            type="button"
            className="small"
            onClick={() =>
              copy(link, t("لینک دعوت کپی شد.", "Invite link copied."))
            }
          >
            {t("کپی لینک دعوت", "Copy invite link")}
          </button>
          <button
            type="button"
            className="text-button"
            onClick={() => setEditing((v) => !v)}
          >
            {t("کد دلخواه", "Custom code")}
          </button>
        </div>
      </div>
      <p className="referral-link" dir="ltr">
        {link}
      </p>
      <div className="referral-share">
        <a
          className="button secondary small"
          href={`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(share)}`}
          target="_blank"
          rel="noopener"
        >
          Telegram
        </a>
        <a
          className="button secondary small"
          href={`https://wa.me/?text=${encodeURIComponent(share + link)}`}
          target="_blank"
          rel="noopener"
        >
          WhatsApp
        </a>
        <a
          className="button secondary small"
          href={`https://twitter.com/intent/tweet?text=${encodeURIComponent(share)}&url=${encodeURIComponent(link)}`}
          target="_blank"
          rel="noopener"
        >
          X
        </a>
      </div>
      {editing && (
        <form
          className="inline-form"
          onSubmit={(e) =>
            submit(
              e,
              "/api/me/referral/code",
              "PUT",
              t(
                "کد دعوت جدید ثبت شد. لینک‌های قبلی هم کار می‌کنند.",
                "New invite code saved. Earlier links still work.",
              ),
            )
          }
        >
          <label htmlFor="custom-code">
            {t(
              "کد دلخواه (۴ تا ۲۴ حرف انگلیسی یا عدد)",
              "Custom code (4–24 letters or digits)",
            )}
          </label>
          <div className="input-row">
            <input
              id="custom-code"
              name="code"
              dir="ltr"
              minLength={4}
              maxLength={24}
              pattern="[A-Za-z0-9][A-Za-z0-9\-]{3,23}"
              required
            />
            <button disabled={busy}>{t("ذخیره", "Save")}</button>
          </div>
        </form>
      )}
      <div className="stat-grid referral-stats">
        <article className="stat-card">
          <div className="stat-label">
            {t("ثبت‌نام با کد شما", "Signed up with your code")}
          </div>
          <strong id="referral-signups">
            {num(data.stats?.signups ?? 0, lang)}
          </strong>
          <p>
            {t("دوستان خریدار: ", "Paying friends: ")}
            {num(data.stats?.paying ?? 0, lang)}
          </p>
        </article>
        <article className="stat-card">
          <div className="stat-label">
            {t("اعتبار قابل استفاده", "Available credit")}
          </div>
          <strong id="referral-balance">{usd(data.balance_cents ?? 0)}</strong>
          <p>
            {data.pending_cents
              ? t("در انتظار: ", "On hold: ") + usd(data.pending_cents)
              : t(
                  "در خرید بعدی خودکار کم می‌شود",
                  "Applied automatically to your next purchase",
                )}
          </p>
        </article>
        <article className="stat-card">
          <div className="stat-label">
            {t("کوپن‌های تخفیف", "Discount coupons")}
          </div>
          <strong>{num(data.coupons?.length ?? 0, lang)}</strong>
          <p>
            {data.coupons?.length
              ? data.coupons.map((c) => percent(c.percent, lang, 0)).join(" · ")
              : t("مجموع اعتبار دریافتی: ", "Total credit earned: ") +
                usd(data.stats?.earned_cents ?? 0)}
          </p>
        </article>
      </div>
      {data.referred ? (
        <p className="note">
          {t("شما با کد ", "You joined with code ")}
          <bdi dir="ltr">{data.referred.code}</bdi>
          {t(" ثبت‌نام کرده‌اید", "")}
          {data.referred.offer && data.referred.offer.type !== "none"
            ? t(" و ", "; ") +
              offerText(data.referred.offer, lang) +
              t(" برای شما فعال است.", " applies to you.")
            : t(".", ".")}
        </p>
      ) : (
        data.can_attach && (
          <form
            className="inline-form"
            onSubmit={(e) =>
              submit(
                e,
                "/api/me/referral/attach",
                "POST",
                t("کد دعوت ثبت شد.", "Invite code applied."),
              )
            }
          >
            <label htmlFor="attach-code">
              {t("کد دعوت دوستتان را دارید؟", "Have a friend's invite code?")}
            </label>
            <div className="input-row">
              <input
                id="attach-code"
                name="code"
                dir="ltr"
                maxLength={24}
                required
              />
              <button disabled={busy} className="secondary">
                {t("ثبت کد", "Apply")}
              </button>
            </div>
          </form>
        )
      )}
      {error && (
        <p className="note warning-text" role="alert">
          {error}
        </p>
      )}
      {!!data.rewards?.length && (
        <div className="table-wrap">
          <table id="referral-rewards">
            <thead>
              <tr>
                <th>{t("پاداش", "Reward")}</th>
                <th>{t("بابت", "For")}</th>
                <th>{t("تاریخ", "Date")}</th>
                <th>{t("وضعیت", "Status")}</th>
              </tr>
            </thead>
            <tbody>
              {data.rewards.map((r) => (
                <tr key={r.id}>
                  <td>
                    {r.kind === "credit"
                      ? usd(r.value) +
                        (r.remaining > 0 && r.remaining < r.value
                          ? t(" (مانده ", " (left ") + usd(r.remaining) + ")"
                          : "")
                      : t("کوپن ", "Coupon ") + percent(r.value / 100, lang, 0)}
                  </td>
                  <td>
                    {r.source === "admin"
                      ? r.note || t("هدیهٔ آوینا", "Gift from Avina")
                      : t("خرید ", "Purchase by ") + r.referee}
                  </td>
                  <td>{dateTime(r.created, lang)}</td>
                  <td>
                    <span className={"order-status " + r.state}>
                      {STATES[r.state][lang === "en" ? 1 : 0]}
                    </span>
                    {r.state === "pending" && (
                      <small> · {dateTime(r.available_at, lang)}</small>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="note">
        {t(
          "پاداش فقط بعد از خرید و تأیید پرداخت دوستتان ثبت می‌شود. حساب‌های ساختگی یا دعوت از خودتان پاداش ندارد.",
          "Rewards are recorded only after your friend's payment is confirmed. Fake accounts or self-invites earn nothing.",
        )}
      </p>
    </section>
  );
}
