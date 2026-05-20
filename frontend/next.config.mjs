/** @type {import('next').NextConfig} */
const nextConfig = {
  // standalone output is only needed for Docker/production deployments; enabling it
  // in dev causes Next.js to trace and copy all node_modules into .next/standalone,
  // making the dev cache 500MB+ and startup take 10+ minutes.
  ...(process.env.NODE_ENV === "production" ? { output: "standalone" } : {}),

  // lucide-react@1.x ships 3,920 individual ESM icon files; without this, Turbopack
  // follows every re-export in the barrel file and stalls under memory pressure.
  // This transforms `import { Zap } from "lucide-react"` into a direct per-icon import.
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
};

export default nextConfig;
