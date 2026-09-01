import { useEffect, useState } from "react";

// A cross-browser month + year picker that reads/writes a "YYYY-MM" string.
//
// We can't use <input type="month"> here: Firefox (and Safari) never implemented
// a picker for it and fall back to a bare text box. Two <select>s work identically
// everywhere.
//
// The parent stores only the combined "YYYY-MM", but a user picks the two parts
// one at a time — so the component keeps its own month/year state. It only
// propagates a value once BOTH parts are set (a lone month or year is meaningless
// and would fail the server's YYYY-MM validation); until then the parent sees "".
// Without this local state, picking the month alone would emit "" and immediately
// snap both dropdowns back to their placeholders.

const MONTH_LABELS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
];

function parse(value: string): [string, string] {
    // Returns [year, month]; ["", ""] for empty/invalid input.
    return value && /^\d{4}-\d{2}$/.test(value) ? (value.split("-") as [string, string]) : ["", ""];
}

interface MonthYearInputProps {
    value: string; // "YYYY-MM" or "" when unset/incomplete
    onChange: (value: string) => void;
    id?: string;
    minYear?: number;
    maxYear?: number;
}

export default function MonthYearInput({ value, onChange, id, minYear, maxYear }: MonthYearInputProps) {
    const [initYear, initMonth] = parse(value);
    const [year, setYear] = useState(initYear);
    const [month, setMonth] = useState(initMonth);

    // Re-sync from the parent only on a genuine external change (form reset, edit
    // populate). We compare against what our current local state would emit so an
    // in-progress partial selection — which legitimately emits "" — is never
    // clobbered by the parent echoing that "" back.
    useEffect(() => {
        const emitted = year && month ? `${year}-${month}` : "";
        if (value !== emitted) {
            const [y, m] = parse(value);
            setYear(y);
            setMonth(m);
        }
    }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

    const currentYear = new Date().getFullYear();
    const lo = minYear ?? 1920;
    const hi = maxYear ?? currentYear + 60;
    const years: number[] = [];
    for (let y = hi; y >= lo; y--) years.push(y);

    const update = (y: string, m: string) => {
        setYear(y);
        setMonth(m);
        onChange(y && m ? `${y}-${m}` : "");
    };

    return (
        <span className="month-year-input">
            <select id={id} aria-label="Month" value={month} onChange={(e) => update(year, e.target.value)}>
                <option value="">Month</option>
                {MONTH_LABELS.map((label, i) => {
                    const mm = String(i + 1).padStart(2, "0");
                    return (
                        <option key={mm} value={mm}>
                            {label}
                        </option>
                    );
                })}
            </select>
            <select aria-label="Year" value={year} onChange={(e) => update(e.target.value, month)}>
                <option value="">Year</option>
                {years.map((y) => (
                    <option key={y} value={String(y)}>
                        {y}
                    </option>
                ))}
            </select>
        </span>
    );
}
