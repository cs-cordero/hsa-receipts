import { editability } from "../editability";
import { formatYearMonth, monthTense, nextYearMonth, prevYearMonth } from "../format";

interface MonthPickerProps {
    value: string;
    onChange: (yearMonth: string) => void;
}

export default function MonthPicker({ value, onChange }: MonthPickerProps) {
    const tense = monthTense(value);
    const state = editability(value);
    // Always show the past/current/future qualifier — it costs nothing to show
    // and is helpful on every page that picks a month.
    const label = `${formatYearMonth(value)} (${tense})`;

    return (
        <div className="month-picker">
            <button onClick={() => onChange(prevYearMonth(value))}>&larr;</button>
            <span className="month-label">{label}</span>
            {state === "LOCKED" && (
                <span className="month-state-badge month-locked" title="Locked — admin override required to mutate">
                    locked
                </span>
            )}
            {state === "GRACE" && (
                <span className="month-state-badge month-grace" title="Grace period — still editable for a few days">
                    grace
                </span>
            )}
            <button onClick={() => onChange(nextYearMonth(value))}>&rarr;</button>
        </div>
    );
}
