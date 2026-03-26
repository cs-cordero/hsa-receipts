interface StatusMessageProps {
    message: string;
    type: "info" | "success" | "error" | "loading" | "";
}

export default function StatusMessage({ message, type }: StatusMessageProps) {
    if (!message) return null;
    const style = type === "error" ? { whiteSpace: "pre-wrap" as const } : undefined;
    return (
        <div className={`status status-${type}`} style={style}>
            {message}
        </div>
    );
}
