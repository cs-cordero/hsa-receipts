import { useState } from "react";
import { ApiError } from "./api";
import { IS_DEV } from "./dev";

type StatusType = "info" | "success" | "error" | "loading" | "";

interface Status {
    message: string;
    type: StatusType;
}

export function useStatus() {
    const [status, setStatus] = useState<Status>({ message: "", type: "" });

    const showInfo = (message: string) => setStatus({ message, type: "info" });
    const showLoading = (message: string) => setStatus({ message, type: "loading" });
    const showSuccess = (message: string) => setStatus({ message, type: "success" });
    const showError = (err: unknown) => {
        if (IS_DEV) {
            console.error(err);
        }
        let message: string;
        if (IS_DEV && err instanceof ApiError) {
            message = `ApiError ${err.status} ${err.url}\n${err.responseBody || err.message}`;
            if (err.stack) {
                message += `\n\n${err.stack}`;
            }
        } else if (IS_DEV && err instanceof Error) {
            message = `${err.name}: ${err.message}`;
            if (err.stack) {
                message += `\n\n${err.stack}`;
            }
        } else {
            const text = err instanceof Error ? err.message : String(err);
            message = `Error: ${text}`;
        }
        setStatus({ message, type: "error" });
        // StatusMessage renders at the top of the page; scroll the viewport up so the
        // user actually sees the error even if they triggered it while scrolled down.
        if (typeof window !== "undefined") {
            window.scrollTo({ top: 0, behavior: "smooth" });
        }
    };
    const clear = () => setStatus({ message: "", type: "" });

    return { status, showInfo, showLoading, showSuccess, showError, clear };
}
