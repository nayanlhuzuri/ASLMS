import type { NextConfig } from "next";

// Design portal-shell: a standalone server for the Compose image, no X-Powered-By header. Security headers and the
// CSP nonce are set per request in src/proxy.ts.
const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
