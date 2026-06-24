import { useCallback, useEffect, useState } from "react";
import { fetchAllCategories, fetchCategoryDeletionPreview, hardDeleteCategory } from "../api";
import { useAdmin } from "../admin";
import LoadingOverlay from "../components/LoadingOverlay";
import StatusMessage from "../components/StatusMessage";
import { formatYearMonth } from "../format";
import { useStatus } from "../hooks";
import type { Category, DeletionPreview } from "../types";

export default function AdminToolsPage() {
    const { isAdminUser } = useAdmin();
    const [categories, setCategories] = useState<Category[]>([]);
    const [selectedId, setSelectedId] = useState<string>("");
    const [preview, setPreview] = useState<DeletionPreview | null>(null);
    const [confirmName, setConfirmName] = useState("");
    const [explanation, setExplanation] = useState("");
    const { status, showLoading, showError, showSuccess, clear } = useStatus();

    const loadCategories = useCallback(async () => {
        try {
            const cats = await fetchAllCategories();
            setCategories(cats);
        } catch (err) {
            showError(err);
        }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (isAdminUser) loadCategories();
    }, [isAdminUser, loadCategories]);

    // When the dropdown selection changes, fetch the deletion preview for that category.
    // Resets the confirmation fields so the user can't accidentally re-submit values
    // from a previous selection.
    useEffect(() => {
        setPreview(null);
        setConfirmName("");
        setExplanation("");
        if (!selectedId) return;
        let cancelled = false;
        (async () => {
            showLoading("Loading deletion preview...");
            try {
                const result = await fetchCategoryDeletionPreview(selectedId);
                if (!cancelled) {
                    setPreview(result);
                    clear();
                }
            } catch (err) {
                if (!cancelled) showError(err);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

    if (!isAdminUser) {
        return (
            <div className="page">
                <h1>Admin Tools</h1>
                <p>This page is only available to budget-admin users.</p>
            </div>
        );
    }

    const handleHardDelete = async () => {
        if (!preview) return;
        if (confirmName !== preview.category.name) {
            showError("Confirmation name must match the category name exactly");
            return;
        }
        if (!explanation.trim()) {
            showError("Explanation is required");
            return;
        }
        if (
            !window.confirm(
                `Permanently delete "${preview.category.name}" and all ${preview.deletionPreview.budgetRows + preview.deletionPreview.transactions} associated rows? This cannot be undone.`,
            )
        ) {
            return;
        }
        showLoading("Deleting...");
        try {
            const result = await hardDeleteCategory(preview.category.categoryId, {
                confirm: true,
                confirmName,
                explanation: explanation.trim(),
            });
            showSuccess(
                `Deleted "${result.name}": ${result.budgetRowsDeleted} budget row${result.budgetRowsDeleted !== 1 ? "s" : ""}, ${result.transactionsDeleted} transaction${result.transactionsDeleted !== 1 ? "s" : ""}.`,
            );
            setTimeout(clear, 6000);
            setSelectedId("");
            loadCategories();
        } catch (err) {
            showError(err);
        }
    };

    return (
        <div className="page admin-tools-page">
            <h1>Admin Tools</h1>
            <LoadingOverlay message={status.message} visible={status.type === "loading"} />
            <StatusMessage message={status.type !== "loading" ? status.message : ""} type={status.type} />

            <section className="admin-section">
                <h2>Hard delete category</h2>
                <p className="hint">
                    Permanently removes a category and every Budget row and transaction that references it. Soft-delete
                    (Deactivate on the Categories page) is the right tool unless you really need to erase history.
                </p>

                <label className="block-label">
                    Category
                    <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
                        <option value="">Select a category…</option>
                        {categories.map((cat) => (
                            <option key={cat.categoryId} value={cat.categoryId}>
                                {cat.name}
                                {cat.active ? "" : " (deactivated)"}
                            </option>
                        ))}
                    </select>
                </label>

                {preview && (
                    <>
                        <div className="deletion-preview">
                            <p>
                                <strong>{preview.category.name}</strong> would be erased along with:
                            </p>
                            <ul>
                                <li>{preview.deletionPreview.budgetRows} Budget row(s)</li>
                                <li>{preview.deletionPreview.transactions} transaction(s)</li>
                                {preview.deletionPreview.lockedMonthsAffected.length > 0 && (
                                    <li className="warn">
                                        Includes locked months that can't otherwise be modified:{" "}
                                        {preview.deletionPreview.lockedMonthsAffected.map(formatYearMonth).join(", ")}
                                    </li>
                                )}
                            </ul>
                        </div>

                        <label className="block-label">
                            Type the category name exactly to confirm
                            <input
                                type="text"
                                value={confirmName}
                                onChange={(e) => setConfirmName(e.target.value)}
                                placeholder={preview.category.name}
                            />
                        </label>
                        <label className="block-label">
                            Explanation (recorded in the audit log)
                            <input
                                type="text"
                                value={explanation}
                                onChange={(e) => setExplanation(e.target.value)}
                                maxLength={1000}
                            />
                        </label>

                        <button
                            className="danger-btn"
                            disabled={confirmName !== preview.category.name || !explanation.trim()}
                            onClick={handleHardDelete}
                        >
                            Permanently delete
                        </button>
                    </>
                )}
            </section>
        </div>
    );
}
