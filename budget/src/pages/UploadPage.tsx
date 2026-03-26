import { useCallback, useMemo, useState } from "react";
import { useAdmin } from "../admin";
import { ApiError, commitTransactions, fetchCategories, uploadTransactions } from "../api";
import LoadingOverlay from "../components/LoadingOverlay";
import StatusMessage from "../components/StatusMessage";
import { formatCurrency } from "../format";
import { useStatus } from "../hooks";
import { parseCommitValidationsFromError } from "../parsers";
import type { Category, ParsedTransaction, RowValidation, RowValidationIssue } from "../types";

type SortKey = "transactionDate" | "description" | "amount" | "categoryName";
type SortDir = "asc" | "desc";

function yearMonthFromDate(dateStr: string): string {
    return dateStr.slice(0, 7);
}

function issueLabel(issue: RowValidationIssue): string {
    switch (issue) {
        case "missing_category":
            return "Pick a category";
        case "locked_month":
            return "Locked month (override required)";
    }
}

export default function UploadPage() {
    const { adminModeOn } = useAdmin();
    const [csvFile, setCsvFile] = useState<File | null>(null);
    const [transactions, setTransactions] = useState<ParsedTransaction[]>([]);
    const [validations, setValidations] = useState<RowValidation[]>([]);
    const [removed, setRemoved] = useState<Set<number>>(new Set());
    const [categories, setCategories] = useState<Category[]>([]);
    const { status, showLoading, showSuccess, showError, clear } = useStatus();
    const [step, setStep] = useState<"upload" | "review" | "done">("upload");

    const [sortKey, setSortKey] = useState<SortKey>("transactionDate");
    const [sortDir, setSortDir] = useState<SortDir>("asc");

    const handleUpload = useCallback(async () => {
        if (!csvFile) return;
        showLoading("Uploading and analyzing...");
        try {
            const text = await csvFile.text();
            const [result, cats] = await Promise.all([uploadTransactions(text), fetchCategories()]);
            setTransactions(result.transactions);
            setValidations(result.validations);
            setRemoved(new Set());
            setCategories(cats);
            setStep("review");
            showSuccess(`Found ${result.transactions.length} transactions`);
            setTimeout(clear, 3000);
        } catch (err) {
            showError(err);
        }
    }, [csvFile]); // eslint-disable-line react-hooks/exhaustive-deps

    // Validations come back keyed by row index. Editing a row's category or removing
    // a row can resolve issues client-side, so we recompute the displayed status from
    // the latest state rather than relying on the server's original list.
    const liveIssues = useMemo<Map<number, RowValidationIssue[]>>(() => {
        const m = new Map<number, RowValidationIssue[]>();
        for (const v of validations) {
            const txn = transactions[v.index];
            if (!txn) continue;
            const issues: RowValidationIssue[] = [];
            for (const issue of v.issues) {
                if (issue === "missing_category") {
                    if (!txn.categoryId) issues.push("missing_category");
                } else if (issue === "locked_month") {
                    // locked_month is server-decided; we don't recompute it because
                    // the client doesn't know the exact editability state machine.
                    // Admin mode optimistically suppresses it — backend re-validates.
                    if (!adminModeOn) issues.push("locked_month");
                }
            }
            if (issues.length) m.set(v.index, issues);
        }
        return m;
    }, [validations, transactions, adminModeOn]);

    const updateTxn = (index: number, field: keyof ParsedTransaction, value: string) => {
        const updated = [...transactions];
        updated[index] = { ...updated[index], [field]: value };
        if (field === "categoryId") {
            const cat = categories.find((c) => c.categoryId === value);
            updated[index].categoryName = cat?.name ?? "";
        }
        setTransactions(updated);
    };

    const toggleRemove = (index: number) => {
        setRemoved((prev) => {
            const next = new Set(prev);
            if (next.has(index)) next.delete(index);
            else next.add(index);
            return next;
        });
    };

    const activeRowsWithIndex = useMemo(
        () => transactions.map((t, i) => ({ ...t, _i: i })).filter((t) => !removed.has(t._i)),
        [transactions, removed],
    );
    const activeCount = activeRowsWithIndex.length;

    const blockingIssueCount = useMemo(
        () => activeRowsWithIndex.filter((t) => (liveIssues.get(t._i) ?? []).length > 0).length,
        [activeRowsWithIndex, liveIssues],
    );
    const canCommit = activeCount > 0 && blockingIssueCount === 0;

    const handleCommit = async () => {
        showLoading("Saving transactions...");
        try {
            const rows = activeRowsWithIndex.map((t) => ({
                transactionDate: t.transactionDate,
                description: t.description,
                amount: t.amount,
                categoryId: t.categoryId,
            }));
            const result = await commitTransactions(rows, adminModeOn);
            setStep("done");
            showSuccess(`Saved ${result.count} transactions`);
        } catch (err) {
            // Server returned 409 with full validation list — surface it back into the UI.
            if (err instanceof ApiError && err.status === 409) {
                const v = parseCommitValidationsFromError(err.responseBody);
                if (v) {
                    // Server validations are keyed by index into the committed batch (filtered).
                    // Re-key to the original transaction indices.
                    const originalIndices = activeRowsWithIndex.map((t) => t._i);
                    const remappedValidations: RowValidation[] = v.map((rv) => ({
                        index: originalIndices[rv.index] ?? rv.index,
                        issues: rv.issues,
                    }));
                    setValidations(remappedValidations);
                    showError("Commit rejected — fix the highlighted rows and try again.");
                    return;
                }
            }
            showError(err);
        }
    };

    const reset = () => {
        setCsvFile(null);
        setTransactions([]);
        setValidations([]);
        setRemoved(new Set());
        setStep("upload");
        clear();
    };

    const sortedIndices = useMemo(() => {
        const indices = transactions.map((_, i) => i);
        indices.sort((a, b) => {
            const ta = transactions[a];
            const tb = transactions[b];
            let cmp = 0;
            switch (sortKey) {
                case "transactionDate":
                    cmp = ta.transactionDate.localeCompare(tb.transactionDate);
                    break;
                case "description":
                    cmp = ta.description.localeCompare(tb.description);
                    break;
                case "amount":
                    cmp = ta.amount - tb.amount;
                    break;
                case "categoryName":
                    cmp = ta.categoryName.localeCompare(tb.categoryName);
                    break;
            }
            return sortDir === "asc" ? cmp : -cmp;
        });
        return indices;
    }, [transactions, sortKey, sortDir]);

    const handleSort = (key: SortKey) => {
        if (sortKey === key) {
            setSortDir(sortDir === "asc" ? "desc" : "asc");
        } else {
            setSortKey(key);
            setSortDir("asc");
        }
    };

    const sortIndicator = (key: SortKey) => {
        if (sortKey !== key) return " ↕";
        return sortDir === "asc" ? " ↑" : " ↓";
    };

    return (
        <div className="page">
            <h1>Upload Transactions</h1>
            <LoadingOverlay message={status.message} visible={status.type === "loading"} />
            <StatusMessage message={status.type !== "loading" ? status.message : ""} type={status.type} />

            {step === "upload" && (
                <div className="upload-section">
                    <p className="hint">Upload a CSV from your bank or credit card statement.</p>
                    <div className="upload-controls">
                        <input type="file" accept=".csv" onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)} />
                        <button className="primary-btn" onClick={handleUpload} disabled={!csvFile}>
                            Upload & Analyze
                        </button>
                    </div>
                </div>
            )}

            {step === "review" && (
                <>
                    <p className="hint">
                        Review the categorized transactions below. Edit categories, remove rows, then commit.
                        {adminModeOn && (
                            <span className="hint-admin">
                                {" "}
                                Admin mode: locked-month rows will commit with override.
                            </span>
                        )}
                    </p>
                    {blockingIssueCount > 0 && (
                        <p className="hint warn">
                            {blockingIssueCount} row{blockingIssueCount !== 1 ? "s" : ""} need attention before
                            committing.
                        </p>
                    )}
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th className="sortable" onClick={() => handleSort("transactionDate")}>
                                    Date{sortIndicator("transactionDate")}
                                </th>
                                <th className="sortable" onClick={() => handleSort("description")}>
                                    Description{sortIndicator("description")}
                                </th>
                                <th className="sortable num" onClick={() => handleSort("amount")}>
                                    Amount{sortIndicator("amount")}
                                </th>
                                <th className="sortable" onClick={() => handleSort("categoryName")}>
                                    Category{sortIndicator("categoryName")}
                                </th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {sortedIndices.map((i) => {
                                const txn = transactions[i];
                                const isRemoved = removed.has(i);
                                const issues = liveIssues.get(i) ?? [];
                                const negative = txn.amount < 0;
                                return (
                                    <tr
                                        key={i}
                                        className={[
                                            isRemoved ? "removed-row" : "",
                                            issues.length > 0 ? "row-has-issue" : "",
                                        ].join(" ")}
                                    >
                                        <td>{txn.transactionDate}</td>
                                        <td>{txn.description}</td>
                                        <td className={`num ${negative ? "amount-refund" : ""}`}>
                                            {formatCurrency(txn.amount)}
                                            {negative && <span className="badge badge-refund">refund</span>}
                                        </td>
                                        <td>
                                            <select
                                                value={txn.categoryId}
                                                onChange={(e) => updateTxn(i, "categoryId", e.target.value)}
                                            >
                                                <option value="">Uncategorized</option>
                                                {categories.map((c) => (
                                                    <option key={c.categoryId} value={c.categoryId}>
                                                        {c.name}
                                                    </option>
                                                ))}
                                            </select>
                                        </td>
                                        <td className="row-issues">
                                            {issues.map((issue) => (
                                                <span
                                                    key={issue}
                                                    className={`badge badge-issue badge-issue-${issue}`}
                                                    title={`${issue} (${yearMonthFromDate(txn.transactionDate)})`}
                                                >
                                                    {issueLabel(issue)}
                                                </span>
                                            ))}
                                        </td>
                                        <td className="actions">
                                            <button
                                                className={`small-btn ${isRemoved ? "" : "delete-btn"}`}
                                                onClick={() => toggleRemove(i)}
                                            >
                                                {isRemoved ? "Restore" : "Remove"}
                                            </button>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                    <div className="toolbar">
                        <button className="primary-btn" onClick={handleCommit} disabled={!canCommit}>
                            Commit {activeCount} Transaction{activeCount !== 1 ? "s" : ""}
                            {adminModeOn ? " (with override)" : ""}
                        </button>
                        <button className="secondary-btn" onClick={reset}>
                            Start Over
                        </button>
                    </div>
                </>
            )}

            {step === "done" && (
                <div className="done-section">
                    <button className="primary-btn" onClick={reset}>
                        Upload More
                    </button>
                </div>
            )}
        </div>
    );
}
