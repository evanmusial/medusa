import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { execSync } from "node:child_process";

function dateStamp(date = new Date()) {
  return date.toISOString().slice(0, 10).replaceAll("-", ".");
}

function gitShortSha() {
  try {
    return execSync("git -C .. rev-parse --short=8 HEAD", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
  } catch {
    return "";
  }
}

const buildDate = process.env.MEDUSA_BUILD_DATE || dateStamp();
const buildSha = process.env.MEDUSA_BUILD_SHA || gitShortSha();
const buildVersion = buildSha ? `${buildDate}+${buildSha}` : buildDate;

export default defineConfig({
  plugins: [react()],
  define: {
    __MEDUSA_BUILD_VERSION__: JSON.stringify(buildVersion),
  },
  server: {
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
