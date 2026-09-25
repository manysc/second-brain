import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    // topic image uploads go through a Server Action; the 1 MB default is too small for the 5 MB image
    // limit enforced by the backend (the extra headroom covers multipart overhead)
    serverActions: { bodySizeLimit: "6mb" },
  },
};

export default nextConfig;
