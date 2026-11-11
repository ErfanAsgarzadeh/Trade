import type { NextConfig } from "next";
const development = process.env.NODE_ENV === "development";
const config: NextConfig = {
  output: "export",
  poweredByHeader: false,
  reactStrictMode: true,
  images: { unoptimized: true },
  // Production is served by FastAPI. Next dev proxies API requests on the same origin.
  ...(development
    ? {
        rewrites: async () => [
          {
            source: "/api/:path*",
            destination: "http://127.0.0.1:8080/api/:path*",
          },
        ],
      }
    : {}),
};
export default config;
