import { editability } from "../editability";
import { formatYearMonth, monthTense, nextYearMonth, prevYearMonth } from "../format";

interface MonthPickerProps {
    value: string;
    onChange: (yearMonth: string) => void;
    // Show the budget-style LOCKED / GRACE badges (default true). Features without
    // lock/grace machinery — e.g. net worth, where any past month is freely
    // editable — pass false so a stale "locked" badge doesn't mislead.
    showBadges?: boolean;
    // Upper bound. When set, the forward arrow is hidden once value reaches it (so
    // the user can't page past it), and a "Current" button appears whenever value
    // is earlier — jumping straight back to it.
    maxMonth?: string;
}

export default function MonthPicker({ value, onChange, showBadges = true, maxMonth }: MonthPickerProps) {
    const tense = monthTense(value);
    const state = editability(value);
    // Always show the past/current/future qualifier — it costs nothing to show
    // and is helpful on every page that picks a month.
    const label = `${formatYearMonth(value)} (${tense})`;

    return (
        <div className="month-picker">
            <button onClick={() => onChange(prevYearMonth(value))}>&larr;</button>
            <span className="month-label">{label}</span>
            {showBadges && state === "LOCKED" && (
                <span className="month-state-badge month-locked" title="Locked — admin override required to mutate">
                    locked
                </span>
            )}
            {showBadges && state === "GRACE" && (
                <span className="month-state-badge month-grace" title="Grace period — still editable for a few days">
                    grace
                </span>
            )}
            {/* Forward arrow is hidden once we reach the upper bound (if one is set). */}
            {(maxMonth === undefined || value < maxMonth) && (
                <button onClick={() => onChange(nextYearMonth(value))}>&rarr;</button>
            )}
            {maxMonth !== undefined && value < maxMonth && (
                <button className="small-btn" onClick={() => onChange(maxMonth)} title="Jump to the current month">
                    Go to Current
                </button>
            )}
        </div>
    );
}
