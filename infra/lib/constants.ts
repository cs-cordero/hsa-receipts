export type Stage = "dev" | "prod";

export const HSA_DOMAIN = "hsa.corderohq.com";
export const AUTH_DOMAIN = "auth.corderohq.com";
export const API_DOMAIN = "api.hsa.corderohq.com";
export const HSA_ORIGIN = `https://${HSA_DOMAIN}`;

export const BUDGET_DOMAIN = "budget.corderohq.com";

export function budgetDomain(stage: Stage): string {
    return stage === "prod" ? BUDGET_DOMAIN : `dev.${BUDGET_DOMAIN}`;
}

export function budgetOrigin(stage: Stage): string {
    return `https://${budgetDomain(stage)}`;
}
