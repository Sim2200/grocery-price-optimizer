import type { NextConfig } from "next";

// Production builds are a static export (web/out) that the FastAPI server serves
// as plain files, the same way it served the Vite build. In development, Next
// runs on :5173 and forwards /api calls to the FastAPI server on :8000.
const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  output: isDev ? undefined : "export",
  reactStrictMode: true,
  ...(isDev && {
    async rewrites() {
      return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
    },
  }),
};

export default nextConfig;
