/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  // Use the `class` strategy: <html class="light"> activates light theme.
  // Default (no class) = dark.
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Map Tailwind color tokens to CSS variables so the same class names
        // work in both themes; the variable VALUES change in index.css.
        bg: {
          900: "var(--lg-bg-900)",
          800: "var(--lg-bg-800)",
          700: "var(--lg-bg-700)",
          600: "var(--lg-bg-600)",
        },
        accent: {
          DEFAULT: "var(--lg-accent)",
          hover:   "var(--lg-accent-hover)",
        },
        ok:   "var(--lg-ok)",
        warn: "var(--lg-warn)",
        err:  "var(--lg-err)",
        // Inverted gray scale so the same Tailwind text class is readable
        // in both themes.
        gray: {
          100: "var(--lg-fg-100)",
          200: "var(--lg-fg-200)",
          300: "var(--lg-fg-300)",
          400: "var(--lg-fg-400)",
          500: "var(--lg-fg-500)",
          600: "var(--lg-fg-600)",
          700: "var(--lg-fg-700)",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
}
