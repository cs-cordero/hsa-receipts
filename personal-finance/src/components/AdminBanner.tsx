interface Props {
    onTurnOff: () => void;
}

export default function AdminBanner({ onTurnOff }: Props) {
    return (
        <div className="admin-banner" role="alert">
            <span className="admin-banner-text">Admin mode active — your changes can bypass lock and grace rules.</span>
            <button className="admin-banner-btn" onClick={onTurnOff}>
                Turn off
            </button>
        </div>
    );
}
