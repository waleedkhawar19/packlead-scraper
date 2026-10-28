/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // NEXT_PUBLIC_API_URL is read at build time and is the only backend setting the browser sees.
  // No secrets belong in the frontend: it only ever talks to the public API URL.
};

module.exports = nextConfig;
