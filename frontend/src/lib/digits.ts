/**
 * Counts in words for the message catalogue (design portal-ui-kit-fixes, decision 23). A leaf module with no imports:
 * `messages.ts` cannot import `format.ts`, which imports `i18n.ts`, which imports `messages.ts`. `format.ts` uses the
 * same grouping for English and re-exports `plural`.
 */

/** 128400 → "1,28,400" (the Indian grouping); negative numbers and decimals keep their sign and fraction. */
export function groupDigits(value: number): string {
  const negative = value < 0;
  const [whole = "0", fraction] = Math.abs(value).toString().split(".");
  let grouped = whole;
  if (whole.length > 3) {
    const last3 = whole.slice(-3);
    const rest = whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
    grouped = `${rest},${last3}`;
  }
  return `${negative ? "-" : ""}${grouped}${fraction ? "." + fraction : ""}`;
}

/** `plural(123456, "case", "cases")` is "1,23,456 cases": the count grouped and the word for one or many. */
export function plural(n: number, one: string, many: string): string {
  return `${groupDigits(n)} ${n === 1 ? one : many}`;
}
