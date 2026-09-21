import createMDX from "@next/mdx";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The about page is written in MDX.
  pageExtensions: ["ts", "tsx", "md", "mdx"],

  // Dev is opened from another machine through the Caddy proxy on the tailnet
  // name (scripts/dev/Caddyfile.devsicap). Without this the dev server refuses
  // HMR and dev-asset requests from that origin.
  allowedDevOrigins: ["devsicap.ts.sicap.ai", "devsicap", "100.77.15.4"],

  // The Pydantic AI agent runs as its own process. Proxying it keeps the
  // browser on one origin, so there is no CORS to configure.
  rewrites() {
    const agentUrl = process.env.AGENT_URL ?? "http://127.0.0.1:8000";

    return [{ source: "/api/agent/:path*", destination: `${agentUrl}/:path*` }];
  },
};

const withMDX = createMDX({});

export default withMDX(nextConfig);
