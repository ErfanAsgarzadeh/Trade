"use client";
import { useEffect, useState } from "react";
import { faNumber } from "@/lib/format";

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
  const [posts, setPosts] = useState<LatestPost[] | null>(null);
  useEffect(() => {
    let current = true;
    fetch("/api/blog/latest?limit=3", {
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
  }, []);
  if (posts && posts.length === 0)
    return (
      <p>
        <a href="/blog/">بلاگ آوینا را ببینید ←</a>
      </p>
    );
  return (
    <div className="blog-cards" aria-busy={posts === null}>
      {(posts ?? []).map((post) => (
        <article className="blog-card" key={post.slug}>
          <small>
            <time dateTime={post.published_on}>{post.date_label}</time>
            <span aria-hidden="true">·</span>
            <span>{faNumber(post.minutes)} دقیقه مطالعه</span>
          </small>
          <h3>
            <a href={`/blog/${post.slug}/`}>{post.title}</a>
          </h3>
          <p>{post.description}</p>
        </article>
      ))}
    </div>
  );
}
