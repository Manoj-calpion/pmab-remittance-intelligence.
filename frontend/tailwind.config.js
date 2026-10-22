/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        canvas: "var(--canvas)",
        inset: "var(--inset)",
        panel: "var(--panel)",
        foam: "var(--foam)",
        mist: "var(--mist)",
        faint: "var(--faint)",
        line: "var(--line)",
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "sans-serif"],
        display: ["Instrument Serif", "Times New Roman", "serif"],
        mono: ["JetBrains Mono", "Consolas", "monospace"],
      },
      boxShadow: {
        lift: "0 18px 50px rgba(0,0,0,0.28)",
      },
    },
  },
  plugins: [],
};
