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
  type ReferrerReward,
} from "@/lib/referral";
import { Heading } from "./shared";

interface Program {
  id: string;
  name: string;
  config: ProgramConfig;
  active: boolean;
  is_default: boolean;
  starts: number | null;
  ends: number | null;
  live: boolean;
  referrals: number;
  rewards: number;
  credit_cents: number;
}
interface Code {
  code: string;
  label: string;
  active: boolean;
  max_uses: number;
  uses: number;
  personal: boolean;
  owner: string | null;
  program_id: string | null;
  paying: number;
}
interface Overview {
  settings: {
    enabled: boolean;
    attach_days: number;
    credit_max_percent: number;
  };
  programs: Program[];
  codes: Code[];
  top: {
    username: string;
    signups: number;
    paying: number;
    credit_cents: number;
  }[];
  rewards: {
    id: string;
    username: string;
    kind: "credit" | "coupon";
    value: number;
    source: string;
    note: string;
    referee: string | null;
    created: number;
    state: string;
  }[];
  totals: {
    referrals: number;
    paying: number;
    discount_cents: number;
    credit_cents: number;
    outstanding_cents: number;
  };
}
interface Draft {
  id: string | null;
  name: string;
  active: boolean;
  is_default: boolean;
  starts: string;
  ends: string;
  referee: RefereeOffer;
  referrer: ReferrerReward;
}

const BOTH = ["autotrade", "signals"];
const referee = (o: Partial<RefereeOffer> = {}): RefereeOffer => ({
  type: "none",
  value: 0,
  purchases: 1,
  window_days: 0,
  min_order_usd: 0,
  products: BOTH,
  ...o,
});
const referrer = (o: Partial<ReferrerReward> = {}): ReferrerReward => ({
  type: "none",
  value: 0,
  trigger: "first",
  max_per_referee: 0,
  hold_days: 0,
  expiry_days: 0,
  max_total_usd: 0,
  min_order_usd: 0,
  products: BOTH,
  tiers: [],
  ...o,
});
const blank = (): Draft => ({
  id: null,
  name: "",
  active: true,
  is_default: true,
  starts: "",
  ends: "",
  referee: referee(),
  referrer: referrer(),
});

/** Ready-made programs; every field stays editable after choosing one. */
const PRESETS: { fa: string; en: string; make: () => Partial<Draft> }[] = [
  {
    fa: "تخفیف دوطرفه",
    en: "Two-sided discount",
    make: () => ({
      name: "Two-sided",
      referee: referee({ type: "percent", value: 10 }),
      referrer: referrer({ type: "coupon", value: 10 }),
    }),
  },
  {
    fa: "تخفیف دوست + اعتبار دعوت‌کننده",
    en: "Friend discount + inviter credit",
    make: () => ({
      name: "Give and get",
      referee: referee({ type: "percent", value: 10 }),
      referrer: referrer({ type: "credit", value: 20 }),
    }),
  },
  {
    fa: "کمیسیون همکاری در فروش",
    en: "Affiliate commission",
    make: () => ({
      name: "Affiliate",
      referrer: referrer({
        type: "commission",
        value: 20,
        trigger: "every",
        hold_days: 14,
      }),
    }),
  },
  {
    fa: "پاداش پلکانی",
    en: "Tiered rewards",
    make: () => ({
      name: "Tiered",
      referee: referee({ type: "percent", value: 10 }),
      referrer: referrer({
        type: "credit",
        value: 10,
        tiers: [
          { referrals: 5, value: 20 },
          { referrals: 10, value: 30 },
        ],
      }),
    }),
  },
  {
    fa: "کمپین تخفیف (بدون دعوت‌کننده)",
    en: "Discount campaign (no inviter)",
    make: () => ({
      name: "Campaign",
      is_default: false,
      referee: referee({
        type: "fixed",
        value: 20,
        purchases: 0,
        window_days: 30,
      }),
    }),
  },
];

const day = (seconds: number | null) =>
  seconds ? new Date(seconds * 1000).toISOString().slice(0, 10) : "";
const seconds = (date: string) =>
  date ? Math.floor(new Date(date + "T00:00:00Z").getTime() / 1000) : null;

export default function AdminReferrals({
  api,
  report,
}: {
  api: ApiClient;
  report: (e: unknown) => void;
}) {
  const { lang, t } = useLang();
  const [data, setData] = useState<Overview | null>(null),
    [draft, setDraft] = useState<Draft | null>(null),
    [busy, setBusy] = useState(false),
    [note, setNote] = useState("");
  const usd = (cents: number) => money(cents / 100, lang);
  const load = useCallback(
    () =>
      api.request<Overview>("/api/admin/referrals").then(setData).catch(report),
    [api, report],
  );
  useEffect(() => {
    void load();
  }, [load]);

  async function call(
    route: string,
    method: string,
    body: unknown,
    done: string,
  ) {
    setBusy(true);
    setNote("");
    try {
      await api.request(route, method, body);
      setNote(done);
      await load();
      return true;
    } catch (e) {
      setNote(
        e instanceof ApiError && e.status === 409
          ? t(
              "با وضعیت فعلی سازگار نیست (کد تکراری است یا برنامه در حال استفاده است).",
              "Conflicts with the current state (the code is taken or the program is in use).",
            )
          : e instanceof ApiError && e.status === 422
            ? t(
                "مقادیر را بررسی کنید: درصدها تا ۱۰۰، مبالغ مثبت، نام کاربری موجود و کد با حروف انگلیسی و عدد.",
                "Check the values: percentages up to 100, positive amounts, an existing username and a code of letters and digits.",
              )
            : errorText(e),
      );
      return false;
    } finally {
      setBusy(false);
    }
  }
  const form = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    return new FormData(e.currentTarget);
  };

  async function saveProgram(e: React.FormEvent) {
    e.preventDefault();
    if (!draft) return;
    const body = {
      name: draft.name,
      active: draft.active,
      is_default: draft.is_default,
      starts: seconds(draft.starts),
      ends: seconds(draft.ends),
      config: { referee: draft.referee, referrer: draft.referrer },
    };
    const ok = await call(
      draft.id
        ? "/api/admin/referrals/programs/" + draft.id
        : "/api/admin/referrals/programs",
      draft.id ? "PUT" : "POST",
      body,
      t("برنامه ذخیره شد.", "Program saved."),
    );
    if (ok) setDraft(null);
  }

  if (!data) return <section className="panel" id="admin-referrals" />;
  const programName = (id: string | null) =>
    id
      ? (data.programs.find((p) => p.id === id)?.name ?? "—")
      : t("برنامهٔ پیش‌فرض", "Default program");
  const setEe = (patch: Partial<RefereeOffer>) =>
    setDraft((d) => d && { ...d, referee: { ...d.referee, ...patch } });
  const setEr = (patch: Partial<ReferrerReward>) =>
    setDraft((d) => d && { ...d, referrer: { ...d.referrer, ...patch } });
  const numberInput = (
    id: string,
    label: string,
    value: number,
    onChange: (v: number) => void,
    props: React.InputHTMLAttributes<HTMLInputElement> = {},
  ) => (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        dir="ltr"
        min={0}
        step="any"
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => onChange(Number(e.target.value))}
        {...props}
      />
    </div>
  );
  const products = (
    value: string[],
    onChange: (v: string[]) => void,
    id: string,
  ) => (
    <fieldset className="referral-products">
      <legend>{t("محصولات", "Products")}</legend>
      {[
        ["autotrade", t("معاملهٔ خودکار", "Automated trading")],
        ["signals", t("سیگنال", "Signals")],
      ].map(([p, label]) => (
        <label key={p} className="consent">
          <input
            id={id + "-" + p}
            type="checkbox"
            checked={value.includes(p)}
            onChange={(e) =>
              onChange(
                e.target.checked ? [...value, p] : value.filter((x) => x !== p),
              )
            }
          />
          {label}
        </label>
      ))}
    </fieldset>
  );

  return (
    <section className="panel" id="admin-referrals">
      <Heading
        eyebrow="REFERRALS"
        title={t("دعوت و پاداش", "Referrals and rewards")}
        description={t(
          "هر کاربر یک کد دعوت دارد. برنامه‌ها تعیین می‌کنند دوستِ دعوت‌شده چه تخفیفی بگیرد و دعوت‌کننده چه پاداشی؛ پاداش فقط بعد از تأیید خرید ثبت می‌شود.",
          "Every customer has an invite code. Programs decide the invited friend's discount and the inviter's reward; rewards are granted only after an approved purchase.",
        )}
      />
      <div className="admin-overview-services">
        <article>
          <h3>{t("ثبت‌نام با دعوت", "Referred sign-ups")}</h3>
          <strong>{num(data.totals.referrals, lang)}</strong>
          <p className="note">
            {t("خریدار: ", "Paying: ")}
            {num(data.totals.paying, lang)}
          </p>
        </article>
        <article>
          <h3>{t("تخفیف داده‌شده", "Discounts given")}</h3>
          <strong>{usd(data.totals.discount_cents)}</strong>
        </article>
        <article>
          <h3>{t("اعتبار پاداش", "Reward credit")}</h3>
          <strong>{usd(data.totals.credit_cents)}</strong>
          <p className="note">
            {t("مصرف‌نشده: ", "Unused: ")}
            {usd(data.totals.outstanding_cents)}
          </p>
        </article>
      </div>

      <form
        className="admin-payment-form"
        id="referral-settings"
        onSubmit={(e) => {
          const values = form(e);
          void call(
            "/api/admin/referrals/settings",
            "PUT",
            {
              enabled: values.get("enabled") === "on",
              attach_days: Number(values.get("attach_days")),
              credit_max_percent: Number(values.get("credit_max_percent")),
            },
            t("تنظیمات ذخیره شد.", "Settings saved."),
          );
        }}
      >
        <h3>{t("تنظیمات کلی", "General settings")}</h3>
        <label className="consent">
          <input
            id="referral-enabled"
            name="enabled"
            type="checkbox"
            defaultChecked={data.settings.enabled}
          />
          {t("سیستم دعوت فعال باشد", "Referrals are on")}
        </label>
        <div className="referral-grid">
          <div>
            <label htmlFor="attach-days">
              {t(
                "مهلت وارد کردن کد بعد از ثبت‌نام (روز)",
                "Days after sign-up to add a code",
              )}
            </label>
            <input
              id="attach-days"
              name="attach_days"
              type="number"
              dir="ltr"
              min={0}
              max={365}
              defaultValue={data.settings.attach_days}
            />
          </div>
          <div>
            <label htmlFor="credit-max">
              {t(
                "حداکثر سهم اعتبار از هر خرید (٪)",
                "Max share of a purchase paid by credit (%)",
              )}
            </label>
            <input
              id="credit-max"
              name="credit_max_percent"
              type="number"
              dir="ltr"
              min={0}
              max={100}
              defaultValue={data.settings.credit_max_percent}
            />
          </div>
        </div>
        <button type="submit" disabled={busy}>
          {t("ذخیرهٔ تنظیمات", "Save settings")}
        </button>
      </form>

      <h3>{t("برنامه‌ها", "Programs")}</h3>
      {!data.programs.length && (
        <p className="empty-state">
          {t(
            "هنوز برنامه‌ای نساخته‌اید. یکی از الگوهای آماده را انتخاب کنید یا برنامهٔ دلخواه بسازید.",
            "No programs yet. Pick a ready-made template or build your own.",
          )}
        </p>
      )}
      <div className="referral-programs">
        {data.programs.map((p) => {
          const reward = rewardText(p.config.referrer, lang);
          return (
            <article
              key={p.id}
              className={"referral-program" + (p.live ? " live" : "")}
            >
              <header>
                <strong>{p.name}</strong>
                <span className="pill">
                  {p.live
                    ? t("فعال", "Live")
                    : p.active
                      ? t("خارج از بازهٔ زمانی", "Outside its dates")
                      : t("غیرفعال", "Inactive")}
                </span>
                {p.is_default && (
                  <span className="quiet-tag">
                    {t("پیش‌فرض کدهای کاربران", "Default for customer codes")}
                  </span>
                )}
              </header>
              <p>
                <strong>{t("دوست دعوت‌شده: ", "Invited friend: ")}</strong>
                {offerText(p.config.referee, lang) ||
                  t("بدون تخفیف", "No discount")}
              </p>
              <p>
                <strong>{t("دعوت‌کننده: ", "Inviter: ")}</strong>
                {reward.text || t("بدون پاداش", "No reward")}
              </p>
              {reward.tiers.map((line) => (
                <p key={line} className="note">
                  {line}
                </p>
              ))}
              <p className="note">
                {t("ثبت‌نام: ", "Sign-ups: ")}
                {num(p.referrals, lang)} · {t("پاداش‌ها: ", "Rewards: ")}
                {num(p.rewards, lang)} · {t("اعتبار: ", "Credit: ")}
                {usd(p.credit_cents)}
                {(p.starts || p.ends) &&
                  " · " + (day(p.starts) || "…") + " → " + (day(p.ends) || "…")}
              </p>
              <div className="telegram-actions">
                <button
                  type="button"
                  className="secondary small"
                  onClick={() =>
                    setDraft({
                      id: p.id,
                      name: p.name,
                      active: p.active,
                      is_default: p.is_default,
                      starts: day(p.starts),
                      ends: day(p.ends),
                      referee: referee(p.config.referee),
                      referrer: referrer(p.config.referrer),
                    })
                  }
                >
                  {t("ویرایش", "Edit")}
                </button>
                <button
                  type="button"
                  className="secondary small danger"
                  disabled={busy}
                  onClick={() =>
                    window.confirm(
                      t("این برنامه حذف شود؟", "Delete this program?"),
                    ) &&
                    void call(
                      "/api/admin/referrals/programs/" + p.id,
                      "DELETE",
                      undefined,
                      t("برنامه حذف شد.", "Program deleted."),
                    )
                  }
                >
                  {t("حذف", "Delete")}
                </button>
              </div>
            </article>
          );
        })}
      </div>
      {!draft && (
        <div className="referral-presets">
          <span className="field-hint">
            {t("ساخت برنامهٔ جدید از الگو:", "New program from a template:")}
          </span>
          {PRESETS.map((preset) => (
            <button
              key={preset.en}
              type="button"
              className="secondary small"
              onClick={() => setDraft({ ...blank(), ...preset.make() })}
            >
              {lang === "en" ? preset.en : preset.fa}
            </button>
          ))}
          <button
            type="button"
            className="small"
            onClick={() => setDraft(blank())}
          >
            {t("برنامهٔ دلخواه", "Custom program")}
          </button>
        </div>
      )}
      {draft && (
        <form
          className="admin-payment-form referral-editor"
          id="referral-program-form"
          onSubmit={saveProgram}
        >
          <h3>
            {draft.id
              ? t("ویرایش برنامه", "Edit program")
              : t("برنامهٔ جدید", "New program")}
          </h3>
          <label htmlFor="program-name">
            {t("نام برنامه", "Program name")}
          </label>
          <input
            id="program-name"
            value={draft.name}
            minLength={2}
            maxLength={80}
            required
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
          <div className="referral-grid">
            <label className="consent">
              <input
                type="checkbox"
                checked={draft.active}
                onChange={(e) =>
                  setDraft({ ...draft, active: e.target.checked })
                }
              />
              {t("فعال", "Active")}
            </label>
            <label className="consent">
              <input
                id="program-default"
                type="checkbox"
                checked={draft.is_default}
                onChange={(e) =>
                  setDraft({ ...draft, is_default: e.target.checked })
                }
              />
              {t(
                "پیش‌فرض برای کد دعوت همهٔ کاربران",
                "Default for every customer's invite code",
              )}
            </label>
            <div>
              <label htmlFor="program-starts">
                {t("شروع (اختیاری)", "Starts (optional)")}
              </label>
              <input
                id="program-starts"
                type="date"
                dir="ltr"
                value={draft.starts}
                onChange={(e) => setDraft({ ...draft, starts: e.target.value })}
              />
            </div>
            <div>
              <label htmlFor="program-ends">
                {t("پایان (اختیاری)", "Ends (optional)")}
              </label>
              <input
                id="program-ends"
                type="date"
                dir="ltr"
                value={draft.ends}
                onChange={(e) => setDraft({ ...draft, ends: e.target.value })}
              />
            </div>
          </div>

          <fieldset>
            <legend>
              {t("تخفیف دوستِ دعوت‌شده", "Invited friend's discount")}
            </legend>
            <div className="referral-grid">
              <div>
                <label htmlFor="referee-type">{t("نوع", "Type")}</label>
                <select
                  id="referee-type"
                  value={draft.referee.type}
                  onChange={(e) =>
                    setEe({ type: e.target.value as RefereeOffer["type"] })
                  }
                >
                  <option value="none">{t("بدون تخفیف", "No discount")}</option>
                  <option value="percent">{t("درصدی", "Percentage")}</option>
                  <option value="fixed">
                    {t("مبلغ ثابت (دلار)", "Fixed amount (USD)")}
                  </option>
                </select>
              </div>
              {draft.referee.type !== "none" && (
                <>
                  {numberInput(
                    "referee-value",
                    draft.referee.type === "percent"
                      ? t("درصد تخفیف", "Discount %")
                      : t("مبلغ تخفیف (دلار)", "Discount (USD)"),
                    draft.referee.value,
                    (v) => setEe({ value: v }),
                    { max: draft.referee.type === "percent" ? 100 : undefined },
                  )}
                  {numberInput(
                    "referee-purchases",
                    t(
                      "تعداد خریدهای مشمول (۰ = همه)",
                      "Discounted purchases (0 = all)",
                    ),
                    draft.referee.purchases,
                    (v) => setEe({ purchases: Math.round(v) }),
                    { step: 1, max: 100 },
                  )}
                  {numberInput(
                    "referee-window",
                    t(
                      "مهلت استفاده پس از ثبت‌نام (روز، ۰ = نامحدود)",
                      "Days after sign-up (0 = no limit)",
                    ),
                    draft.referee.window_days,
                    (v) => setEe({ window_days: Math.round(v) }),
                    { step: 1 },
                  )}
                  {numberInput(
                    "referee-min",
                    t("حداقل مبلغ خرید (دلار)", "Minimum order (USD)"),
                    draft.referee.min_order_usd,
                    (v) => setEe({ min_order_usd: v }),
                  )}
                </>
              )}
            </div>
            {draft.referee.type !== "none" &&
              products(
                draft.referee.products,
                (v) => setEe({ products: v }),
                "referee-products",
              )}
          </fieldset>

          <fieldset>
            <legend>{t("پاداش دعوت‌کننده", "Inviter's reward")}</legend>
            <div className="referral-grid">
              <div>
                <label htmlFor="referrer-type">{t("نوع", "Type")}</label>
                <select
                  id="referrer-type"
                  value={draft.referrer.type}
                  onChange={(e) =>
                    setEr({ type: e.target.value as ReferrerReward["type"] })
                  }
                >
                  <option value="none">{t("بدون پاداش", "No reward")}</option>
                  <option value="credit">
                    {t(
                      "اعتبار خرید ثابت (دلار)",
                      "Fixed purchase credit (USD)",
                    )}
                  </option>
                  <option value="commission">
                    {t(
                      "کمیسیون: درصد از مبلغ خرید دوست، به‌صورت اعتبار",
                      "Commission: % of the friend's payment as credit",
                    )}
                  </option>
                  <option value="coupon">
                    {t(
                      "کوپن تخفیف درصدی برای خرید بعدی",
                      "Percentage coupon for the next purchase",
                    )}
                  </option>
                </select>
              </div>
              {draft.referrer.type !== "none" && (
                <>
                  {numberInput(
                    "referrer-value",
                    draft.referrer.type === "credit"
                      ? t("مبلغ اعتبار (دلار)", "Credit (USD)")
                      : t("درصد", "Percent"),
                    draft.referrer.value,
                    (v) => setEr({ value: v }),
                    { max: draft.referrer.type === "credit" ? undefined : 100 },
                  )}
                  <div>
                    <label htmlFor="referrer-trigger">
                      {t("پاداش برای", "Reward for")}
                    </label>
                    <select
                      id="referrer-trigger"
                      value={draft.referrer.trigger}
                      onChange={(e) =>
                        setEr({
                          trigger: e.target.value as ReferrerReward["trigger"],
                        })
                      }
                    >
                      <option value="first">
                        {t(
                          "فقط اولین خرید هر دوست",
                          "Each friend's first purchase only",
                        )}
                      </option>
                      <option value="every">
                        {t("هر خرید دوستان", "Every purchase by friends")}
                      </option>
                    </select>
                  </div>
                  {draft.referrer.trigger === "every" &&
                    numberInput(
                      "referrer-max",
                      t(
                        "سقف تعداد پاداش از هر دوست (۰ = نامحدود)",
                        "Max rewards per friend (0 = unlimited)",
                      ),
                      draft.referrer.max_per_referee,
                      (v) => setEr({ max_per_referee: Math.round(v) }),
                      { step: 1 },
                    )}
                  {numberInput(
                    "referrer-hold",
                    t(
                      "دورهٔ انتظار قبل از استفاده (روز)",
                      "Hold before use (days)",
                    ),
                    draft.referrer.hold_days,
                    (v) => setEr({ hold_days: Math.round(v) }),
                    { step: 1, max: 365 },
                  )}
                  {numberInput(
                    "referrer-expiry",
                    t(
                      "اعتبار پاداش (روز، ۰ = همیشگی)",
                      "Reward validity (days, 0 = forever)",
                    ),
                    draft.referrer.expiry_days,
                    (v) => setEr({ expiry_days: Math.round(v) }),
                    { step: 1 },
                  )}
                  {draft.referrer.type !== "coupon" &&
                    numberInput(
                      "referrer-cap",
                      t(
                        "سقف کل اعتبار هر نفر (دلار، ۰ = نامحدود)",
                        "Total credit cap per person (USD, 0 = none)",
                      ),
                      draft.referrer.max_total_usd,
                      (v) => setEr({ max_total_usd: v }),
                    )}
                  {numberInput(
                    "referrer-min",
                    t(
                      "حداقل مبلغ خرید دوست (دلار)",
                      "Friend's minimum order (USD)",
                    ),
                    draft.referrer.min_order_usd,
                    (v) => setEr({ min_order_usd: v }),
                  )}
                </>
              )}
            </div>
            {draft.referrer.type !== "none" && (
              <>
                {products(
                  draft.referrer.products,
                  (v) => setEr({ products: v }),
                  "referrer-products",
                )}
                <div className="referral-tiers">
                  <span className="field-hint">
                    {t(
                      "پلکان پاداش بر اساس تعداد دوستان خریدار (اختیاری)",
                      "Reward tiers by number of paying friends (optional)",
                    )}
                  </span>
                  {draft.referrer.tiers.map((tier, i) => (
                    <div key={i} className="input-row">
                      <input
                        aria-label={t("از تعداد دوست", "From friends")}
                        type="number"
                        dir="ltr"
                        min={2}
                        step={1}
                        value={tier.referrals}
                        onChange={(e) =>
                          setEr({
                            tiers: draft.referrer.tiers.map((x, j) =>
                              j === i
                                ? {
                                    ...x,
                                    referrals: Math.round(
                                      Number(e.target.value),
                                    ),
                                  }
                                : x,
                            ),
                          })
                        }
                      />
                      <input
                        aria-label={t("پاداش", "Reward")}
                        type="number"
                        dir="ltr"
                        min={0}
                        step="any"
                        value={tier.value}
                        onChange={(e) =>
                          setEr({
                            tiers: draft.referrer.tiers.map((x, j) =>
                              j === i
                                ? { ...x, value: Number(e.target.value) }
                                : x,
                            ),
                          })
                        }
                      />
                      <button
                        type="button"
                        className="text-button"
                        onClick={() =>
                          setEr({
                            tiers: draft.referrer.tiers.filter(
                              (_, j) => j !== i,
                            ),
                          })
                        }
                      >
                        {t("حذف", "Remove")}
                      </button>
                    </div>
                  ))}
                  {draft.referrer.tiers.length < 10 && (
                    <button
                      type="button"
                      className="secondary small"
                      onClick={() =>
                        setEr({
                          tiers: [
                            ...draft.referrer.tiers,
                            {
                              referrals:
                                (draft.referrer.tiers.at(-1)?.referrals ?? 1) +
                                4,
                              value: draft.referrer.value * 1.5 || 1,
                            },
                          ],
                        })
                      }
                    >
                      {t("افزودن پله", "Add tier")}
                    </button>
                  )}
                </div>
              </>
            )}
          </fieldset>
          <div className="referral-preview">
            <strong>
              {t("پیش‌نمایش برای کاربر", "What customers will see")}
            </strong>
            <p>
              {t("دوست: ", "Friend: ")}
              {offerText(draft.referee, lang) || "—"}
            </p>
            <p>
              {t("دعوت‌کننده: ", "Inviter: ")}
              {rewardText(draft.referrer, lang).text || "—"}
            </p>
          </div>
          <div className="telegram-actions">
            <button type="submit" disabled={busy}>
              {t("ذخیرهٔ برنامه", "Save program")}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => setDraft(null)}
            >
              {t("انصراف", "Cancel")}
            </button>
          </div>
        </form>
      )}

      <h3>{t("کدهای ویژه و کمپین‌ها", "Special and campaign codes")}</h3>
      <form
        className="admin-payment-form"
        id="referral-code-form"
        onSubmit={(e) => {
          const values = form(e);
          const target = e.currentTarget;
          void call(
            "/api/admin/referrals/codes",
            "POST",
            {
              code: values.get("code"),
              owner: values.get("owner") || null,
              program_id: values.get("program_id") || null,
              label: values.get("label"),
              max_uses: Number(values.get("max_uses") || 0),
              active: true,
            },
            t("کد ساخته شد.", "Code created."),
          ).then((ok) => ok && target.reset());
        }}
      >
        <p className="field-hint">
          {t(
            "برای اینفلوئنسر یا همکار، کد اختصاصی با صاحب و برنامهٔ جدا بسازید؛ برای کمپین عمومی (مثل نوروز) صاحب را خالی بگذارید.",
            "Make a dedicated code with its own owner and program for an influencer or partner; leave the owner empty for a public campaign.",
          )}
        </p>
        <div className="referral-grid">
          <div>
            <label htmlFor="new-code">{t("کد", "Code")}</label>
            <input
              id="new-code"
              name="code"
              dir="ltr"
              required
              minLength={3}
              maxLength={24}
              pattern="[A-Za-z0-9][A-Za-z0-9\-]{2,23}"
            />
          </div>
          <div>
            <label htmlFor="new-code-owner">
              {t("نام کاربری صاحب کد (اختیاری)", "Owner username (optional)")}
            </label>
            <input id="new-code-owner" name="owner" dir="ltr" maxLength={40} />
          </div>
          <div>
            <label htmlFor="new-code-program">{t("برنامه", "Program")}</label>
            <select id="new-code-program" name="program_id" defaultValue="">
              <option value="">
                {t("برنامهٔ پیش‌فرض", "Default program")}
              </option>
              {data.programs.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="new-code-label">{t("توضیح", "Label")}</label>
            <input id="new-code-label" name="label" maxLength={80} />
          </div>
          <div>
            <label htmlFor="new-code-max">
              {t("سقف استفاده (۰ = نامحدود)", "Usage limit (0 = none)")}
            </label>
            <input
              id="new-code-max"
              name="max_uses"
              type="number"
              dir="ltr"
              min={0}
              defaultValue={0}
            />
          </div>
        </div>
        <button type="submit" disabled={busy}>
          {t("ساخت کد", "Create code")}
        </button>
      </form>
      {!!data.codes.length && (
        <div className="table-wrap">
          <table id="referral-codes">
            <thead>
              <tr>
                <th>{t("کد", "Code")}</th>
                <th>{t("صاحب", "Owner")}</th>
                <th>{t("برنامه", "Program")}</th>
                <th>{t("استفاده / خریدار", "Uses / paying")}</th>
                <th>{t("وضعیت", "Status")}</th>
              </tr>
            </thead>
            <tbody>
              {data.codes.map((c) => (
                <tr key={c.code}>
                  <td>
                    <bdi dir="ltr">{c.code}</bdi>
                    {c.label && <small> · {c.label}</small>}
                  </td>
                  <td>{c.owner ?? t("کمپین", "Campaign")}</td>
                  <td>{programName(c.program_id)}</td>
                  <td>
                    {num(c.uses, lang)}
                    {c.max_uses ? " / " + num(c.max_uses, lang) : ""} ·{" "}
                    {num(c.paying, lang)}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="text-button"
                      disabled={busy}
                      onClick={() =>
                        void call(
                          "/api/admin/referrals/codes/" +
                            encodeURIComponent(c.code),
                          "PUT",
                          {
                            code: c.code,
                            program_id: c.program_id,
                            label: c.label,
                            max_uses: c.max_uses,
                            active: !c.active,
                          },
                          c.active
                            ? t("کد غیرفعال شد.", "Code disabled.")
                            : t("کد فعال شد.", "Code enabled."),
                        )
                      }
                    >
                      {c.active
                        ? t("فعال · غیرفعال کن", "Active · disable")
                        : t("غیرفعال · فعال کن", "Disabled · enable")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>{t("اعتبار یا کوپن دستی", "Manual credit or coupon")}</h3>
      <form
        className="admin-payment-form"
        id="referral-grant-form"
        onSubmit={(e) => {
          const values = form(e);
          const target = e.currentTarget;
          void call(
            "/api/admin/referrals/rewards",
            "POST",
            {
              username: values.get("username"),
              kind: values.get("kind"),
              value: Number(values.get("value")),
              note: values.get("note"),
              expiry_days: Number(values.get("expiry_days") || 0),
            },
            t("پاداش ثبت شد.", "Reward granted."),
          ).then((ok) => ok && target.reset());
        }}
      >
        <div className="referral-grid">
          <div>
            <label htmlFor="grant-user">{t("نام کاربری", "Username")}</label>
            <input
              id="grant-user"
              name="username"
              dir="ltr"
              required
              maxLength={40}
            />
          </div>
          <div>
            <label htmlFor="grant-kind">{t("نوع", "Type")}</label>
            <select id="grant-kind" name="kind">
              <option value="credit">
                {t("اعتبار (دلار)", "Credit (USD)")}
              </option>
              <option value="coupon">
                {t("کوپن درصدی", "Percentage coupon")}
              </option>
            </select>
          </div>
          <div>
            <label htmlFor="grant-value">{t("مقدار", "Amount")}</label>
            <input
              id="grant-value"
              name="value"
              type="number"
              dir="ltr"
              min={0.01}
              step="any"
              required
            />
          </div>
          <div>
            <label htmlFor="grant-expiry">
              {t("اعتبار (روز، ۰ = همیشگی)", "Valid for (days, 0 = forever)")}
            </label>
            <input
              id="grant-expiry"
              name="expiry_days"
              type="number"
              dir="ltr"
              min={0}
              defaultValue={0}
            />
          </div>
          <div>
            <label htmlFor="grant-note">
              {t("توضیح برای کاربر", "Note for the customer")}
            </label>
            <input id="grant-note" name="note" maxLength={200} />
          </div>
        </div>
        <button type="submit" disabled={busy}>
          {t("ثبت پاداش", "Grant")}
        </button>
      </form>

      {!!data.top.length && (
        <>
          <h3>{t("برترین دعوت‌کننده‌ها", "Top inviters")}</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("کاربر", "User")}</th>
                  <th>{t("ثبت‌نام", "Sign-ups")}</th>
                  <th>{t("خریدار", "Paying")}</th>
                  <th>{t("اعتبار دریافتی", "Credit earned")}</th>
                </tr>
              </thead>
              <tbody>
                {data.top.map((r) => (
                  <tr key={r.username}>
                    <td>
                      <bdi>{r.username}</bdi>
                    </td>
                    <td>{num(r.signups, lang)}</td>
                    <td>{num(r.paying, lang)}</td>
                    <td>{usd(r.credit_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {!!data.rewards.length && (
        <>
          <h3>{t("آخرین پاداش‌ها", "Latest rewards")}</h3>
          <div className="table-wrap">
            <table id="referral-reward-log">
              <thead>
                <tr>
                  <th>{t("کاربر", "User")}</th>
                  <th>{t("پاداش", "Reward")}</th>
                  <th>{t("بابت", "For")}</th>
                  <th>{t("تاریخ", "Date")}</th>
                  <th>{t("عملیات", "Actions")}</th>
                </tr>
              </thead>
              <tbody>
                {data.rewards.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <bdi>{r.username}</bdi>
                    </td>
                    <td>
                      {r.kind === "credit"
                        ? usd(r.value)
                        : t("کوپن ", "Coupon ") +
                          percent(r.value / 100, lang, 0)}
                    </td>
                    <td>
                      {r.source === "admin"
                        ? r.note || t("دستی", "Manual")
                        : t("خرید ", "Purchase by ") + (r.referee ?? "—")}
                    </td>
                    <td>{dateTime(r.created, lang)}</td>
                    <td>
                      {r.state === "void" ? (
                        t("باطل‌شده", "Voided")
                      ) : (
                        <button
                          type="button"
                          className="text-button"
                          disabled={busy}
                          onClick={() =>
                            window.confirm(
                              t("این پاداش باطل شود؟", "Void this reward?"),
                            ) &&
                            void call(
                              "/api/admin/referrals/rewards/" + r.id + "/void",
                              "POST",
                              {},
                              t("پاداش باطل شد.", "Reward voided."),
                            )
                          }
                        >
                          {t("ابطال", "Void")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {note && (
        <p className="admin-error" role="status">
          {note}
        </p>
      )}
    </section>
  );
}
