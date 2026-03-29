import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080"}/api/:path*`,
      },
      {
        source: "/simulator/:path*",
        destination: `${process.env.NEXT_PUBLIC_SIMULATOR_URL || "http://localhost:8081"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
