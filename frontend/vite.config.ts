import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const vitePackage = require("vite/package.json") as { version?: string };

function pad2(value: number) {
  return value.toString().padStart(2, "0");
}

function buildDateStamp(date = new Date()) {
  return `${date.getFullYear()}${pad2(date.getMonth() + 1)}${pad2(date.getDate())}`;
}

function normalizeBuildDate(value: string | undefined, fallback: string) {
  const cleaned = (value || "").trim();
  if (!cleaned) return fallback;
  const digits = cleaned.replace(/\D/g, "");
  return digits.length >= 8 ? digits.slice(0, 8) : cleaned;
}

const buildInstant = new Date();
const buildDate = normalizeBuildDate(process.env.MEDUSA_BUILD_DATE, buildDateStamp(buildInstant));
const buildNumber = (process.env.MEDUSA_BUILD_NUMBER || `${pad2(buildInstant.getHours())}${pad2(buildInstant.getMinutes())}`).trim();
const buildVersion = buildNumber ? `${buildDate} (${buildNumber})` : buildDate;
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
