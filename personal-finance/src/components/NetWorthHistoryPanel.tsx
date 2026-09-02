import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchNetWorthHistory } from "../api";
import { formatCurrency, formatYearMonth } from "../format";
import { useStatus } from "../hooks";
import type { Account, NetWorthHistory } from "../types";
import NetWorthChart from "./NetWorthChart";
import StatusMessage from "./StatusMessage";

interface NetWorthHistoryPanelProps {
    // Bumped by the parent after a successful save so the history refetches.
    reloadKey: number;
    // The month currently selected in the entry pane (highlighted here).
    selectedMonth: string;
    // Clicking a month header jumps the entry pane to that month.
    onSelectMonth: (yearMonth: string) => void;
}

export default function NetWorthHistoryPanel({ reloadKey, selectedMonth, onSelectMonth }: NetWorthHistoryPanelProps) {
    const [history, setHistory] = useState<NetWorthHistory | null>(null);
    const [loading, setLoading] = useState(true);
    const { status, showError, clear } = useStatus();

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const h = await fetchNetWorthHistory();
            setHistory(h);
            clear();
        } catch (err) {
            showError(err);
        } finally {
            setLoading(false);
        }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        load();
    }, [load, reloadKey]);

    const { assets, liabilities } = useMemo(() => {
        const accounts = history?.accounts ?? [];
        // Deactivated accounts sink to the bottom of their group; the sort is stable,
        // so sortOrder is preserved within the active and inactive partitions.
        const byActive = (arr: Account[]): Account[] =>
            [...arr].sort((x, y) => (x.active === y.active ? 0 : x.active ? -1 : 1));
        return {
            assets: byActive(accounts.filter((a) => !a.liability)),
            liabilities: byActive(accounts.filter((a) => a.liability)),
        };
    }, [history]);

    const netWorthSeries = useMemo(
        () => (history ? history.months.map((ym) => history.totals[ym]?.netWorth ?? 0) : []),
        [history],
    );

    // Account name for the sticky first column, with an "Excluded" badge when it's
    // tracked-but-excluded from the totals, and a "Deactivated" badge when closed.
    const accountLabel = (a: Account) => (
        <>
            {a.name}
            {a.excludedFromNetWorth && (
                <span className="badge badge-pinned nw-excluded-badge" title="Excluded from the totals below">
                    Excluded
                </span>
            )}
            {!a.active && (
                <span className="badge nw-deactivated-badge" title="Account is deactivated (history kept)">
                    Deactivated
                </span>
            )}
        </>
    );

    const cell = (ym: string, accountId: string) => {
        const v = history?.values[ym]?.[accountId];
        if (v === undefined) return <span className="muted">—</span>;
        const note = history?.notes[ym]?.[accountId];
        return (
            <>
                {formatCurrency(v)}
                {note && (
                    <sup className="nw-note-dot" title={note}>
                        ●
                    </sup>
                )}
            </>
        );
    };

    if (loading && history === null) {
        return <p className="hint">Loading history…</p>;
    }

    if (!history || history.months.length === 0) {
        return (
            <>
                <StatusMessage message={status.message} type={status.type} />
                <p className="empty">No history yet. Record a month on the left to start building your history.</p>
            </>
        );
    }

    // Chart reads time left→right (chronological). The TABLE shows newest first:
    // Account column, then the current month, then older months as you scroll right.
    const months = history.months;
    const monthCols = [...history.months].reverse();
    const numCell = (ym: string) => `num${ym === selectedMonth ? " nw-selected" : ""}`;

    // Shared fixed-width columns so the accounts table and the totals table below it
    // line up column-for-column and scroll together as one (they share the scroll
    // container). Fixed layout is what lets two separate <table>s stay aligned.
    const colgroup = (
        <colgroup>
            <col className="nw-hist-label-col" />
            {monthCols.map((ym) => (
                <col key={ym} className="nw-hist-month-col" />
            ))}
        </colgroup>
    );

    return (
        <div className="networth-history">
            <StatusMessage message={status.message} type={status.type} />

            <h2 className="pane-title">Net worth over time</h2>
            <NetWorthChart months={months} netWorth={netWorthSeries} />

            <h2>History</h2>
            <div className="networth-history-scroll">
                {/* Accounts table. */}
                <table className="data-table networth-history-table">
                    {colgroup}
                    <thead>
                        <tr>
                            <th className="nw-sticky-col">Account</th>
                            {monthCols.map((ym) => (
                                <th
                                    key={ym}
                                    className={ym === selectedMonth ? "nw-month-col nw-selected" : "nw-month-col"}
                                >
                                    <button
                                        className="nw-month-btn"
                                        title="Edit this month on the left"
                                        onClick={() => onSelectMonth(ym)}
                                    >
                                        {formatYearMonth(ym)}
                                    </button>
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {assets.length > 0 && (
                            <tr className="nw-group-row">
                                {/* Label pinned via a sticky span — a full-width colSpan cell
                                    can't stick on its own, so it would scroll away. */}
                                <td colSpan={monthCols.length + 1}>
                                    <span className="nw-group-label">Assets</span>
                                </td>
                            </tr>
                        )}
                        {assets.map((a) => (
                            <tr key={a.accountId}>
                                <td className="nw-sticky-col">{accountLabel(a)}</td>
                                {monthCols.map((ym) => (
                                    <td key={ym} className={numCell(ym)}>
                                        {cell(ym, a.accountId)}
                                    </td>
                                ))}
                            </tr>
                        ))}

                        {liabilities.length > 0 && (
                            <tr className="nw-group-row">
                                <td colSpan={monthCols.length + 1}>
                                    <span className="nw-group-label">Liabilities</span>
                                </td>
                            </tr>
                        )}
                        {liabilities.map((a) => (
                            <tr key={a.accountId}>
                                <td className="nw-sticky-col">{accountLabel(a)}</td>
                                {monthCols.map((ym) => (
                                    <td key={ym} className={numCell(ym)}>
                                        {cell(ym, a.accountId)}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>

                {/* Totals table — its own table with a hard separation above it. Shares
                    the colgroup + scroll container with the accounts table so columns
                    stay aligned and both scroll together. */}
                <table className="data-table networth-history-table networth-totals-table">
                    {colgroup}
                    <tbody>
                        <tr className="nw-total-row">
                            <td className="nw-sticky-col">Total Assets</td>
                            {monthCols.map((ym) => (
                                <td key={ym} className={numCell(ym)}>
                                    {formatCurrency(history.totals[ym]?.assets ?? 0)}
                                </td>
                            ))}
                        </tr>
                        <tr className="nw-total-row">
                            <td className="nw-sticky-col">Total Liabilities</td>
                            {monthCols.map((ym) => (
                                <td key={ym} className={numCell(ym)}>
                                    {formatCurrency(history.totals[ym]?.liabilities ?? 0)}
                                </td>
                            ))}
                        </tr>
                        <tr className="nw-total-row nw-networth-row">
                            <td className="nw-sticky-col">Net Worth</td>
                            {monthCols.map((ym) => (
                                <td key={ym} className={numCell(ym)}>
                                    {formatCurrency(history.totals[ym]?.netWorth ?? 0)}
                                </td>
                            ))}
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    );
}
