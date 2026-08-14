import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Relative asset URLs: the bundle is served from package data at /,
  // but never assume a mount point.
  base: "./",
  build: { outDir: "../darwin_memo/data/ui", emptyOutDir: true },
  // Dev server proxies the API to a running `darwin-memo ui`.
  server: { proxy: { "/api": "http://127.0.0.1:8787" } },
});
