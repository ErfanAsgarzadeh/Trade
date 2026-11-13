"use client";
import { useEffect, useMemo, useState } from "react";
import { ApiClient, ApiError, errorText } from "@/lib/api";
import { faNumber } from "@/lib/format";
import { parseMarkdown, readingMinutes } from "@/lib/markdown";
import Markdown from "./markdown";
import { Heading } from "./shared";

type Report = (error: unknown) => void;
interface Summary {
  id: string;
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
  slug: string;
  title: string;
  description: string;
  keywords: string;
  body: string;
  published_on: string;
}
const empty: Draft = {
  slug: "",
  title: "",
  description: "",
  keywords: "",
  body: "",
  published_on: "",
};
const today = () => new Date().toISOString().slice(0, 10);

function state(post: Summary) {
  if (post.status === "draft") return ["پیش‌نویس", "warning"];
  if (post.published_on && post.published_on > today())
    return ["زمان‌بندی‌شده", "neutral"];
  return ["منتشرشده", "success"];
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
function seoChecks(d: Draft) {
  const blocks = parseMarkdown(d.body);
  const words = d.body.split(/\s+/).filter(Boolean).length;
  const firstKeyword = d.keywords.split(/[,،]/)[0]?.trim();
  return [
    [
      d.title.length >= 30 && d.title.length <= 65,
      `طول عنوان ${faNumber(d.title.length)} حرف؛ بهتر است ۳۰ تا ۶۵ باشد.`,
    ],
    [
      d.description.length >= 110 && d.description.length <= 165,
      `طول توضیح ${faNumber(d.description.length)} حرف؛ بهتر است ۱۱۰ تا ۱۶۵ باشد.`,
    ],
    [
      !!firstKeyword && d.title.includes(firstKeyword),
      "کلمهٔ کلیدی اصلی (اولین کلمه در فهرست) در عنوان آمده است.",
    ],
    [
      blocks.filter((b) => b.kind === "h2").length >= 2,
      "دست‌کم دو تیتر ## برای ساختار و فهرست مطالب دارد.",
    ],
    [
      /\]\(\/(?!\/)/.test(d.body),
      "دست‌کم یک پیوند به صفحهٔ دیگری از سایت دارد.",
    ],
    [
      words >= 400,
      `${faNumber(words)} کلمه؛ مقاله‌های ۴۰۰ کلمه به بالا بهترند.`,
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
          title="مقاله‌های بلاگ"
          description="مقاله بنویسید، پیش‌نویس نگه دارید یا منتشر کنید. مقالهٔ منتشرشده همان لحظه در سایت و نقشهٔ سایت دیده می‌شود."
        />
        <button id="admin-blog-new" onClick={() => setEditing("new")}>
          مقالهٔ تازه ＋
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {["عنوان", "آدرس", "وضعیت", "تاریخ انتشار", ""].map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items?.map((post) => {
              const [label, tone] = state(post);
              return (
                <tr key={post.id}>
                  <td>{post.title}</td>
                  <td>
                    <bdi dir="ltr">/blog/{post.slug}/</bdi>
                  </td>
                  <td>
                    <span className={"pill " + tone}>{label}</span>
                  </td>
                  <td>
                    <bdi>{post.published_on ?? "—"}</bdi>
                  </td>
                  <td className="admin-row-actions">
                    <button className="small" onClick={() => open(post.id)}>
                      ویرایش
                    </button>
                    {label === "منتشرشده" && (
                      <a
                        className="admin-view-link"
                        href={`/blog/${post.slug}/`}
                        target="_blank"
                        rel="noopener"
                      >
                        مشاهده
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
        <p className="empty-state">هنوز مقاله‌ای نوشته نشده است.</p>
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
  const [draft, setDraft] = useState<Draft>(
      article
        ? {
            slug: article.slug,
            title: article.title,
            description: article.description,
            keywords: article.keywords.join("، "),
            body: article.body,
            published_on: article.published_on ?? "",
          }
        : empty,
    ),
    [saved, setSaved] = useState(article),
    [slugTouched, setSlugTouched] = useState(!!article),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [view, setView] = useState<"write" | "preview">("write");
  const blocks = useMemo(() => parseMarkdown(draft.body), [draft.body]);
  const checks = useMemo(() => seoChecks(draft), [draft]);
  const set = (key: keyof Draft) => (value: string) =>
    setDraft((d) => {
      const next = { ...d, [key]: value };
      if (key === "title" && !slugTouched) next.slug = suggestSlug(value);
      return next;
    });
  const livePublished =
    saved?.status === "published" && saved.slug !== draft.slug;

  async function save(status: "draft" | "published") {
    setBusy(true);
    setMessage("");
    const payload = {
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
            ? "ذخیره شد؛ مقاله در تاریخ انتشار در سایت دیده می‌شود."
            : "منتشر شد و در سایت دیده می‌شود."
          : "پیش‌نویس ذخیره شد.",
      );
    } catch (e) {
      setMessage(
        e instanceof ApiError && e.status === 409
          ? "این آدرس قبلاً استفاده شده، یا مقاله در جای دیگری تغییر کرده است. صفحه را تازه کنید."
          : e instanceof ApiError && e.status === 422
            ? "فیلدها را بررسی کنید: آدرس فقط حروف کوچک لاتین، عدد و خط تیره؛ عنوان، توضیح و متن لازم‌اند."
            : errorText(e),
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!saved || !window.confirm("این مقاله برای همیشه حذف شود؟")) return;
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
          title={saved ? "ویرایش مقاله" : "مقالهٔ تازه"}
          description="متن با قالب ساده نوشته می‌شود: ## تیتر، ### زیرتیتر، - فهرست، 1. فهرست شماره‌دار، **پررنگ**، [متن](/blog/آدرس/) و > نقل قول."
        />
        <button className="secondary" onClick={onClose} disabled={busy}>
          ← بازگشت به فهرست
        </button>
      </div>
      <div className="admin-blog-grid">
        <div className="admin-blog-fields">
          <label htmlFor="blog-title">عنوان</label>
          <input
            id="blog-title"
            value={draft.title}
            maxLength={120}
            onChange={(e) => set("title")(e.target.value)}
          />
          <label htmlFor="blog-slug">آدرس مقاله</label>
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
            <bdi dir="ltr">/blog/{draft.slug || "…"}/</bdi> · فقط حروف کوچک
            لاتین، عدد و خط تیره.
          </p>
          {livePublished && (
            <p className="field-hint warning-text">
              تغییر آدرس مقالهٔ منتشرشده پیوندهای قبلی و جایگاه آن در گوگل را از
              بین می‌برد.
            </p>
          )}
          <label htmlFor="blog-description">توضیح کوتاه (نمایش در گوگل)</label>
          <textarea
            id="blog-description"
            rows={3}
            value={draft.description}
            maxLength={300}
            onChange={(e) => set("description")(e.target.value)}
          />
          <label htmlFor="blog-keywords">کلمات کلیدی، با کاما جدا کنید</label>
          <input
            id="blog-keywords"
            value={draft.keywords}
            maxLength={300}
            onChange={(e) => set("keywords")(e.target.value)}
          />
          <label htmlFor="blog-date">تاریخ انتشار (اختیاری)</label>
          <input
            id="blog-date"
            type="date"
            dir="ltr"
            value={draft.published_on}
            onChange={(e) => set("published_on")(e.target.value)}
          />
          <p className="field-hint">
            خالی بماند یعنی روز انتشار. تاریخ آینده مقاله را زمان‌بندی می‌کند.
          </p>
          <div className="admin-seo-checks" aria-label="بررسی سئو">
            <strong>بررسی سریع سئو</strong>
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
              نوشتن
            </button>
            <button
              role="tab"
              aria-selected={view === "preview"}
              className={view === "preview" ? "active" : "secondary"}
              onClick={() => setView("preview")}
            >
              پیش‌نمایش
            </button>
            <span>{faNumber(readingMinutes(draft.body))} دقیقه مطالعه</span>
          </div>
          {view === "write" ? (
            <textarea
              id="blog-body"
              aria-label="متن مقاله"
              value={draft.body}
              maxLength={60000}
              onChange={(e) => set("body")(e.target.value)}
            />
          ) : (
            <div className="blog-body admin-blog-preview">
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
          {saved?.status === "published" ? "ذخیره و انتشار" : "انتشار"}
        </button>
        <button
          id="blog-save-draft"
          className="secondary"
          disabled={busy}
          onClick={() => save("draft")}
        >
          {saved?.status === "published"
            ? "برگرداندن به پیش‌نویس"
            : "ذخیرهٔ پیش‌نویس"}
        </button>
        {saved && (
          <button
            id="blog-delete"
            className="secondary danger"
            disabled={busy}
            onClick={remove}
          >
            حذف مقاله
          </button>
        )}
      </div>
    </section>
  );
}
