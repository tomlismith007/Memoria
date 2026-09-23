/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#FAFAF9",
        surface: "#FFFFFF",
        subtle: "#F4F4F5",
        ink: {
          primary: "#18181B",
          muted: "#71717A",
          faint: "#A1A1AA",
        },
        whisper: "#E4E4E7",
        wiki: {
          bg: "#ECFDF5",
          text: "#047857",
          border: "rgba(167, 243, 208, 0.6)",
        },
        citation: {
          bg: "#EFF6FF",
          text: "#1D4ED8",
          border: "rgba(191, 219, 254, 0.6)",
        },
        shield: {
          bg: "#FFFBEB",
          text: "#92400E",
          border: "rgba(253, 230, 138, 0.8)",
        },
        burn: {
          bg: "#FEF2F2",
          text: "#B91C1C",
          border: "rgba(254, 202, 202, 0.6)",
        },
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.5rem",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "SF Mono",
          "JetBrains Mono",
          "monospace",
        ],
      },
    },
  },
  plugins: [],
};
