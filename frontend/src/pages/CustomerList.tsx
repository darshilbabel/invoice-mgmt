import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api } from "../api/client";
import { fetchAllCustomers } from "../api/customers";
import { useAuth } from "../auth/AuthContext";
import type { Customer } from "../types";

/**
 * NOTE: there is no wireframe for this screen.
 *
 * The design canvas shows a Customers nav item in all eight product frames but
 * never draws the screen. This is built to match wireframe 1c's table rhythm —
 * same filter bar, same inline two-step delete — so it reads as part of the set.
 */

const blank = { name: "", email: "", company_name: "", billing_address: "" };

export default function CustomerList() {
  const { user } = useAuth();
  const canWrite = user?.role === "ADMIN" || user?.role === "STAFF";

  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);

  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState({ ...blank });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setCustomers(await fetchAllCustomers());
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load customers.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  function openNew() { setDraft({ ...blank }); setEditing("new"); setError(null); }
  function openEdit(c: Customer) {
    setDraft({ name: c.name, email: c.email, company_name: c.company_name, billing_address: c.billing_address });
    setEditing(c.id);
    setError(null);
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (editing === "new") await api.post("/customers/", draft);
      else await api.patch(`/customers/${editing}/`, draft);
      setEditing(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save the customer.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    setError(null);
    try {
      await api.delete(`/customers/${id}/`);
      setConfirming(null);
      await load();
    } catch (caught) {
      // The API refuses to delete a customer that has invoices and explains why
      // (400, PROTECT). Surface that message rather than a generic failure.
      setError(caught instanceof Error ? caught.message : "Delete failed.");
      setConfirming(null);
    }
  }

  const visible = (customers ?? []).filter((c) =>
    `${c.name} ${c.company_name} ${c.email}`.toLowerCase().includes(search.trim().toLowerCase()),
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Customers</h1>
          <p className="muted" style={{ margin: "var(--sp-4) 0 0", font: "var(--type-body-sm)" }}>
            {customers?.length ?? 0} total · used by the invoice form's customer picker
          </p>
        </div>
        {canWrite && <button type="button" className="btn" onClick={openNew}>New customer</button>}
      </div>

      <div className="filters">
        <input className="grow" type="search" placeholder="Search name, company or email"
          value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search customers" />
      </div>

      {error && <p role="alert" className="notice notice-danger" style={{ marginBottom: "var(--sp-16)" }}>{error}</p>}

      {editing !== null && (
        <form className="card card-pad" onSubmit={handleSave} style={{ marginBottom: "var(--sp-24)" }}>
          <h2>{editing === "new" ? "New customer" : "Edit customer"}</h2>
          <div className="form-grid" style={{ marginTop: "var(--sp-16)" }}>
            <label className="field">
              Name
              <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} required />
            </label>
            <label className="field">
              Company
              <input value={draft.company_name} onChange={(e) => setDraft({ ...draft, company_name: e.target.value })} />
            </label>
            <label className="field">
              Email
              <input type="email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} />
            </label>
          </div>
          <label className="field" style={{ marginTop: "var(--sp-16)" }}>
            Billing address
            <textarea rows={2} value={draft.billing_address}
              onChange={(e) => setDraft({ ...draft, billing_address: e.target.value })} />
          </label>
          <div className="row" style={{ marginTop: "var(--sp-16)" }}>
            <button type="submit" className="btn" disabled={saving}>{saving ? "Saving…" : "Save customer"}</button>
            <button type="button" className="btn-ghost" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </form>
      )}

      {!customers ? (
        <p className="muted">Loading…</p>
      ) : visible.length === 0 ? (
        <p className="notice notice-muted">No customers match.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th><th>Company</th><th>Email</th><th>Billing address</th>
                {canWrite && <th className="right">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {visible.map((c) => (
                <tr key={c.id}>
                  <td className="cell-strong">{c.name}</td>
                  <td>{c.company_name || <span className="subtle">—</span>}</td>
                  <td>{c.email ? <a href={`mailto:${c.email}`}>{c.email}</a> : <span className="subtle">—</span>}</td>
                  <td className="muted">{c.billing_address || <span className="subtle">—</span>}</td>
                  {canWrite && (
                    <td className="right">
                      {confirming === c.id ? (
                        <span className="row" style={{ justifyContent: "flex-end", gap: "var(--sp-4)" }}>
                          <button type="button" className="btn btn-danger btn-sm" onClick={() => void handleDelete(c.id)}>Confirm</button>
                          <button type="button" className="btn-ghost btn-sm" onClick={() => setConfirming(null)}>Cancel</button>
                        </span>
                      ) : (
                        <span className="row" style={{ justifyContent: "flex-end", gap: "var(--sp-4)" }}>
                          <button type="button" className="btn-ghost btn-sm" onClick={() => openEdit(c)}>Edit</button>
                          <button type="button" className="btn-ghost btn-sm danger" onClick={() => setConfirming(c.id)}>Delete</button>
                        </span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
