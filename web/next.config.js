/** @type {import('next').NextConfig} */

const nextConfig = {
  experimental: { proxyTimeout: 330_000 },
  // Rewrites proxy to Presenton can reuse stale sockets after large uploads.
  // Disable keep-alive on the server agent to avoid ECONNRESET/socket hang up
  // between the edunote frontend container and the presenton service.
  httpAgentOptions: {
    keepAlive: false,
  },

  // Move dev indicator to bottom-right corner
  devIndicators: {
    position: "bottom-right",
  },

  // Transpile mermaid and related packages for proper ESM handling
  transpilePackages: ["mermaid"],

  // Turbopack configuration (Next.js 16+ uses Turbopack by default for dev)
  turbopack: {
    resolveAlias: {
      // Fix for mermaid's cytoscape dependency - use CJS version
      cytoscape: "cytoscape/dist/cytoscape.cjs.js",
    },
  },

  // Webpack configuration (used for production builds - next build)
  webpack: (config) => {
    const path = require("path");
    config.resolve.alias = {
      ...config.resolve.alias,
      cytoscape: path.resolve(
        __dirname,
        "node_modules/cytoscape/dist/cytoscape.cjs.js",
      ),
    };
    return config;
  },

    async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8001/api/:path*'
      }
    ];
  },
};

module.exports = nextConfig;
