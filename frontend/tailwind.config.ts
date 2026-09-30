import type { Config } from "tailwindcss";
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        emerald: { DEFAULT: "#0C3B2E", deep: "#0C3B2E", mid: "#14532D", soft: "#E7F0EB", mist: "#F2F7F4" },
        gold: { DEFAULT: "#C89B58", soft: "#F6EEDF" },
        cream: "#FBFAF6",
        ink: "#1C2420",
      },
      boxShadow: { soft: "0 2px 16px rgba(12,59,46,0.07)", lift: "0 8px 30px rgba(12,59,46,0.12)" },
    },
  },
  plugins: [],
};
export default config;
