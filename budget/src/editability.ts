/**
 * Frontend port of the backend editability state machine. Used for UX hints
 * (lock badges, disabled form controls). The backend is the source of truth —
 * this is only a client-side preview.
 */

import { effectiveNow } from "./simulated_date";

export type EditabilityState = "EDITABLE" | "GRACE" | "LOCKED";

const N_FUTURE_MONTHS = 12;
const GRACE_PERIOD_DAYS = 7;
const BUDGET_TZ = "America/New_York";

interface EtCalendarParts {
    year: number;
    month: number;
    day: number;
}

function nowInEt(now: Date): EtCalendarParts {
    const fmt = new Intl.DateTimeFormat("en-US", {
        timeZone: BUDGET_TZ,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    });
    const parts = fmt.formatToParts(now);
    const lookup = (type: string): number => {
        const part = parts.find((p) => p.type === type);
        if (!part) throw new Error(`Missing ET date part: ${type}`);
        return parseInt(part.value, 10);
    };
    return { year: lookup("year"), month: lookup("month"), day: lookup("day") };
}

function toMonthOrdinal(year: number, month: number): number {
    return year * 12 + (month - 1);
}

function parseYearMonth(ym: string): { year: number; month: number } {
    if (!/^\d{4}-\d{2}$/.test(ym)) {
        throw new Error(`Invalid year-month: ${ym}, expected YYYY-MM`);
    }
    return { year: parseInt(ym.slice(0, 4), 10), month: parseInt(ym.slice(5), 10) };
}

export function editability(yearMonth: string, now: Date = effectiveNow()): EditabilityState {
    const et = nowInEt(now);
    const target = parseYearMonth(yearMonth);
    const diff = toMonthOrdinal(target.year, target.month) - toMonthOrdinal(et.year, et.month);

    if (diff === 0 || (diff >= 1 && diff <= N_FUTURE_MONTHS)) {
        return "EDITABLE";
    }
    // Grace: previous month, before midnight ET on day 8 of the current month.
    // Equivalently: today's ET day < (1 + GRACE_PERIOD_DAYS).
    if (diff === -1 && et.day < 1 + GRACE_PERIOD_DAYS) {
        return "GRACE";
    }
    return "LOCKED";
}
