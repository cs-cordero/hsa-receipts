interface LoadingOverlayProps {
    message: string;
    visible: boolean;
}

export default function LoadingOverlay({ message, visible }: LoadingOverlayProps) {
    if (!visible) return null;
    return (
        <div className="loading-overlay">
            <div className="loading-content">
                <div className="spinner" />
                <p>{message}</p>
            </div>
        </div>
    );
}
