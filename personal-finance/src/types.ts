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

// --- Net worth tracking ---

// A person in the household. Owner references on accounts point at personId.
export interface Person {
    personId: string;
    name: string;
    birthYearMonth: string; // YYYY-MM
    createdAt: string;
    updatedAt: string;
}

// Amortization facts for a debt (mortgage, auto/student loan). Captured for the
// future simulation feature; the tracking UI reads them back only to edit.
export interface LoanTerms {
    interestRate: number; // annual rate as a decimal, e.g. 0.04875 for 4.875%
    monthlyPayment: number; // integer millionths of a dollar (principal + interest)
    payoffYearMonth: string; // YYYY-MM of the final payment
}

export interface Account {
    accountId: string;
    name: string;
    accountType: string; // one of ACCOUNT_TYPES; kept as string so unknown DB values don't crash the parser
    assetClass: string; // one of ASSET_CLASSES
    liability: boolean;
    active: boolean;
    sortOrder: number;
    owners: string[]; // one or more personIds; a jointly-held account simply has 2+ owners
    // Tracked but left out of the Total Assets / Liabilities / Net Worth sums
    // (e.g. a 529 or custodial account you follow but don't own).
    excludedFromNetWorth: boolean;
    loanTerms?: LoanTerms;
    notes?: string;
    createdAt: string;
    updatedAt: string;
}

// Create payload: required identity/classification fields plus optional extras.
// Optional fields are simply omitted when unset (never sent as null on create).
export interface AccountCreate {
    name: string;
    accountType: string;
    assetClass: string; // for fixed-class types the server overrides this; send the fixed value anyway
    owners: string[]; // required, non-empty
    excludedFromNetWorth?: boolean; // defaults to false server-side
    loanTerms?: LoanTerms;
    notes?: string;
}

// Edit payload: every field optional. For the nullable extras, an explicit `null`
// REMOVES the attribute server-side; omitting the key leaves it untouched.
// `owners`, when present, is a non-empty list that replaces the current owners.
// `accountType` and `liability` are immutable and are not editable here.
export type AccountUpdate = Partial<{
    name: string;
    assetClass: string;
    owners: string[];
    excludedFromNetWorth: boolean;
    loanTerms: LoanTerms | null;
    notes: string | null;
    sortOrder: number;
}>;

// Enum value spaces mirror lambda/src/corderohq/networth/models.py. The backend
// validates against its StrEnums and 400s on unknown values, so these must stay
// in sync with that file.
export const ACCOUNT_TYPES = [
    "checking",
    "savings",
    "brokerage",
    "401k",
    "roth_ira",
    "traditional_ira",
    "hsa",
    "529",
    "530a",
    "real_estate",
    "mortgage",
    "vehicle",
    "other_asset",
    "other_liability",
] as const;

export const ASSET_CLASSES = ["cash", "us_equity", "intl_equity", "bonds", "real_estate", "other"] as const;

// Type-driven behavior, mirroring lambda/src/corderohq/networth/models.py's
// _ACCOUNT_TYPE_META. The account type is the "driver": it fixes liability, may
// fix the asset class (and to what), and gates loan terms. The backend is
// authoritative — this mirror only shapes the form. Keep the two in sync.
export interface AccountTypeMeta {
    liability: boolean;
    fixedAssetClass: string | null; // when set, asset class is forced & shown read-only (hidden for liabilities)
    amortizing: boolean; // whether loan-term fields are offered
}

export const ACCOUNT_TYPE_META: Record<string, AccountTypeMeta> = {
    checking: { liability: false, fixedAssetClass: "cash", amortizing: false },
    savings: { liability: false, fixedAssetClass: "cash", amortizing: false },
    brokerage: { liability: false, fixedAssetClass: null, amortizing: false },
    "401k": { liability: false, fixedAssetClass: null, amortizing: false },
    roth_ira: { liability: false, fixedAssetClass: null, amortizing: false },
    traditional_ira: { liability: false, fixedAssetClass: null, amortizing: false },
    hsa: { liability: false, fixedAssetClass: null, amortizing: false },
    "529": { liability: false, fixedAssetClass: null, amortizing: false },
    "530a": { liability: false, fixedAssetClass: null, amortizing: false },
    real_estate: { liability: false, fixedAssetClass: "real_estate", amortizing: false },
    vehicle: { liability: false, fixedAssetClass: "other", amortizing: false },
    mortgage: { liability: true, fixedAssetClass: "other", amortizing: true },
    other_asset: { liability: false, fixedAssetClass: null, amortizing: false },
    other_liability: { liability: true, fixedAssetClass: "other", amortizing: true },
};

export const ACCOUNT_TYPE_LABELS: Record<string, string> = {
    checking: "Checking",
    savings: "Savings",
    brokerage: "Brokerage",
    "401k": "401(k)",
    roth_ira: "Roth IRA",
    traditional_ira: "Traditional IRA",
    hsa: "HSA",
    "529": "529",
    "530a": "530A",
    real_estate: "Real Estate",
    mortgage: "Mortgage",
    vehicle: "Vehicle",
    other_asset: "Other Asset",
    other_liability: "Other Liability",
};

export const ASSET_CLASS_LABELS: Record<string, string> = {
    cash: "Cash",
    us_equity: "US Equity",
    intl_equity: "Intl Equity",
    bonds: "Bonds",
    real_estate: "Real Estate",
    other: "Other",
};

// Prefill = the most recent recorded value strictly before this month, powering
// the entry grid's "carried from 2026-06" convenience. null means no prior value.
export interface NetWorthPrefill {
    value: number;
    fromYearMonth: string;
}

export interface NetWorthRow {
    accountId: string;
    value: number | null;
    prefill: NetWorthPrefill | null;
    note: string | null; // month-specific; never carried forward (so no note prefill)
}

export interface NetWorthMonth {
    yearMonth: string;
    rows: NetWorthRow[];
}

export interface NetWorthTotals {
    assets: number;
    liabilities: number;
    netWorth: number;
}

// The Excel-style wide history from GET /api/net-worth/history.
export interface NetWorthHistory {
    accounts: Account[]; // active accounts + any with history, in sortOrder
    months: string[]; // every month with a value, sorted ascending (YYYY-MM)
    values: Record<string, Record<string, number>>; // { yearMonth: { accountId: value } }
    notes: Record<string, Record<string, string>>; // { yearMonth: { accountId: note } } — only cells with a note
    totals: Record<string, NetWorthTotals>; // { yearMonth: totals }
}
