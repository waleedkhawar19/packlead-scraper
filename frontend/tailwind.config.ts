import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          50: "#f2f6fb", 100: "#e1eaf5", 200: "#c2d4ea", 300: "#93b2d8", 400: "#5d89c0",
          500: "#3a6aa5", 600: "#2d5385", 700: "#254369", 800: "#1b3250", 900: "#0f2a4a", 950: "#0a1d35",
        },
        brand: { 50: "#eff6ff", 100: "#dbeafe", 200: "#bfdbfe", 400: "#60a5fa", 500: "#3b82f6", 600: "#2563eb", 700: "#1d4ed8" },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
      },
      boxShadow: { card: "0 1px 2px rgba(15,42,74,.06), 0 1px 3px rgba(15,42,74,.08)" },
    },
  },
  plugins: [],
};

export default config;
