"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import snapshot from "@/public/backtest/five-year-summary.json";
import { money, percent } from "@/lib/format";
import { useLang } from "@/lib/lang";

const W = 760,
  H = 390,
  LEFT = 72,
  RIGHT = 28,
  TOP = 32,
  BOTTOM = 46,
  // Five years replay in a few seconds; reduced-motion users get the final frame.
  DURATION = 4200;
export default function BacktestMotion() {
  const { lang, t } = useLang();
  const usd = (value: number) => money(value, lang);
  const container = useRef<HTMLDivElement>(null),
    [progress, setProgress] = useState(1),
    [playing, setPlaying] = useState(false),
    [reduced, setReduced] = useState(false);
  const elapsed = useRef(0);
  const geometry = useMemo(() => {
    const points: [[string, number], ...[string, number][]] = [
      ["2021-01-01", snapshot.initial],
      ...snapshot.daily.map(
        ([date, value]) => [String(date), Number(value)] as [string, number],
      ),
    ];
    const low = Math.log10(snapshot.initial),
      high = Math.log10(Math.max(...points.map((p) => p[1])) * 1.12),
      width = W - LEFT - RIGHT,
      height = H - TOP - BOTTOM;
    const y = (value: number) =>
      TOP + height * (1 - (Math.log10(value) - low) / (high - low));
    const xy = points.map((p, i) => ({
      x: LEFT + (i / (points.length - 1)) * width,
      y: y(p[1]),
      value: p[1],
      date: p[0],
    }));
    const path = xy
      .map((p, i) => (i ? "L" : "M") + p.x.toFixed(2) + "," + p.y.toFixed(2))
      .join(" ");
    return {
      xy,
      path,
      width,
      height,
      y,
      area: path + ` L${W - RIGHT},${H - BOTTOM} L${LEFT},${H - BOTTOM} Z`,
    };
  }, []);
  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(preference.matches);
    const change = () => {
      setReduced(preference.matches);
      if (preference.matches) {
        setPlaying(false);
        setProgress(1);
        elapsed.current = DURATION;
      }
    };
    preference.addEventListener("change", change);
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          if (!preference.matches) {
            elapsed.current = 0;
            setProgress(0);
            setPlaying(true);
          }
          observer.disconnect();
        }
      },
      { threshold: 0.2 },
    );
    if (container.current) observer.observe(container.current);
    const hidden = () => {
      if (document.hidden) setPlaying(false);
    };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      observer.disconnect();
      preference.removeEventListener("change", change);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  useEffect(() => {
    if (!playing) return;
    let frame = 0,
      previous: number | undefined;
    const tick = (time: number) => {
      if (previous !== undefined)
        elapsed.current = Math.min(DURATION, elapsed.current + time - previous);
      previous = time;
      setProgress(elapsed.current / DURATION);
      if (elapsed.current < DURATION) frame = requestAnimationFrame(tick);
      else setPlaying(false);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);
  const point =
    geometry.xy[
      Math.min(
        geometry.xy.length - 1,
        Math.floor(progress * (geometry.xy.length - 1)),
      )
    ];
  const ticks = [10000, 50000, 100000, 500000, 1000000].filter(
    (v) => geometry.y(v) >= TOP,
  );
  const toggle = () => {
    if (playing) {
      setPlaying(false);
      return;
    }
    if (progress >= 1) {
      elapsed.current = 0;
      setProgress(0);
    }
    setPlaying(true);
  };
  return (
    <div
      ref={container}
      id="backtest-motion"
      className="replay-card"
      data-motion={playing ? "playing" : "paused"}
      data-reduced-motion={reduced ? "true" : "false"}
    >
      <div className="replay-top">
        <div className="replay-brand">
          <span className="replay-dot" />
          BACKTEST REPLAY
        </div>
        <span className="replay-tag">
          {t("شبیه‌سازی تاریخی", "Historical simulation")}
        </span>
      </div>
      <div className="replay-value">
        <div>
          <span>{t("ارزش حساب در بازپخش", "Account value in replay")}</span>
          <strong id="replay-equity">{usd(point.value)}</strong>
        </div>
        <span className="replay-date" dir="ltr">
          {point.date}
        </span>
      </div>
      <svg
        className="equity-motion"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-labelledby="equity-chart-title equity-chart-description"
      >
        <title id="equity-chart-title">
          {t(
            "رشد سرمایهٔ شبیه‌سازی‌شده از ۱۰٬۰۰۰ تا ۹۶۴٬۴۵۲ دلار، سال‌های ۲۰۲۱ تا ۲۰۲۵",
            "Simulated growth from $10,000 to $964,452, 2021 to 2025",
          )}
        </title>
        <desc id="equity-chart-description">
          {t(
            "منحنی ارزش پایان روز روی محور لگاریتمی، سه ربات روی یک حساب و بدون برداشت. بیشترین افت سرمایهٔ دقیقه‌ای ۳۰٫۷٪ بوده است.",
            "End-of-day value on a log scale, three bots on one account, no withdrawals. The largest minute drawdown was 30.7%.",
          )}
        </desc>
        <defs>
          <linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-fill)" stopOpacity=".24" />
            <stop offset="100%" stopColor="var(--chart-fill)" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="equity-stroke">
            <stop stopColor="var(--chart-indicator)" />
            <stop offset="100%" stopColor="var(--chart-equity)" />
          </linearGradient>
          <clipPath id="replay-clip">
            <rect
              x={LEFT}
              y={TOP - 4}
              width={geometry.width * progress + 1}
              height={geometry.height + 8}
            />
          </clipPath>
          <filter id="point-glow">
            <feGaussianBlur stdDeviation="4" />
          </filter>
        </defs>
        {ticks.map((value) => (
          <g key={value}>
            <line
              x1={LEFT}
              y1={geometry.y(value)}
              x2={W - RIGHT}
              y2={geometry.y(value)}
              className="chart-grid"
            />
            <text
              x={LEFT - 12}
              y={geometry.y(value) + 4}
              textAnchor="end"
              className="chart-axis"
            >
              {value >= 1000000 ? "$1m" : "$" + value / 1000 + "k"}
            </text>
          </g>
        ))}
        {[2021, 2022, 2023, 2024, 2025].map((year, index) => {
          const x = LEFT + (index / 5) * geometry.width;
          return (
            <g key={year}>
              <line
                x1={x}
                y1={TOP}
                x2={x}
                y2={H - BOTTOM}
                className="chart-grid vertical"
              />
              <text x={x} y={H - 15} textAnchor="middle" className="chart-axis">
                {year}
              </text>
            </g>
          );
        })}
        <g clipPath="url(#replay-clip)">
          <path d={geometry.area} fill="url(#equity-fill)" />
          <path
            d={geometry.path}
            className="actual-equity-line"
            fill="none"
            stroke="url(#equity-stroke)"
            strokeWidth="2.3"
            vectorEffect="non-scaling-stroke"
          />
        </g>
        <line
          x1={point.x}
          y1={TOP}
          x2={point.x}
          y2={H - BOTTOM}
          className="chart-cursor"
        />
        <circle
          cx={point.x}
          cy={point.y}
          r="10"
          fill="var(--chart-fill)"
          opacity=".55"
          filter="url(#point-glow)"
        />
        <circle
          cx={point.x}
          cy={point.y}
          r="4.5"
          fill="var(--chart-marker)"
          stroke="var(--chart-background)"
          strokeWidth="2"
        />
      </svg>
      <div className="replay-controls">
        <span>
          {t(
            "ارزش پایان روز · مقیاس لگاریتمی · دلار",
            "End-of-day value · log scale · USD",
          )}
        </span>
        <button
          id="toggle-backtest-motion"
          onClick={toggle}
          aria-pressed={playing}
        >
          {playing
            ? t("توقف", "Pause")
            : progress >= 1
              ? t("پخش دوباره", "Replay")
              : t("ادامه", "Resume")}
        </button>
      </div>
      <div className="replay-bottom">
        <div>
          <span>{t("سرمایهٔ اولیه", "Starting capital")}</span>
          <strong>{usd(snapshot.initial)}</strong>
        </div>
        <div>
          <span>{t("ارزش پایان پنج سال", "Value after five years")}</span>
          <strong>{usd(Math.round(snapshot.final))}</strong>
        </div>
        <div>
          <span>{t("رشد سالانهٔ مرکب", "CAGR")}</span>
          <strong>{percent(snapshot.cagr_pct, lang)}</strong>
        </div>
        <div className="replay-dd">
          <span>{t("بیشترین افت دقیقه‌ای", "Max minute drawdown")}</span>
          <strong>{percent(snapshot.max_minute_dd_pct, lang)}</strong>
        </div>
      </div>
      <div className="replay-ornament" aria-hidden="true" />
    </div>
  );
}
