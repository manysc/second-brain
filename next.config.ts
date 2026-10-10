import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // dev-only: lets the app be opened at 127.0.0.1 (preferred over localhost on this setup, see CLAUDE.md) without
  // the dev server refusing its own client assets, which leaves pages unhydrated
  allowedDevOrigins: ["127.0.0.1"],
  experimental: {
    // topic image uploads go through a Server Action; the 1 MB default is too small for the 5 MB image
    // limit enforced by the backend (the extra headroom covers multipart overhead)
    serverActions: { bodySizeLimit: "6mb" },
  },
};

export default nextConfig;
