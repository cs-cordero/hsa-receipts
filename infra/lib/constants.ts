export type Stage = "dev" | "prod";

export const ROOT_DOMAIN = "corderohq.com";
export const WWW_DOMAIN = `www.${ROOT_DOMAIN}`;

export const HSA_DOMAIN = `hsa.${ROOT_DOMAIN}`;
export const AUTH_DOMAIN = `auth.${ROOT_DOMAIN}`;
export const API_DOMAIN = `api.${HSA_DOMAIN}`;
export const HSA_ORIGIN = `https://${HSA_DOMAIN}`;

export const PERSONAL_FINANCE_DOMAIN = `finance.${ROOT_DOMAIN}`;

export const MATH_DOMAIN = `math.${ROOT_DOMAIN}`;

export function personalFinanceDomain(stage: Stage): string {
    return stage === "prod" ? PERSONAL_FINANCE_DOMAIN : `dev.${PERSONAL_FINANCE_DOMAIN}`;
}

export function personalFinanceOrigin(stage: Stage): string {
    return `https://${personalFinanceDomain(stage)}`;
}
