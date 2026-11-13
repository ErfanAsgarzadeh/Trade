import type { Metadata } from "next";
import Markdown from "@/components/markdown";
import { PostCard } from "@/components/landing";
import { SiteFooter, SiteHeader } from "@/components/site-chrome";
import { allPosts, persianDate } from "@/lib/blog";
import { faNumber } from "@/lib/format";

type Props = { params: Promise<{ slug: string }> };
export const dynamicParams = false;

export function generateStaticParams() {
  return allPosts().map((post) => ({ slug: post.slug }));
}

function find(slug: string) {
  const post = allPosts().find((item) => item.slug === slug);
  if (!post) throw Error(`Unknown blog post ${slug}`);
  return post;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const post = find((await params).slug);
  const title = `${post.title} | بلاگ آوینا`;
  return {
    title,
    description: post.description,
    keywords: post.keywords,
    openGraph: {
      type: "article",
      title,
      description: post.description,
      publishedTime: post.date,
      modifiedTime: post.updated,
    },
    twitter: { title, description: post.description },
  };
}

export default async function BlogPost({ params }: Props) {
  const post = find((await params).slug);
  const related = allPosts()
    .filter((item) => item.slug !== post.slug)
    .slice(0, 2);
  const contents = post.blocks.filter((block) => block.kind === "h2");
  // BlogPosting and breadcrumb JSON-LD need absolute URLs, so portal_frontend.py adds them when it serves the page.
  return (
    <div className="landing blog-page">
      <a className="skip-link" href="#blog-main">
        رفتن به محتوا
      </a>
      <SiteHeader />
      <main id="blog-main">
        <article className="blog-article">
          <nav className="blog-breadcrumb" aria-label="مسیر صفحه">
            <a href="/">آوینا</a>
            <span aria-hidden="true">/</span>
            <a href="/blog/">بلاگ</a>
          </nav>
          <header className="blog-article-head">
            <h1>{post.title}</h1>
            <p className="blog-lead">{post.description}</p>
            <small>
              <time dateTime={post.date}>{persianDate(post.date)}</time>
              <span aria-hidden="true">·</span>
              <span>{faNumber(post.minutes)} دقیقه مطالعه</span>
              {post.updated !== post.date && (
                <span>
                  به‌روزرسانی{" "}
                  <time dateTime={post.updated}>
                    {persianDate(post.updated)}
                  </time>
                </span>
              )}
            </small>
          </header>
          {contents.length > 2 && (
            <nav className="blog-contents" aria-label="فهرست مطالب">
              <strong>در این مقاله</strong>
              <ol>
                {contents.map((block) =>
                  block.kind === "h2" ? (
                    <li key={block.id}>
                      <a href={`#${block.id}`}>{block.text}</a>
                    </li>
                  ) : null,
                )}
              </ol>
            </nav>
          )}
          <div className="blog-body">
            <Markdown blocks={post.blocks} />
          </div>
          <aside className="blog-cta" aria-label="شروع با آوینا">
            <h2>کارنامهٔ آوینا را خودتان بسنجید.</h2>
            <p>
              بک‌تست پنج‌ساله، دادهٔ روزانه و روش محاسبه را ببینید و اگر قانع
              شدید، حساب بسازید. سرمایه در حساب صرافی خودتان می‌ماند.
            </p>
            <div>
              <a className="landing-primary" href="/#backtest">
                دیدن کارنامه ←
              </a>
              <a className="landing-secondary" href="/register/">
                ساخت حساب ←
              </a>
            </div>
          </aside>
          <p className="blog-disclaimer">
            این مقاله آموزشی است و توصیهٔ سرمایه‌گذاری نیست. معامله در بازار
            فیوچرز ریسک از دست دادن سرمایه دارد.
          </p>
        </article>
        {related.length > 0 && (
          <section className="blog-related" aria-labelledby="related-title">
            <h2 id="related-title">مقاله‌های دیگر</h2>
            <div className="blog-cards">
              {related.map((item) => (
                <PostCard key={item.slug} post={item} />
              ))}
            </div>
          </section>
        )}
      </main>
      <SiteFooter />
    </div>
  );
}
