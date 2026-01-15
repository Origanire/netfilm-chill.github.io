import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/netfilm-chill.github.io/",
  plugins: [react()],
  server: {
    proxy: {
      "/akinator": {
        target: "http://localhost:5000",
        changeOrigin: true,
      },
      "/moviegrid": {
        target: "http://localhost:5000",
        changeOrigin: true,
      },
      "/blindtest": {
        target: "http://localhost:5000",
        changeOrigin: true,
      },
    },
  },
});
