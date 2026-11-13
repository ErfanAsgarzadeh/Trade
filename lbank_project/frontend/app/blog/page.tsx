import type { Metadata } from "next";
import { PostCard } from "@/components/landing";
import { SiteFooter, SiteHeader } from "@/components/site-chrome";
import { allPosts } from "@/lib/blog";

const title = "بلاگ آوینا | آموزش ربات ترید، حد ضرر و مدیریت ریسک";
const description =
  "مقاله‌های آموزشی آوینا دربارهٔ ربات معامله‌گر ارز دیجیتال، معاملات فیوچرز، حد ضرر، مدیریت ریسک و خواندن نتایج بک‌تست.";
export const metadata: Metadata = {
  title,
  description,
  openGraph: { title, description, type: "website" },
  twitter: { title, description },
};

export default function BlogIndex() {
  const posts = allPosts();
  return (
    <div className="landing blog-page">
      <a className="skip-link" href="#blog-main">
        رفتن به محتوا
      </a>
      <SiteHeader />
      <main id="blog-main">
        <section className="blog-hero" aria-labelledby="blog-title">
          <span className="eyebrow">AVINA JOURNAL</span>
          <h1 id="blog-title">بلاگ آوینا</h1>
          <p>
            راهنماهای کوتاه و بی‌تعارف دربارهٔ ربات ترید، معاملات فیوچرز، حد ضرر
            و مدیریت ریسک؛ برای اینکه پیش از سپردن معامله به هر ربات، بدانید چه
            چیزی را باید بسنجید.
          </p>
        </section>
        <div className="blog-cards blog-list">
          {posts.map((post) => (
            <PostCard key={post.slug} post={post} />
          ))}
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
