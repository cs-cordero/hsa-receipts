export interface CategoryNameHistoryEntry {
    previousName: string;
    replacedAt: string;
}

export interface CategoryGroup {
    groupId: string;
    name: string;
    order: number;
    createdAt: string;
    updatedAt: string;
    // True for sentinel groups managed by the backend (e.g. "Unassigned"). System
    // groups are immutable from the UI: no rename, no delete, no drag-to-reorder.
    system: boolean;
}

export interface Category {
    categoryId: string;
    name: string;
    active: boolean;
    createdAt: string;
    updatedAt: string;
    nameHistory: CategoryNameHistoryEntry[];
    // Pre-CP12 rows may not yet have these — backfill script + new creates always do.
    // Parser defaults missing values to empty/0 so the UI doesn't crash on legacy rows.
    groupId: string;
    orderInGroup: number;
}

export interface DeactivateResult {
    category: Category;
    affectedMonths: string[];
}

export interface DeletionPreview {
    category: Category;
    deletionPreview: {
        budgetRows: number;
        transactions: number;
        lockedMonthsAffected: string[];
    };
}

export interface HardDeleteResult {
    categoryId: string;
    name: string;
    budgetRowsDeleted: number;
    transactionsDeleted: number;
}

export interface BudgetTarget {
    yearMonth: string;
    categoryId: string;
    amount: number;
    // Only present for future-month responses (server-resolved walk-back).
    // True means an explicit pin row exists at this (yearMonth, categoryId);
    // false means the amount was carried forward from an earlier month.
    pinned?: boolean;
}

export interface PinResult {
    targets: BudgetTarget[];
    warnings: {
        downstreamPins: { categoryId: string; yearMonth: string }[];
        pinMatchesCarriedValue: string[];
    };
}

export interface Transaction {
    yearMonth: string;
    sortId: string;
    transactionDate: string;
    description: string;
    amount: number;
    categoryId: string;
    createdAt: string;
}

export interface SummaryCategory {
    categoryId: string;
    // Current display name. `historicalName` is the name in effect during the
    // requested year-month if the category was later renamed (set only for
    // locked months per architecture's "Display names on locked months").
    name: string;
    historicalName: string | null;
    budgeted: number;
    actual: number;
    delta: number;
}

export interface Summary {
    yearMonth: string;
    state: "EDITABLE" | "GRACE" | "LOCKED";
    categories: SummaryCategory[];
    totals: { budgeted: number; actual: number; delta: number };
}

export interface AuditUser {
    sub: string;
    email: string;
    username: string;
}

export interface AuditEntry {
    sortId: string;
    changedAt: string;
    effectiveYearMonth: string | null;
    categoryId: string;
    action: string;
    explanation: string;
    user: AuditUser;
    override: boolean;
    // Action-shaped payload. CREATE/UPDATE/PIN/UNPIN use {before, after} per field.
    // CATEGORY_HARD_DELETE uses {budgetRowsDeleted, transactionsDeleted, name}.
    // Renderer branches on `action`.
    changes: Record<string, unknown>;
}

export interface ColumnMapping {
    date: string;
    description: string;
    amount: string;
    amount_invert?: boolean;
}

export interface ParsedTransaction {
    transactionDate: string;
    description: string;
    amount: number;
    categoryId: string;
    categoryName: string;
}

// Closed enum so we can render specific UI per issue. Adding a new issue here
// requires updating the backend's `_validate_commit_rows`.
export type RowValidationIssue = "missing_category" | "locked_month";

export interface RowValidation {
    index: number;
    issues: RowValidationIssue[];
}

export interface UploadResult {
    columnMapping: ColumnMapping;
    transactions: ParsedTransaction[];
    validations: RowValidation[];
}

export interface CommitResult {
    count: number;
    transactions: Transaction[];
}

export interface CommitValidationError {
    error: string;
    validations: RowValidation[];
}
