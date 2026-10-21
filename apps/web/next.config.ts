import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The monorepo root holds the shared OpenAPI contract (type-only imports).
  turbopack: { root: path.join(__dirname, "..", "..") },
  outputFileTracingRoot: path.join(__dirname, "..", ".."),
};

export default nextConfig;
