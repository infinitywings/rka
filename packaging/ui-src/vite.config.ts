import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    target: "esnext",
    sourcemap: true,
    // Leave dist/.gitkeep alone so fresh clones can `cargo check` Tauri
    // before running `npm run build`. Stale .js bundles in dist/ get
    // overwritten on the next build; only the committed .gitkeep is
    // protected by leaving the directory non-empty.
    emptyOutDir: false,
  },
});
