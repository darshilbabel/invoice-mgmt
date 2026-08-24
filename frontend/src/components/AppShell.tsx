import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";

import { useAuth } from "../auth/AuthContext";

/**
 * Top bar shared by every signed-in screen.
 *
 * The 4px gradient rule under the bar is the only place the signature
 * violet->amber gradient appears in the whole app — the design system forbids
 * it as a background or a fill.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <span className="brand">Invoice manager</span>
          <nav className="row" style={{ gap: "var(--sp-20)" }}>
            <NavLink to="/" end className={({ isActive }) => `navlink${isActive ? " active" : ""}`}>
              Dashboard
            </NavLink>
            <NavLink to="/invoices" className={({ isActive }) => `navlink${isActive ? " active" : ""}`}>
              Invoices
            </NavLink>
            <NavLink to="/customers" className={({ isActive }) => `navlink${isActive ? " active" : ""}`}>
              Customers
            </NavLink>
          </nav>
          {user && (
            <div className="row spacer">
              <span className="whoami">
                {user.full_name} · <span className="eyebrow">{user.role}</span>
              </span>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => void logout()}>
                Sign out
              </button>
            </div>
          )}
        </div>
        <div className="topbar-rule" />
      </header>
      <main className="page">{children}</main>
    </>
  );
}
