/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          900: "#0a0a0f",
          800: "#13131a",
          700: "#1c1c26",
          600: "#262633",
        },
        accent: {
          DEFAULT: "#7c5cff",
          hover: "#9579ff",
        },
        ok: "#3ddc97",
        warn: "#ffb454",
        err: "#ff5577",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
}
