/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        base: "#0c0d10",
        surface: "#15171c",
        "surface-hover": "#1c2026",
        border: "#232731",
        "text-primary": "#e6e8ec",
        "text-muted": "#707788",
        green: "#00c076",
        red: "#f23645",
        accent: "#2962ff",
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
