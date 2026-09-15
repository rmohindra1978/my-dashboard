/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { 50: "#eef6ff", 100: "#d9eaff", 500: "#1e6fd9", 600: "#155bb5", 700: "#124a91", 900: "#0b2b52" },
      },
    },
  },
  plugins: [],
};
