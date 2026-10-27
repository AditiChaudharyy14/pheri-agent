import type { NextConfig } from "next";

// The Pheri API (FastAPI, api/pheri/app.py). The browser calls /api/... on this origin and Next.js
// forwards it, so no CORS is needed; server components call the API directly.
const API = process.env.PHERI_API_URL ?? "http://127.0.0.1:8000";

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
  rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/:path*` }];
  },
};

export default nextConfig;
