"use client";
import { useEffect, useMemo, useState } from "react";
import { ApiClient, ApiError, errorText } from "@/lib/api";
import { num } from "@/lib/format";
import { localPath, pick, type Lang } from "@/lib/i18n";
import { useLang } from "@/lib/lang";
import { parseMarkdown, readingMinutes } from "@/lib/markdown";
import Markdown from "./markdown";
import { Heading } from "./shared";

type Report = (error: unknown) => void;
interface Summary {
  id: string;
  lang: Lang;
  slug: string;
  title: string;
  description: string;
  keywords: string[];
  status: "draft" | "published";
  published_on: string | null;
  updated: number;
  updated_on: string;
  minutes: number;
}
interface Article extends Summary {
  body: string;
}
interface Draft {
  lang: Lang;
  slug: string;
  title: string;
  description: string;
  keywords: string;
  body: string;
  published_on: string;
}
const today = () => new Date().toISOString().slice(0, 10);

function state(post: Summary, ui: Lang) {
  const t = pick(ui);
  if (post.status === "draft") return [t("پیش‌نویس", "Draft"), "warning", "draft"];
  if (post.published_on && post.published_on > today())
    return [t("زمان‌بندی‌شده", "Scheduled"), "neutral", "scheduled"];
  return [t("منتشرشده", "Published"), "success", "live"];
}

// Latin address from a Latin title; Persian titles need the address typed by hand.
function suggestSlug(title: string) {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/[\s-]+/g, "-")
    .slice(0, 80);
}

// Quick, honest checks; passing them does not guarantee a ranking.
function seoChecks(d: Draft, ui: Lang) {
  const t = pick(ui),
    n = (value: number) => num(value, ui);
  const blocks = parseMarkdown(d.body);
  const words = d.body.split(/\s+/).filter(Boolean).length;
  const firstKeyword = d.keywords.split(/[,،]/)[0]?.trim();
  return [
    [
      d.title.length >= 30 && d.title.length <= 65,
      t(
        `طول عنوان ${n(d.title.length)} حرف؛ بهتر است ۳۰ تا ۶۵ باشد.`,
        `Title is ${d.title.length} characters; 30 to 65 is best.`,
      ),
    ],
    [
      d.description.length >= 110 && d.description.length <= 165,
      t(
        `طول توضیح ${n(d.description.length)} حرف؛ بهتر است ۱۱۰ تا ۱۶۵ باشد.`,
        `Description is ${d.description.length} characters; 110 to 165 is best.`,
      ),
    ],
    [
      !!firstKeyword && d.title.includes(firstKeyword),
      t(
        "کلمهٔ کلیدی اصلی (اولین کلمه در فهرست) در عنوان آمده است.",
        "The main keyword (first in the list) appears in the title.",
      ),
    ],
    [
      blocks.filter((b) => b.kind === "h2").length >= 2,
      t(
        "دست‌کم دو تیتر ## برای ساختار و فهرست مطالب دارد.",
        "Has at least two ## headings for structure and a contents list.",
      ),
    ],
    [
      /\]\(\/(?!\/)/.test(d.body),
      t(
        "دست‌کم یک پیوند به صفحهٔ دیگری از سایت دارد.",
        "Links to at least one other page on the site.",
      ),
    ],
    [
      words >= 400,
      t(
        `${n(words)} کلمه؛ مقاله‌های ۴۰۰ کلمه به بالا بهترند.`,
        `${words} words; articles of 400+ words do better.`,
      ),
    ],
  ] as const;
}

export default function AdminBlog({
  api,
  report,
}: {
  api: ApiClient;
  report: Report;
}) {
  const { lang, t } = useLang();
  const [items, setItems] = useState<Summary[] | null>(null),
    [revision, setRevision] = useState(0),
    [editing, setEditing] = useState<Article | "new" | null>(null);
  useEffect(() => {
    let current = true;
    api
      .request<{ items: Summary[] }>("/api/admin/blog")
      .then((d) => {
        if (current) setItems(d.items);
      })
      .catch((e) => {
        if (current) report(e);
      });
    return () => {
      current = false;
    };
  }, [api, report, revision]);
  const open = (id: string) =>
    api
      .request<Article>("/api/admin/blog/" + id)
      .then(setEditing)
      .catch(report);
  if (editing)
    return (
      <Editor
        api={api}
        article={editing === "new" ? null : editing}
        onClose={() => {
          setEditing(null);
          setRevision((n) => n + 1);
        }}
      />
    );
  return (
    <section className="panel" id="admin-blog">
      <div className="admin-blog-head">
        <Heading
          eyebrow="AVINA JOURNAL"
          title={t("مقاله‌های بلاگ", "Blog articles")}
          description={t(
            "مقاله بنویسید، پیش‌نویس نگه دارید یا منتشر کنید. مقالهٔ منتشرشده همان لحظه در سایت و نقشهٔ سایت دیده می‌شود.",
            "Write articles, keep drafts or publish. A published article appears on the site and in the sitemap right away.",
          )}
        />
        <button id="admin-blog-new" onClick={() => setEditing("new")}>
          {t("مقالهٔ تازه", "New article")}
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {[
                t("عنوان", "Title"),
                t("زبان", "Language"),
                t("آدرس", "Address"),
                t("وضعیت", "Status"),
                t("تاریخ انتشار", "Publish date"),
                "",
              ].map((h, i) => (
                <th key={i}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items?.map((post) => {
              const [label, tone, kind] = state(post, lang);
              const address = localPath(post.lang, `/blog/${post.slug}/`);
              return (
                <tr key={post.id}>
                  <td>
                    <bdi>{post.title}</bdi>
                  </td>
                  <td>{post.lang === "en" ? "English" : "فارسی"}</td>
                  <td>
                    <bdi dir="ltr">{address}</bdi>
                  </td>
                  <td>
                    <span className={"pill " + tone}>{label}</span>
                  </td>
                  <td>
                    <bdi>{post.published_on ?? "—"}</bdi>
                  </td>
                  <td className="admin-row-actions">
                    <button className="small" onClick={() => open(post.id)}>
                      {t("ویرایش", "Edit")}
                    </button>
                    {kind === "live" && (
                      <a
                        className="admin-view-link"
                        href={address}
                        target="_blank"
                        rel="noopener"
                      >
                        {t("مشاهده", "View")}
                      </a>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {items && !items.length && (
        <p className="empty-state">
          {t("هنوز مقاله‌ای نوشته نشده است.", "No articles yet.")}
        </p>
      )}
    </section>
  );
}

function Editor({
  api,
  article,
  onClose,
}: {
  api: ApiClient;
  article: Article | null;
  onClose: () => void;
}) {
  const { lang, t } = useLang();
  const [draft, setDraft] = useState<Draft>(
      article
        ? {
            lang: article.lang,
            slug: article.slug,
            title: article.title,
            description: article.description,
            keywords: article.keywords.join(article.lang === "en" ? ", " : "، "),
            body: article.body,
            published_on: article.published_on ?? "",
          }
        : {
            lang,
            slug: "",
            title: "",
            description: "",
            keywords: "",
            body: "",
            published_on: "",
          },
    ),
    [saved, setSaved] = useState(article),
    [slugTouched, setSlugTouched] = useState(!!article),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [view, setView] = useState<"write" | "preview">("write");
  const blocks = useMemo(() => parseMarkdown(draft.body), [draft.body]);
  const checks = useMemo(() => seoChecks(draft, lang), [draft, lang]);
  const set = (key: keyof Draft) => (value: string) =>
    setDraft((d) => {
      const next = { ...d, [key]: value };
      if (key === "title" && !slugTouched) next.slug = suggestSlug(value);
      return next;
    });
  const movedLive =
    saved?.status === "published" &&
    (saved.slug !== draft.slug || saved.lang !== draft.lang);
  const address = localPath(draft.lang, `/blog/${draft.slug || "…"}/`);

  async function save(status: "draft" | "published") {
    setBusy(true);
    setMessage("");
    const payload = {
      lang: draft.lang,
      slug: draft.slug.trim(),
      title: draft.title.trim(),
      description: draft.description.trim(),
      keywords: draft.keywords
        .split(/[,،]/)
        .map((k) => k.trim())
        .filter(Boolean),
      body: draft.body,
      status,
      published_on: draft.published_on || null,
      ...(saved ? { expected_updated: saved.updated } : {}),
    };
    try {
      const result = await api.request<Article>(
        saved ? "/api/admin/blog/" + saved.id : "/api/admin/blog",
        saved ? "PUT" : "POST",
        payload,
      );
      setSaved(result);
      setDraft((d) => ({ ...d, published_on: result.published_on ?? "" }));
      setMessage(
        status === "published"
          ? result.published_on && result.published_on > today()
            ? t(
                "ذخیره شد؛ مقاله در تاریخ انتشار در سایت دیده می‌شود.",
                "Saved; the article appears on the site on its publish date.",
              )
            : t("منتشر شد و در سایت دیده می‌شود.", "Published and live on the site.")
          : t("پیش‌نویس ذخیره شد.", "Draft saved."),
      );
    } catch (e) {
      setMessage(
        e instanceof ApiError && e.status === 409
          ? t(
              "این آدرس در همین زبان قبلاً استفاده شده، یا مقاله در جای دیگری تغییر کرده است. صفحه را تازه کنید.",
              "This address is already used in this language, or the article changed elsewhere. Refresh the page.",
            )
          : e instanceof ApiError && e.status === 422
            ? t(
                "فیلدها را بررسی کنید: آدرس فقط حروف کوچک لاتین، عدد و خط تیره؛ عنوان، توضیح و متن لازم‌اند.",
                "Check the fields: the address takes lowercase Latin letters, numbers and dashes; title, description and body are required.",
              )
            : errorText(e),
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (
      !saved ||
      !window.confirm(
        t("این مقاله برای همیشه حذف شود؟", "Delete this article permanently?"),
      )
    )
      return;
    setBusy(true);
    try {
      await api.request(
        `/api/admin/blog/${saved.id}?expected_updated=${saved.updated}`,
        "DELETE",
      );
      onClose();
    } catch (e) {
      setMessage(errorText(e));
      setBusy(false);
    }
  }

  return (
    <section className="panel" id="admin-blog-editor">
      <div className="admin-blog-head">
        <Heading
          eyebrow={saved ? "EDIT ARTICLE" : "NEW ARTICLE"}
          title={
            saved
              ? t("ویرایش مقاله", "Edit article")
              : t("مقالهٔ تازه", "New article")
          }
          description={t(
            "متن با قالب ساده نوشته می‌شود: ## تیتر، ### زیرتیتر، - فهرست، 1. فهرست شماره‌دار، **پررنگ**، [متن](/blog/آدرس/) و > نقل قول.",
            "Write in a simple format: ## heading, ### subheading, - list, 1. numbered list, **bold**, [text](/en/blog/address/) and > quote.",
          )}
        />
        <button className="secondary" onClick={onClose} disabled={busy}>
          {t("بازگشت به فهرست", "Back to list")}
        </button>
      </div>
      <div className="admin-blog-grid">
        <div className="admin-blog-fields">
          <label htmlFor="blog-lang">{t("زبان مقاله", "Article language")}</label>
          <select
            id="blog-lang"
            value={draft.lang}
            onChange={(e) => set("lang")(e.target.value)}
          >
            <option value="fa">فارسی</option>
            <option value="en">English</option>
          </select>
          <label htmlFor="blog-title">{t("عنوان", "Title")}</label>
          <input
            id="blog-title"
            dir={draft.lang === "en" ? "ltr" : "rtl"}
            value={draft.title}
            maxLength={120}
            onChange={(e) => set("title")(e.target.value)}
          />
          <label htmlFor="blog-slug">{t("آدرس مقاله", "Article address")}</label>
          <input
            id="blog-slug"
            dir="ltr"
            value={draft.slug}
            maxLength={80}
            placeholder="futures-trading-guide"
            onChange={(e) => {
              setSlugTouched(true);
              set("slug")(e.target.value.toLowerCase());
            }}
          />
          <p className="field-hint">
            <bdi dir="ltr">{address}</bdi> ·{" "}
            {t(
              "فقط حروف کوچک لاتین، عدد و خط تیره. اگر نسخهٔ فارسی و انگلیسی یک مقاله آدرس یکسان داشته باشند، به هم پیوند داده می‌شوند.",
              "Lowercase Latin letters, numbers and dashes only. Persian and English versions with the same address are linked to each other.",
            )}
          </p>
          {movedLive && (
            <p className="field-hint warning-text">
              {t(
                "تغییر آدرس یا زبان مقالهٔ منتشرشده پیوندهای قبلی و جایگاه آن در گوگل را از بین می‌برد.",
                "Changing the address or language of a published article breaks old links and its Google ranking.",
              )}
            </p>
          )}
          <label htmlFor="blog-description">
            {t("توضیح کوتاه (نمایش در گوگل)", "Short description (shown in Google)")}
          </label>
          <textarea
            id="blog-description"
            dir={draft.lang === "en" ? "ltr" : "rtl"}
            rows={3}
            value={draft.description}
            maxLength={300}
            onChange={(e) => set("description")(e.target.value)}
          />
          <label htmlFor="blog-keywords">
            {t("کلمات کلیدی، با کاما جدا کنید", "Keywords, comma separated")}
          </label>
          <input
            id="blog-keywords"
            dir={draft.lang === "en" ? "ltr" : "rtl"}
            value={draft.keywords}
            maxLength={300}
            onChange={(e) => set("keywords")(e.target.value)}
          />
          <label htmlFor="blog-date">
            {t("تاریخ انتشار (اختیاری)", "Publish date (optional)")}
          </label>
          <input
            id="blog-date"
            type="date"
            dir="ltr"
            value={draft.published_on}
            onChange={(e) => set("published_on")(e.target.value)}
          />
          <p className="field-hint">
            {t(
              "خالی بماند یعنی روز انتشار. تاریخ آینده مقاله را زمان‌بندی می‌کند.",
              "Leave empty to use the day you publish. A future date schedules the article.",
            )}
          </p>
          <div
            className="admin-seo-checks"
            aria-label={t("بررسی سئو", "SEO check")}
          >
            <strong>{t("بررسی سریع سئو", "Quick SEO check")}</strong>
            <ul>
              {checks.map(([ok, text]) => (
                <li key={text} className={ok ? "ok" : "todo"}>
                  <span aria-hidden="true">{ok ? "✓" : "○"}</span> {text}
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="admin-blog-body">
          <div className="admin-blog-tabs" role="tablist">
            <button
              role="tab"
              aria-selected={view === "write"}
              className={view === "write" ? "active" : "secondary"}
              onClick={() => setView("write")}
            >
              {t("نوشتن", "Write")}
            </button>
            <button
              role="tab"
              aria-selected={view === "preview"}
              className={view === "preview" ? "active" : "secondary"}
              onClick={() => setView("preview")}
            >
              {t("پیش‌نمایش", "Preview")}
            </button>
            <span>
              {num(readingMinutes(draft.body), lang)}{" "}
              {t("دقیقه مطالعه", "min read")}
            </span>
          </div>
          {view === "write" ? (
            <textarea
              id="blog-body"
              dir={draft.lang === "en" ? "ltr" : "rtl"}
              aria-label={t("متن مقاله", "Article body")}
              value={draft.body}
              maxLength={60000}
              onChange={(e) => set("body")(e.target.value)}
            />
          ) : (
            <div
              className="blog-body admin-blog-preview"
              dir={draft.lang === "en" ? "ltr" : "rtl"}
              lang={draft.lang}
            >
              <h1>{draft.title}</h1>
              <Markdown blocks={blocks} />
            </div>
          )}
        </div>
      </div>
      <p className="admin-error" role="status">
        {message}
      </p>
      <div className="dialog-actions">
        <button
          id="blog-publish"
          disabled={busy}
          onClick={() => save("published")}
        >
          {saved?.status === "published"
            ? t("ذخیره و انتشار", "Save and publish")
            : t("انتشار", "Publish")}
        </button>
        <button
          id="blog-save-draft"
          className="secondary"
          disabled={busy}
          onClick={() => save("draft")}
        >
          {saved?.status === "published"
            ? t("برگرداندن به پیش‌نویس", "Unpublish to draft")
            : t("ذخیرهٔ پیش‌نویس", "Save draft")}
        </button>
        {saved && (
          <button
            id="blog-delete"
            className="secondary danger"
            disabled={busy}
            onClick={remove}
          >
            {t("حذف مقاله", "Delete article")}
          </button>
        )}
      </div>
    </section>
  );
}
