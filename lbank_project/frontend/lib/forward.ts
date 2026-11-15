"use client";
import { useEffect, useState } from "react";

/** The public forward-test summary: index and percentages only, never account size or anything about trades. */
export type ForwardBot = {
  id: "falcon" | "wave_rider" | "phoenix";
  name_fa: string;
  name_en: string;
  trades: number;
  win_rate_pct: number | null;
  contribution_pct: number;
};
export type ForwardData = {
  available: boolean;
  collecting?: boolean;
  days?: number;
  start_date?: string;
  data_through?: string;
  computed_at?: string;
  equity_basis?: "mark_to_market" | "realized";
  current_index?: number;
  total_return_pct?: number;
  max_drawdown_pct?: number;
  trades?: number;
  win_rate_pct?: number | null;
  profit_factor?: number | null;
  best_day_pct?: number | null;
  worst_day_pct?: number | null;
  series?: { d: string; v: number }[];
  monthly?: { m: string; r: number }[];
  bots?: ForwardBot[];
};

/** null while loading, then the summary (or {available:false} when the request fails). */
export function useForwardTest(): ForwardData | null {
  const [data, setData] = useState<ForwardData | null>(null);
  useEffect(() => {
    let current = true;
    fetch("/api/forward-test", { credentials: "omit" })
      .then((r) => {
        if (!r.ok) throw Error("Unavailable");
        return r.json();
      })
      .then((d) => {
        if (current) setData(d);
      })
      .catch(() => {
        if (current) setData({ available: false });
      });
    return () => {
      current = false;
    };
  }, []);
  return data;
}

export type Point = { d: string; v: number };

/** SVG path and scale for a line of points in a width x height box with padding; the start index 100 is included. */
export function linePath(
  points: Point[],
  width: number,
  height: number,
  pad: { l: number; r: number; t: number; b: number },
) {
  const values = points.map((p) => p.v);
  const lo = Math.min(...values),
    hi = Math.max(...values);
  const span = hi - lo || 1,
    min = lo - span * 0.1,
    max = hi + span * 0.1;
  const iw = width - pad.l - pad.r,
    ih = height - pad.t - pad.b;
  const x = (i: number) =>
    pad.l + (points.length > 1 ? (i / (points.length - 1)) * iw : iw / 2);
  const y = (v: number) => pad.t + ih * (1 - (v - min) / (max - min));
  const d = points
    .map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + "," + y(p.v).toFixed(1))
    .join(" ");
  return { d, x, y, min, max };
}

/** The curve with the 100 starting point prepended, dated the day before the first full day. */
export function withStart(data: ForwardData): Point[] {
  const series = data.series ?? [];
  if (!series.length) return [];
  const first = new Date(series[0].d + "T00:00:00Z");
  first.setUTCDate(first.getUTCDate() - 1);
  return [{ d: first.toISOString().slice(0, 10), v: 100 }, ...series];
}
