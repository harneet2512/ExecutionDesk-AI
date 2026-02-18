const backend = process.env.BACKEND_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  rewrites: async () => [
    {
      source: "/api/v1/:path*",
      destination: `${backend}/api/v1/:path*`,
    },
  ],
}

module.exports = nextConfig
