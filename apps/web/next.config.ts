import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Workspace packages ship TypeScript/TSX source; Next compiles them.
  transpilePackages: ["@ngsirs/contracts", "@ngsirs/design"],
  poweredByHeader: false,
  // No telemetry, analytics or remote assets: the console only talks to the NGSIRS API.
  images: { unoptimized: true },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;
