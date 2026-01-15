import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/netfilm-chill.github.io/",
  plugins: [react()],
});
