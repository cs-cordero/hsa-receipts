/**
 * Dev-only date simulation: lets the user pretend the current date is somewhere
 * else (e.g. December next year) without changing system time. The frontend
 * stores the chosen date in localStorage and attaches it to every API request
 * as `X-Simulated-Date`. The backend honors the header in non-prod stages.
 *
 * Prod absolutely ignores the header. Treat any data written under simulation
 * as a real DB write — densification, pins, etc. will fire as if it were that
 * day. Reset/clear via `clearSimulatedDate()` (or the UI button).
 */

import { IS_DEV } from "./dev";

const KEY = "personalFinance.simulatedDate";

export function getSimulatedDate(): string | null {
    if (!IS_DEV) return null;
    try {
        const v = window.localStorage.getItem(KEY);
        return v && v.length > 0 ? v : null;
    } catch {
        return null;
    }
}

export function setSimulatedDate(value: string): void {
    if (!IS_DEV) return;
    try {
        window.localStorage.setItem(KEY, value);
        // Reload so every page re-fetches with the new simulated date in effect.
        window.location.reload();
    } catch {
        /* ignore */
    }
}

export function clearSimulatedDate(): void {
    if (!IS_DEV) return;
    try {
        window.localStorage.removeItem(KEY);
        window.location.reload();
    } catch {
        /* ignore */
    }
}

/**
 * Effective "now" Date, honoring the simulated date when set. Anything that asks
 * "what year-month is it?" or computes editability should call this instead of
 * `new Date()` directly so UI hints match the backend's view.
 *
 * Sim dates are anchored at noon UTC, not midnight. Midnight UTC of a given date
 * lands on the previous calendar day in any negative-offset timezone (e.g. EDT
 * is UTC-4 so midnight UTC = 8pm ET the previous day). Noon UTC sits comfortably
 * inside the simulated calendar day everywhere from UTC-11 through UTC+11, so
 * "I picked Aug 1" means Aug 1 in every relevant timezone — including ET, which
 * the budget anchors in per the architecture spec.
 */
export function effectiveNow(): Date {
    const sim = getSimulatedDate();
    if (sim) {
        const parsed = new Date(`${sim}T12:00:00Z`);
        if (!Number.isNaN(parsed.getTime())) return parsed;
    }
    return new Date();
}
