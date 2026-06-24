export type Stage = "dev" | "prod";

export const HSA_DOMAIN = "hsa.corderohq.com";
export const AUTH_DOMAIN = "auth.corderohq.com";
export const API_DOMAIN = "api.hsa.corderohq.com";
export const HSA_ORIGIN = `https://${HSA_DOMAIN}`;

export const PERSONAL_FINANCE_DOMAIN = "finance.corderohq.com";

export function personalFinanceDomain(stage: Stage): string {
    return stage === "prod" ? PERSONAL_FINANCE_DOMAIN : `dev.${PERSONAL_FINANCE_DOMAIN}`;
}

export function personalFinanceOrigin(stage: Stage): string {
    return `https://${personalFinanceDomain(stage)}`;
}
