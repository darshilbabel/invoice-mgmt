import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

/**
 * Wireframe 2b — split brand panel and form.
 *
 * The left panel is the only place in the product where the role model is ever
 * stated to a user, and the only screen carrying the deep violet.
 */
export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const from =
    (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? "/";
  if (user) return <Navigate to={from} replace />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (caught) {
      // The API returns one message for unknown email and wrong password alike.
      // The UI must not elaborate on which.
      setError(caught instanceof Error ? caught.message : "Sign in failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login">
      <section className="login-panel">
        <span className="eyebrow" style={{ color: "var(--violet-300)" }}>Invoice manager</span>
        <h1>Raise, track and close invoices in one place.</h1>
        <ul className="login-rules">
          <li><strong>Admins</strong> see every invoice.</li>
          <li><strong>Staff</strong> see the ones they raised.</li>
          <li><strong>Viewers</strong> read only.</li>
        </ul>
        <p className="login-rules" style={{ margin: 0 }}>
          <span>Access is granted by an admin.</span>
        </p>
      </section>

      <section className="login-form-side">
        <form className="login-form" onSubmit={handleSubmit}>
          <div className="stack" style={{ gap: "var(--sp-4)" }}>
            <h1>Sign in</h1>
            <p className="muted" style={{ margin: 0, font: "var(--type-body-sm)" }}>
              Use the email your account was created with.
            </p>
          </div>

          {error && (
            <p role="alert" className="notice notice-danger" style={{ margin: 0 }}>
              {error}
            </p>
          )}

          <label className="field">
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              required
              autoFocus
            />
          </label>

          <label className="field">
            Password
            <span className="pw-wrap">
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
              <button
                type="button"
                className="pw-toggle"
                onClick={() => setShowPassword((v) => !v)}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </span>
          </label>

          <button type="submit" className="btn" disabled={submitting} style={{ justifyContent: "center" }}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>

          <p className="hint" style={{ margin: 0 }}>
            No self-serve sign-up. Accounts are created by an admin.
          </p>
        </form>
      </section>
    </div>
  );
}
