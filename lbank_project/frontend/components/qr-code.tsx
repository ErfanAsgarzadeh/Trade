"use client";
import qrcode from "qrcode-generator";
import { useMemo } from "react";

/** A QR code drawn as SVG squares (no inline script or style, so it fits the site's CSP). */
export default function QrCode({
  value,
  label,
}: {
  value: string;
  label: string;
}) {
  const cells = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(value);
    qr.make();
    const count = qr.getModuleCount(),
      dark: [number, number][] = [];
    for (let r = 0; r < count; r++)
      for (let c = 0; c < count; c++) if (qr.isDark(r, c)) dark.push([r, c]);
    return { count, dark };
  }, [value]);
  const size = cells.count + 8;
  return (
    <svg
      className="qr-code"
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={label}
      shapeRendering="crispEdges"
    >
      <rect width={size} height={size} fill="#ffffff" />
      <path
        fill="#100424"
        d={cells.dark.map(([r, c]) => `M${c + 4},${r + 4}h1v1h-1z`).join("")}
      />
    </svg>
  );
}
