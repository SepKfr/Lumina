import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// When deployed as "Lumina" at alignmentatlas.online/lumina, set VITE_BASE_PATH=/lumina/
const base = process.env.VITE_BASE_PATH ?? "/lumina/";

export default defineConfig({
  base,
  plugins: [react()],
});
