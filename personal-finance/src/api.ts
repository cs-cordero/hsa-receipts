import { getAccessToken } from "./auth";
import { getSimulatedDate } from "./simulated_date";
import {
    parseAuditEntryArray,
    parseBudgetTargetArray,
    parseCategory,
    parseCategoryArray,
    parseCategoryGroup,
    parseCategoryGroupArray,
    parseCommitResult,
    parseDeactivateResult,
    parseDeletedCount,
    parseDeletedGroup,
    parseDeletionPreview,
    parseHardDeleteResult,
    parsePinResult,
    parseSummary,
    parseTransaction,
    parseTransactionArray,
    parseUploadResult,
} from "./parsers";
import type { Transaction } from "./types";

const API_BASE = "/api";

export class ApiError extends Error {
    constructor(
        message: string,
        public readonly status: number,
        public readonly url: string,
        public readonly responseBody: string,
    ) {
        super(message);
        this.name = "ApiError";
    }
}

async function request<T>(path: string, parse: (raw: unknown) => T, options: RequestInit = {}): Promise<T> {
    const token = await getAccessToken();
    const url = `${API_BASE}${path}`;
    // X-Simulated-Date is a dev-only override (see simulated_date.ts). getSimulatedDate
    // returns null outside dev mode, so prod requests never carry it.
    const simulatedDate = getSimulatedDate();
    const response = await fetch(url, {
        ...options,
        headers: {
            Authorization: `Bearer ${token}`,
            ...(simulatedDate ? { "X-Simulated-Date": simulatedDate } : {}),
            ...options.headers,
        },
    });

    if (!response.ok) {
        const text = await response.text();
        throw new ApiError(text || `Request failed: ${response.status}`, response.status, url, text);
    }

    const text = await response.text();
    const raw: unknown = text ? JSON.parse(text) : undefined;
    return parse(raw);
}

function jsonBody(data: unknown): RequestInit {
    return {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    };
}

// Category groups
export const fetchCategoryGroups = () => request("/category-groups", parseCategoryGroupArray);
export const createCategoryGroup = (name: string) =>
    request("/category-groups", parseCategoryGroup, { method: "POST", ...jsonBody({ name }) });
export const renameCategoryGroup = (id: string, name: string) =>
    request(`/category-groups/${id}`, parseCategoryGroup, { method: "PUT", ...jsonBody({ name }) });
export const deleteCategoryGroup = (id: string) =>
    request(`/category-groups/${id}`, parseDeletedGroup, { method: "DELETE" });
export const reorderCategoryGroups = (order: string[]) =>
    request("/category-groups/reorder", parseCategoryGroupArray, {
        method: "POST",
        ...jsonBody({ order }),
    });

// Categories
export const fetchCategories = () => request("/categories", parseCategoryArray);
export const fetchAllCategories = () => request("/categories?include_inactive=true", parseCategoryArray);
export const createCategory = (name: string, groupId: string, initialTarget = 0) =>
    request("/categories", parseCategory, {
        method: "POST",
        ...jsonBody({ name, initialTarget, groupId }),
    });
export const updateCategory = (id: string, updates: { name?: string; groupId?: string }) =>
    request(`/categories/${id}`, parseCategory, { method: "PUT", ...jsonBody(updates) });
export const reorderCategoriesInGroup = (groupId: string, order: string[]) =>
    request("/categories/reorder", parseCategoryArray, {
        method: "POST",
        ...jsonBody({ groupId, order }),
    });
export const deactivateCategory = (id: string, opts: { confirm?: boolean; explanation?: string } = {}) =>
    request(`/categories/${id}/deactivate`, parseDeactivateResult, {
        method: "POST",
        ...jsonBody(opts),
    });
export const reactivateCategory = (id: string) =>
    request(`/categories/${id}/reactivate`, parseCategory, { method: "POST" });
export const fetchCategoryDeletionPreview = (id: string) =>
    request(`/categories/${id}?deletion_preview=true`, parseDeletionPreview);
export const hardDeleteCategory = (id: string, opts: { confirm: true; confirmName: string; explanation: string }) =>
    request(`/categories/${id}`, parseHardDeleteResult, {
        method: "DELETE",
        ...jsonBody(opts),
    });

// Budget
export const fetchBudget = (yearMonth: string) => request(`/budget/${yearMonth}`, parseBudgetTargetArray);
export const replaceBudget = (
    yearMonth: string,
    targets: { categoryId: string; amount: number }[],
    explanation: string,
    override = false,
) =>
    request(`/budget/${yearMonth}/replace`, parseBudgetTargetArray, {
        method: "POST",
        ...jsonBody({ targets, explanation, ...(override ? { override: true } : {}) }),
    });
export const pinBudget = (
    yearMonth: string,
    targets: { categoryId: string; amount: number | null }[],
    explanation: string,
) =>
    request(`/budget/${yearMonth}/pin`, parsePinResult, {
        method: "POST",
        ...jsonBody({ targets, explanation }),
    });

// Transactions
export const fetchTransactions = (yearMonth: string) =>
    request(`/transactions?month=${yearMonth}`, parseTransactionArray);
export const createTransaction = (
    data: {
        yearMonth: string;
        transactionDate: string;
        description: string;
        amount: number;
        categoryId: string;
    },
    override = false,
) =>
    request("/transactions", parseTransaction, {
        method: "POST",
        ...jsonBody({ ...data, ...(override ? { override: true } : {}) }),
    });
export const updateTransaction = (
    yearMonth: string,
    sortId: string,
    updates: Partial<Pick<Transaction, "description" | "amount" | "categoryId">>,
    override = false,
) =>
    request("/transactions/update", parseTransaction, {
        method: "POST",
        ...jsonBody({ yearMonth, sortId, ...updates, ...(override ? { override: true } : {}) }),
    });
export const deleteTransactions = (items: { yearMonth: string; sortId: string }[], override = false) =>
    request("/transactions/delete", parseDeletedCount, {
        method: "POST",
        ...jsonBody({ items, ...(override ? { override: true } : {}) }),
    });
export const uploadTransactions = (csvData: string) =>
    request("/transactions/upload", parseUploadResult, {
        method: "POST",
        ...jsonBody({ csvData }),
    });
export const commitTransactions = (
    rows: { transactionDate: string; description: string; amount: number; categoryId: string }[],
    override = false,
) =>
    request("/transactions/commit", parseCommitResult, {
        method: "POST",
        ...jsonBody({ rows, ...(override ? { override: true } : {}) }),
    });

// Summary
export const fetchSummary = (yearMonth: string) => request(`/summary?month=${yearMonth}`, parseSummary);

// Audit log
export const fetchAuditLog = (limit = 10) => request(`/audit-log?limit=${limit}`, parseAuditEntryArray);
