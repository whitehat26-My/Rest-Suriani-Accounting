import type { Config } from "tailwindcss";

/**
 * Two themes, one config.
 *
 * Colours are declared as CSS custom properties in `app/globals.css` and read
 * here through `var(...)`, so `.theme-owner` and `.theme-accountant` can swap
 * the whole palette without any component knowing which mode it is in.
 *
 * The chart series colours are the validated data-visualisation palette; they
 * are fixed per mode rather than themed freely, because their separation under
 * colour-vision deficiency was measured, not chosen by eye.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          base: "var(--surface-base)",
          raised: "var(--surface-raised)",
          sunken: "var(--surface-sunken)",
          border: "var(--surface-border)",
        },
        ink: {
          primary: "var(--text-primary)",
          secondary: "var(--text-secondary)",
          muted: "var(--text-muted)",
          inverse: "var(--text-inverse)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          soft: "var(--accent-soft)",
          glow: "var(--accent-glow)",
        },
        status: {
          good: "var(--status-good)",
          warning: "var(--status-warning)",
          serious: "var(--status-serious)",
          critical: "var(--status-critical)",
        },
        series: {
          1: "var(--series-1)",
          2: "var(--series-2)",
          3: "var(--series-3)",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        // Grandma Mode never uses anything below `lg`.
        huge: ["clamp(2.25rem, 7.5vw, 4rem)", { lineHeight: "1", letterSpacing: "-0.03em" }],
        giant: ["clamp(2.75rem, 11vw, 5rem)", { lineHeight: "0.95", letterSpacing: "-0.04em" }],
      },
      borderRadius: {
        xl2: "1.25rem",
        xl3: "1.75rem",
      },
      boxShadow: {
        glow: "0 0 0 1px var(--accent-soft), 0 8px 40px -8px var(--accent-glow)",
        lift: "0 12px 32px -12px rgba(4, 10, 24, 0.45)",
        press: "inset 0 3px 0 0 rgba(0, 0, 0, 0.18)",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-1000px 0" },
          "100%": { backgroundPosition: "1000px 0" },
        },
        pulseRing: {
          "0%": { transform: "scale(0.95)", opacity: "0.7" },
          "70%": { transform: "scale(1.25)", opacity: "0" },
          "100%": { transform: "scale(0.95)", opacity: "0" },
        },
        driftGrid: {
          "0%": { transform: "translateY(0)" },
          "100%": { transform: "translateY(-48px)" },
        },
      },
      animation: {
        shimmer: "shimmer 2.4s linear infinite",
        pulseRing: "pulseRing 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        driftGrid: "driftGrid 18s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
