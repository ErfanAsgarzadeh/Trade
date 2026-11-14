"use client";
import { useEffect, useState } from "react";
import { num } from "@/lib/format";
import { useLang } from "@/lib/lang";

type LatestPost = {
  slug: string;
  title: string;
  description: string;
  published_on: string;
  date_label: string;
  minutes: number;
};

// Articles are written in the admin panel, so the landing page reads the latest ones at view time.
export default function LatestPosts() {
  const { lang, t, path } = useLang();
  const [posts, setPosts] = useState<LatestPost[] | null>(null);
  useEffect(() => {
    let current = true;
    fetch(`/api/blog/latest?limit=3&lang=${lang}`, {
      credentials: "omit",
      cache: "no-store",
    })
      .then((r) => {
        if (!r.ok) throw Error("Unavailable");
        return r.json();
      })
      .then((data) => {
        if (current) setPosts(data.items);
      })
      .catch(() => {
        if (current) setPosts([]);
      });
    return () => {
      current = false;
    };
  }, [lang]);
  if (posts && posts.length === 0)
    return (
      <p>
        <a href={path("/blog/")}>{t("بلاگ آوینا را ببینید", "Visit the Avina blog")}</a>
      </p>
    );
  return (
    <div className="blog-cards" aria-busy={posts === null}>
      {(posts ?? []).map((post) => (
        <article className="blog-card" key={post.slug}>
          <small>
            <time dateTime={post.published_on}>{post.date_label}</time>
            <span aria-hidden="true">·</span>
            <span>
              {num(post.minutes, lang)} {t("دقیقه مطالعه", "min read")}
            </span>
          </small>
          <h3>
            <a href={path(`/blog/${post.slug}/`)}>{post.title}</a>
          </h3>
          <p>{post.description}</p>
        </article>
      ))}
    </div>
  );
}
