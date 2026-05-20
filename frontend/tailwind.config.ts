import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#f97316",
          dark: "#ea580c",
          50: "#fff7ed",
          100: "#ffedd5",
        },
        accent: {
          DEFAULT: "#4f46e5",
          dark: "#4338ca",
          50: "#eef2ff",
          100: "#e0e7ff",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 3px 0 rgb(0 0 0 / 0.08), 0 1px 2px -1px rgb(0 0 0 / 0.06)",
        "card-hover": "0 4px 12px 0 rgb(0 0 0 / 0.10), 0 2px 4px -1px rgb(0 0 0 / 0.06)",
        "card-lg": "0 8px 24px 0 rgb(0 0 0 / 0.08), 0 4px 8px -2px rgb(0 0 0 / 0.06)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "new-badge-fade": {
          "0%": { opacity: "1" },
          "70%": { opacity: "1" },
          "100%": { opacity: "0" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.2s ease-out",
        "new-badge-fade": "new-badge-fade 30s ease-out forwards",
      },
    },
  },
  plugins: [],
};

export default config;
