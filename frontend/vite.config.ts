import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function pad2(value: number) {
  return value.toString().padStart(2, "0");
}

function buildTimestamp(date = new Date()) {
  return `${date.getFullYear()}.${pad2(date.getMonth() + 1)}.${pad2(date.getDate())}-${pad2(date.getHours())}${pad2(date.getMinutes())}`;
}

const buildVersion = process.env.MEDUSA_BUILD_DATE || buildTimestamp();

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
