import { effectiveNow } from "./simulated_date";

/** Format an amount in millionths of a dollar as a currency string. */
export function formatCurrency(millionths: number): string {
    const dollars = millionths / 1_000_000;
    return dollars.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

/** Parse a currency input string to millionths of a dollar. */
export function parseCurrencyInput(input: string): number | null {
    const cleaned = input.replace(/[$,\s]/g, "");
    const value = parseFloat(cleaned);
    if (isNaN(value)) return null;
    return Math.round(value * 1_000_000);
}

/** Get the current YYYY-MM string in BUDGET_TZ (America/New_York).
 *
 * The budget anchors in ET per the architecture spec. Using local-time
 * `getMonth()` would shift the answer by up to a day for users in any
 * negative-offset timezone — wrong on the 1st of every month for east-of-UTC
 * users, and especially wrong under simulation (date pickers think in days,
 * not UTC instants). Respects the dev-only simulated date via `effectiveNow`.
 */
export function currentYearMonth(): string {
    const fmt = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        year: "numeric",
        month: "2-digit",
    });
    const parts = fmt.formatToParts(effectiveNow());
    const year = parts.find((p) => p.type === "year")?.value ?? "";
    const month = parts.find((p) => p.type === "month")?.value ?? "";
    return `${year}-${month}`;
}

/** Format YYYY-MM as a readable month string. */
export function formatYearMonth(yearMonth: string): string {
    const [year, month] = yearMonth.split("-");
    const date = new Date(parseInt(year), parseInt(month) - 1);
    return date.toLocaleDateString("en-US", { year: "numeric", month: "long" });
}

/** Get the previous YYYY-MM. */
export function prevYearMonth(yearMonth: string): string {
    const [year, month] = yearMonth.split("-").map(Number);
    const date = new Date(year, month - 2);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

/** Get the next YYYY-MM. */
export function nextYearMonth(yearMonth: string): string {
    const [year, month] = yearMonth.split("-").map(Number);
    const date = new Date(year, month);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

/** Compare two YYYY-MM strings. Returns "past", "current", or "future" relative to the current month. */
export function monthTense(yearMonth: string): "past" | "current" | "future" {
    const current = currentYearMonth();
    if (yearMonth < current) return "past";
    if (yearMonth === current) return "current";
    return "future";
}
