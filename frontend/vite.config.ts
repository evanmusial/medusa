import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const vitePackage = require("vite/package.json") as { version?: string };

function pad2(value: number) {
  return value.toString().padStart(2, "0");
}

function buildTimestamp(date = new Date()) {
  return `${date.getFullYear()}.${pad2(date.getMonth() + 1)}.${pad2(date.getDate())}-${pad2(date.getHours())}${pad2(date.getMinutes())}`;
}

const buildVersion = process.env.MEDUSA_BUILD_DATE || buildTimestamp();
const frontendNodeVersion = process.version;
const frontendViteVersion = vitePackage.version || "unknown";
const allowedHosts = (process.env.MEDUSA_ALLOWED_HOSTS || "medusa.home.musial.io")
  .split(",")
  .map((host) => host.trim())
  .filter(Boolean);

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          xyflow: ["@xyflow/react"],
        },
      },
    },
  },
  define: {
    "import.meta.env.VITE_MEDUSA_BUILD_VERSION": JSON.stringify(buildVersion),
    "import.meta.env.VITE_MEDUSA_FRONTEND_NODE_VERSION": JSON.stringify(frontendNodeVersion),
    "import.meta.env.VITE_MEDUSA_FRONTEND_VITE_VERSION": JSON.stringify(frontendViteVersion),
  },
  server: {
    allowedHosts,
    host: "0.0.0.0",
    port: 3737,
    proxy: {
      "/api": {
        target: process.env.MEDUSA_API_PROXY || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
