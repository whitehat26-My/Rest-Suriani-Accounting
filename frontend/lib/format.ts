/** Formatting helpers shared by both interfaces. */

export const CURRENCY = "RM";

/** "RM1,234.50". Grandma Mode never shows a number without its currency. */
export function money(value: number | string | null | undefined): string {
  const amount = toNumber(value);
  return `${CURRENCY}${amount.toLocaleString("en-MY", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** "RM1,235" - used where the cents would only add noise, e.g. axis ticks. */
export function moneyShort(value: number | string | null | undefined): string {
  const amount = toNumber(value);
  if (Math.abs(amount) >= 1000) {
    return `${CURRENCY}${(amount / 1000).toFixed(1)}k`;
  }
  return `${CURRENCY}${Math.round(amount)}`;
}

export function toNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === "number" ? value : Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "n/a";
  return `${value.toFixed(digits)}%`;
}

/** "19 Aug" - short enough for an axis, unambiguous for a person. */
export function shortDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  return date.toLocaleDateString("en-MY", { day: "numeric", month: "short" });
}

/** "Tuesday, 19 August 2026" - the owner's screen spells it out. */
export function longDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  return date.toLocaleDateString("en-MY", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function todayIso(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

/** Maps a backend rating to a CSS colour variable. */
export function ratingColor(rating: string): string {
  switch (rating) {
    case "good":
    case "positive":
      return "var(--status-good)";
    case "watch":
    case "warning":
      return "var(--status-warning)";
    case "serious":
      return "var(--status-serious)";
    case "bad":
    case "critical":
      return "var(--status-critical)";
    default:
      return "var(--text-muted)";
  }
}

/**
 * Status colours never travel alone - each one ships with a glyph and a word,
 * so meaning survives colour-blindness, a photocopier and a bright kitchen.
 */
export function ratingGlyph(rating: string): string {
  switch (rating) {
    case "good":
    case "positive":
      return "✓";
    case "watch":
    case "warning":
      return "△";
    case "serious":
      return "◆";
    case "bad":
    case "critical":
      return "✕";
    default:
      return "•";
  }
}

export function ratingWord(rating: string): string {
  switch (rating) {
    case "good":
      return "Healthy";
    case "positive":
      return "Good news";
    case "watch":
    case "warning":
      return "Watch";
    case "serious":
      return "Serious";
    case "bad":
    case "critical":
      return "Act now";
    default:
      return "No data";
  }
}
