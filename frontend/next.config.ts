import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: ["@assistant-ui/react", "@assistant-ui/react-ai-sdk"],
};

export default nextConfig;
