import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const vitePackage = require("vite/package.json") as { version?: string };
const configDir = path.dirname(fileURLToPath(import.meta.url));

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

function normalizeBuildHash(value: string | undefined) {
  return (value || "").trim().replace(/[^0-9A-Za-z._-]/g, "").slice(0, 16);
}

function addFileToBuildHash(hash: ReturnType<typeof createHash>, filePath: string, relativePath: string) {
  hash.update(relativePath);
  hash.update("\0");
  hash.update(readFileSync(filePath));
  hash.update("\0");
}

function addDirectoryToBuildHash(hash: ReturnType<typeof createHash>, directoryPath: string, relativeRoot: string) {
  const entries = readdirSync(directoryPath, { withFileTypes: true }).sort((left, right) =>
    left.name.localeCompare(right.name),
  );
  for (const entry of entries) {
    const entryPath = path.join(directoryPath, entry.name);
    const relativePath = path.join(relativeRoot, entry.name).split(path.sep).join("/");
    if (entry.isDirectory()) {
      addDirectoryToBuildHash(hash, entryPath, relativePath);
    } else if (entry.isFile()) {
      addFileToBuildHash(hash, entryPath, relativePath);
    }
  }
}

function buildContentHash() {
  const hash = createHash("sha256");
  for (const fileName of ["index.html", "package.json", "package-lock.json", "tsconfig.json", "vite.config.ts"]) {
    const filePath = path.join(configDir, fileName);
    try {
      if (statSync(filePath).isFile()) addFileToBuildHash(hash, filePath, fileName);
    } catch {
      // Optional build inputs are skipped when absent.
    }
  }
  for (const directoryName of ["public", "src"]) {
    const directoryPath = path.join(configDir, directoryName);
    try {
      if (statSync(directoryPath).isDirectory()) addDirectoryToBuildHash(hash, directoryPath, directoryName);
    } catch {
      // Optional build input directories are skipped when absent.
    }
  }
  return hash.digest("hex").slice(0, 12);
}

const buildInstant = new Date();
const buildDate = normalizeBuildDate(process.env.MEDUSA_BUILD_DATE, buildDateStamp(buildInstant));
const buildHash = normalizeBuildHash(process.env.MEDUSA_BUILD_HASH) || buildContentHash();
const buildVersion = (process.env.MEDUSA_BUILD_VERSION || "").trim() || `${buildDate} (${buildHash})`;
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
        timeout: 300_000,
        proxyTimeout: 300_000,
      },
    },
  },
});
