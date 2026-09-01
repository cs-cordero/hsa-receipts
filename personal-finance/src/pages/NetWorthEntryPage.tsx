import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchAllAccounts, fetchNetWorthMonth, saveNetWorthMonth } from "../api";
import LoadingOverlay from "../components/LoadingOverlay";
import MonthPicker from "../components/MonthPicker";
import NetWorthHistoryPanel from "../components/NetWorthHistoryPanel";
import StatusMessage from "../components/StatusMessage";
import { currentYearMonth, formatCurrency, formatYearMonth, parseCurrencyInput } from "../format";
import { useStatus } from "../hooks";
import { ACCOUNT_TYPE_LABELS, type Account, type NetWorthRow } from "../types";

// Per-account editable cell state. `raw` is the dollar string in the input;
// `touched` records whether the user has interacted with it. A carried (prefill)
// value that stays untouched is never written — only values the user asserts are.
interface Entry {
    raw: string;
    touched: boolean;
}

// Strip currency chrome ($ and thousands separators) so a formatted value is easy
// to edit while focused.
function stripFormat(s: string): string {
    return s.replace(/[$,\s]/g, "");
}

// Normalize a raw input string to a currency display ("$1,234.56"). Empty stays
// empty; unparseable text is left as-is so the user can correct it rather than
// having their entry silently discarded.
function formatValue(s: string): string {
    const trimmed = s.trim();
    if (trimmed === "") return "";
    const millionths = parseCurrencyInput(trimmed);
    if (millionths === null) return trimmed;
    return formatCurrency(millionths);
}

export default function NetWorthEntryPage() {
    const [yearMonth, setYearMonth] = useState<string>(currentYearMonth());
    const [rows, setRows] = useState<NetWorthRow[]>([]);
    const [accountsById, setAccountsById] = useState<Map<string, Account>>(new Map());
    const [entries, setEntries] = useState<Record<string, Entry>>({});
    // Per-account note for this month (month-specific; not carried forward).
    const [notes, setNotes] = useState<Record<string, string>>({});
    // Which account's note editor is currently expanded (only one at a time).
    const [openNote, setOpenNote] = useState<string | null>(null);
    // Bumped after a successful save so the history pane refetches.
    const [historyReloadKey, setHistoryReloadKey] = useState(0);
    const { status, showLoading, showError, showSuccess, clear } = useStatus();

    const isFuture = yearMonth > currentYearMonth();

    const load = useCallback(async () => {
        if (yearMonth > currentYearMonth()) {
            // The backend rejects future snapshots (that's the simulator's job someday);
            // don't even fetch — just surface the guidance.
            setRows([]);
            setEntries({});
            clear();
            return;
        }
        showLoading("Loading...");
        try {
            const [month, allAccounts] = await Promise.all([fetchNetWorthMonth(yearMonth), fetchAllAccounts()]);
            const byId = new Map(allAccounts.map((a) => [a.accountId, a]));
            setAccountsById(byId);
            setRows(month.rows);

            // Seed the editable state: a saved value shows as itself (already
            // asserted); a carried prefill shows muted until touched; otherwise blank.
            const seeded: Record<string, Entry> = {};
            for (const row of month.rows) {
                if (row.value !== null) {
                    seeded[row.accountId] = { raw: formatCurrency(row.value), touched: true };
                } else if (row.prefill) {
                    seeded[row.accountId] = { raw: formatCurrency(row.prefill.value), touched: false };
                } else {
                    seeded[row.accountId] = { raw: "", touched: false };
                }
            }
            setEntries(seeded);

            // Seed notes from the month's saved rows. Notes don't carry forward, so
            // there's no prefill — a month starts with only its own recorded notes.
            const noteSeed: Record<string, string> = {};
            for (const row of month.rows) noteSeed[row.accountId] = row.note ?? "";
            setNotes(noteSeed);
            setOpenNote(null);

            clear();
        } catch (err) {
            showError(err);
        }
    }, [yearMonth]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        load();
    }, [load]);

    const setRaw = (accountId: string, raw: string) => {
        setEntries((prev) => ({ ...prev, [accountId]: { raw, touched: true } }));
    };

    // Focus/blur reformatting must NOT flip `touched` — only real edits (setRaw) do
    // — so an untouched carried value stays unsaved even after tabbing through it.
    const reformatRaw = (accountId: string, raw: string) => {
        setEntries((prev) => ({ ...prev, [accountId]: { raw, touched: prev[accountId]?.touched ?? false } }));
    };

    const setNote = (accountId: string, text: string) => {
        setNotes((prev) => ({ ...prev, [accountId]: text }));
    };

    // Split rows into assets / liabilities for display, preserving server order.
    const { assetRows, liabilityRows } = useMemo(() => {
        const assetRows: NetWorthRow[] = [];
        const liabilityRows: NetWorthRow[] = [];
        for (const row of rows) {
            const account = accountsById.get(row.accountId);
            if (account?.liability) liabilityRows.push(row);
            else assetRows.push(row);
        }
        return { assetRows, liabilityRows };
    }, [rows, accountsById]);

    // Live totals use the effective displayed value per row (typed or carried), so
    // the net-worth figure reflects what the month would look like if saved.
    const totals = useMemo(() => {
        let assets = 0;
        let liabilities = 0;
        for (const row of rows) {
            const account = accountsById.get(row.accountId);
            // Excluded accounts are still recorded, but never roll into the totals
            // (mirrors the server's build_history).
            if (account?.excludedFromNetWorth) continue;
            const raw = (entries[row.accountId]?.raw ?? "").trim();
            if (raw === "") continue;
            const value = parseCurrencyInput(raw);
            if (value === null || value < 0) continue;
            if (account?.liability) liabilities += value;
            else assets += value;
        }
        return { assets, liabilities, netWorth: assets - liabilities };
    }, [rows, entries, accountsById]);

    const handleSave = async () => {
        // Save records the whole visible column — the Save click is the assertion.
        // Carried (pre-filled) values are written just like typed ones; blanking a
        // cell deletes an existing saved value; a row is a no-op only when BOTH its
        // value and its note are unchanged.
        const payload: { accountId: string; value: number | null; note?: string }[] = [];
        for (const row of rows) {
            const entry = entries[row.accountId];
            if (!entry) continue;
            const raw = entry.raw.trim();
            const note = (notes[row.accountId] ?? "").trim();
            const originalNote = (row.note ?? "").trim();

            if (raw === "") {
                // Blank clears an existing saved value (and its note); an empty account
                // with nothing to carry is simply skipped.
                if (row.value !== null) payload.push({ accountId: row.accountId, value: null });
                continue;
            }

            const value = parseCurrencyInput(raw);
            if (value === null || value < 0) {
                showError(`"${accountsById.get(row.accountId)?.name ?? row.accountId}" has an invalid amount`);
                return;
            }
            if (value === row.value && note === originalNote) continue; // nothing changed
            const out: { accountId: string; value: number | null; note?: string } = {
                accountId: row.accountId,
                value,
            };
            if (note) out.note = note;
            payload.push(out);
        }

        if (payload.length === 0) {
            showSuccess("Nothing to save — no values were changed");
            setTimeout(clear, 3000);
            return;
        }

        showLoading("Saving...");
        try {
            await saveNetWorthMonth(yearMonth, payload);
            showSuccess(`Saved ${payload.length} value${payload.length !== 1 ? "s" : ""} for ${formatYearMonth(yearMonth)}`);
            setTimeout(clear, 3000);
            load();
            setHistoryReloadKey((k) => k + 1); // refresh the history pane

        } catch (err) {
            showError(err);
        }
    };

    const renderRow = (row: NetWorthRow) => {
        const account = accountsById.get(row.accountId);
        const entry = entries[row.accountId] ?? { raw: "", touched: false };
        const isCarried = row.value === null && row.prefill !== null && !entry.touched;
        const hasNote = (notes[row.accountId] ?? "").trim() !== "";
        return (
            <tr key={row.accountId} className={isCarried ? "faded" : ""}>
                <td>
                    <div>
                        {account?.name ?? row.accountId}
                        {account?.excludedFromNetWorth && (
                            <span className="badge badge-pinned nw-excluded-badge" title="Excluded from net worth totals">
                                Excluded
                            </span>
                        )}
                    </div>
                    {account && (
                        <div className="nw-entry-type">
                            {ACCOUNT_TYPE_LABELS[account.accountType] ?? account.accountType}
                        </div>
                    )}
                </td>
                <td className="num">
                    <div className="nw-value-row">
                        <input
                            type="text"
                            inputMode="decimal"
                            className="currency-input"
                            value={entry.raw}
                            onChange={(e) => setRaw(row.accountId, e.target.value)}
                            onFocus={(e) => reformatRaw(row.accountId, stripFormat(e.target.value))}
                            onBlur={(e) => reformatRaw(row.accountId, formatValue(e.target.value))}
                        />
                        <button
                            type="button"
                            className={`nw-note-toggle${hasNote ? " has-note" : ""}`}
                            title={hasNote ? (notes[row.accountId] ?? "") : "Add note"}
                            aria-label={hasNote ? "Edit note" : "Add note"}
                            onClick={() => setOpenNote((cur) => (cur === row.accountId ? null : row.accountId))}
                        >
                            {hasNote ? "●" : "○"}
                        </button>
                    </div>
                    {isCarried && row.prefill && (
                        <div className="nw-carried-note">
                            carried from {formatYearMonth(row.prefill.fromYearMonth)}
                        </div>
                    )}
                    {openNote === row.accountId && (
                        <textarea
                            className="nw-note-editor"
                            rows={2}
                            placeholder="Note for this month"
                            value={notes[row.accountId] ?? ""}
                            onChange={(e) => setNote(row.accountId, e.target.value)}
                        />
                    )}
                </td>
            </tr>
        );
    };

    // Both sections render through one helper with a fixed column layout (see the
    // .networth-grid colgroup) so the Assets and Liabilities tables line up
    // column-for-column instead of each sizing to its own content.
    const renderTable = (title: string, sectionRows: NetWorthRow[], total: number) => (
        <section>
            <h2>{title}</h2>
            <table className="data-table networth-grid">
                <colgroup>
                    <col className="nw-col-account" />
                    <col className="nw-col-value" />
                </colgroup>
                <thead>
                    <tr>
                        <th>Account</th>
                        <th>Value</th>
                    </tr>
                </thead>
                <tbody>
                    {sectionRows.map(renderRow)}
                    {/* Uneditable section total — recomputes live as values change. */}
                    <tr className="nw-total-row">
                        <td>Total {title}</td>
                        <td className="num">{formatCurrency(total)}</td>
                    </tr>
                </tbody>
            </table>
        </section>
    );

    return (
        <div className="page">
            <h1>Household Net Worth</h1>
            <LoadingOverlay message={status.message} visible={status.type === "loading"} />
            <StatusMessage message={status.type !== "loading" ? status.message : ""} type={status.type} />

            <div className="networth-split">
                {/* Left pane: record this month's values. */}
                <section className="networth-pane networth-entry-pane">
                    <h2 className="pane-title">Record</h2>
                    <div className="toolbar">
                        {/* Net worth has no lock/grace, and future months aren't recordable — so
                            hide the badges, cap navigation at the current month, and offer a
                            one-click jump back to it. */}
                        <MonthPicker
                            value={yearMonth}
                            onChange={setYearMonth}
                            showBadges={false}
                            maxMonth={currentYearMonth()}
                        />
                    </div>

                    {isFuture ? (
                        <p className="hint">
                            Future months can't be recorded — net worth is entered as it happens. Pick the current
                            month or a past one.
                        </p>
                    ) : rows.length === 0 ? (
                        <p className="empty">
                            No accounts to record. Add accounts on the <strong>Accounts</strong> page first.
                        </p>
                    ) : (
                        <>
                            <div className="toolbar">
                                <button className="primary-btn" onClick={handleSave}>
                                    Save {formatYearMonth(yearMonth)}
                                </button>
                            </div>

                            {assetRows.length > 0 && renderTable("Assets", assetRows, totals.assets)}
                            {liabilityRows.length > 0 && renderTable("Liabilities", liabilityRows, totals.liabilities)}

                            {/* Uneditable net-worth summary row, aligned with the tables above. */}
                            <table className="data-table networth-grid nw-networth-summary">
                                <colgroup>
                                    <col className="nw-col-account" />
                                    <col className="nw-col-value" />
                                </colgroup>
                                <tbody>
                                    <tr className="nw-total-row nw-networth-row">
                                        <td>Net Worth</td>
                                        <td className="num">{formatCurrency(totals.netWorth)}</td>
                                    </tr>
                                </tbody>
                            </table>
                        </>
                    )}
                </section>

                {/* Right pane: historical values + net-worth-over-time chart. */}
                <section className="networth-pane networth-history-pane">
                    <NetWorthHistoryPanel
                        reloadKey={historyReloadKey}
                        selectedMonth={yearMonth}
                        onSelectMonth={setYearMonth}
                    />
                </section>
            </div>
        </div>
    );
}
