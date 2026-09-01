import { NavLink, Outlet } from "react-router-dom";
import { useAdmin } from "../admin";
import { signOut } from "../auth";
import AdminBanner from "./AdminBanner";
import DevBanner from "./DevBanner";
import DevSimulationInfoModal from "./DevSimulationInfoModal";

export default function Layout() {
    const { isAdminUser, adminModeOn, setAdminModeOn } = useAdmin();

    return (
        <div className={`app${adminModeOn ? " admin-mode" : ""}`}>
            <DevSimulationInfoModal />
            <DevBanner />
            {adminModeOn && <AdminBanner onTurnOff={() => setAdminModeOn(false)} />}
            <header>
                <nav>
                    <span className="logo">Personal Finance</span>
                    <NavLink to="/">Summary</NavLink>
                    <NavLink to="/budget">Budget</NavLink>
                    <NavLink to="/transactions">Transactions</NavLink>
                    <NavLink to="/upload">Upload</NavLink>
                    <NavLink to="/categories">Categories</NavLink>
                    <NavLink to="/accounts">Accounts</NavLink>
                    <NavLink to="/net-worth">Net Worth</NavLink>
                    <NavLink to="/audit-log">Audit Log</NavLink>
                    {isAdminUser && <NavLink to="/admin">Admin</NavLink>}
                    {isAdminUser && (
                        <label className="admin-toggle" title="Toggle admin mode">
                            <input
                                type="checkbox"
                                checked={adminModeOn}
                                onChange={(e) => setAdminModeOn(e.target.checked)}
                            />
                            <span>Admin</span>
                        </label>
                    )}
                    <button className="sign-out-btn" onClick={signOut}>
                        Sign Out
                    </button>
                </nav>
            </header>
            <main>
                <Outlet />
            </main>
        </div>
    );
}
