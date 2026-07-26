/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // A production build writes the same directory `next dev` serves from, so building while a
  // dev server is up replaces the chunk graph underneath it and the page starts failing with
  // "Cannot find module './471.js'". `pnpm build:check` points this at a scratch directory so
  // a build can be verified without disturbing anyone's running server.
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
