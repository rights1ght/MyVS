/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#070a0e",
          900: "#0b1016",
          850: "#101720",
          800: "#151e29",
          700: "#1e2b38",
        },
        amber: {
          400: "#f5c45e",
          500: "#efb13c",
        },
        mint: {
          300: "#7ee8c8",
          400: "#4ed7b0",
        },
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "-apple-system", "sans-serif"],
        mono: ["Cascadia Code", "SFMono-Regular", "Consolas", "monospace"],
      },
      boxShadow: {
        panel: "0 18px 50px rgba(0,0,0,.22)",
      },
      keyframes: {
        pulseSoft: {
          "0%, 100%": { opacity: "0.45" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        "pulse-soft": "pulseSoft 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
