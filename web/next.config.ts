import type { NextConfig } from "next";

// The Pheri API (FastAPI, api/pheri/app.py), at PHERI_API_URL: server components call it directly, and
// the browser's /api/... calls go through app/api/[...path]/route.ts, which reads the address at run time.

const nextConfig: NextConfig = {
  cacheComponents: true,
  devIndicators: false, // clean screen recordings
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
