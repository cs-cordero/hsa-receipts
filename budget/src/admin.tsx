/**
 * Admin-mode context. Tracks two things:
 *
 * - `isAdminUser` — derived from the JWT `cognito:groups` claim. The user has
 *   admin capability if `budget-admin-{stage}` is in their groups. This is
 *   cached for the session; if the token refreshes and groups change, a page
 *   refresh picks up the new state. (Backend re-verifies on every request, so
 *   nothing security-sensitive depends on this client-side flag.)
 *
 * - `adminModeOn` — per-tab toggle, defaults to off, never persisted. The
 *   banner + tinted header (see Layout/AdminBanner) are the safety net.
 */

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { getCurrentUserGroups } from "./auth";
import { getConfig } from "./config";

interface AdminContextValue {
    isAdminUser: boolean;
    adminModeOn: boolean;
    setAdminModeOn: (on: boolean) => void;
}

const AdminContext = createContext<AdminContextValue | null>(null);

export function AdminProvider({ children }: { children: ReactNode }) {
    const [adminModeOn, setAdminModeOn] = useState(false);
    const isAdminUser = useMemo(() => {
        const expected = `budget-admin-${getConfig().stage}`;
        return getCurrentUserGroups().includes(expected);
    }, []);

    return (
        <AdminContext.Provider value={{ isAdminUser, adminModeOn, setAdminModeOn }}>{children}</AdminContext.Provider>
    );
}

export function useAdmin(): AdminContextValue {
    const ctx = useContext(AdminContext);
    if (!ctx) {
        throw new Error("useAdmin must be used inside <AdminProvider>");
    }
    return ctx;
}
