import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // AURA brand colors
        aura: {
          primary: "#6366f1",    // Indigo
          secondary: "#8b5cf6",  // Purple
          accent: "#22d3ee",     // Cyan
          dark: "#0f172a",       // Slate 900
          light: "#f1f5f9",      // Slate 100
        },
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "spin-slow": "spin 3s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
