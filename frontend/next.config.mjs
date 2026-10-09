/** @type {import('next').NextConfig} */
const nextConfig = {
  async headers() {
    return [{
      source: "/auth/login",
      headers: [{ key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" }],
    }];
  },
};

export default nextConfig;
