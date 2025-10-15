import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"], // scan everything under src/
  theme: {
    extend: {},
  },
  plugins: [],
};

export default config;