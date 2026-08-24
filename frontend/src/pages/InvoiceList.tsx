import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { fetchAllCustomers } from "../api/customers";
import { useAuth } from "../auth/AuthContext";
import { daysLate } from "../lib/money";
import type { Customer, Invoice, Paginated } from "../types";

/** Wireframe 1c — one dense full-width table with a filter bar above it. */
export default function InvoiceList() {
  const { user } = useAuth();
  const canWrite = user?.role === "ADMIN" || user?.role === "STAFF";

  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [count, setCount] = useState(0);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);

  const [search, setSearch] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [dueBefore, setDueBefore] = useState("");
  const [overdueOnly, setOverdueOnly] = useState(false);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (search.trim()) params.set("search", search.trim());
    if (customerId) params.set("customer", customerId);
    if (dueBefore) params.set("due_date", dueBefore);
    // Server-side, so the toggle filters the dataset rather than one page.
    if (overdueOnly) params.set("overdue", "true");
    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }, [search, customerId, dueBefore, overdueOnly]);

  const load = useCallback(async () => {
    try {
      const page = await api.get<Paginated<Invoice>>(`/invoices/${query}`);
      setInvoices(page.results);
      setCount(page.count);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load invoices.");
    }
  }, [query]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { void fetchAllCustomers().then(setCustomers).catch(() => setCustomers([])); }, []);

  async function handleDelete(id: number) {
    try {
      await api.delete(`/invoices/${id}/`);
      setConfirming(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Delete failed.");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Invoices</h1>
          <p className="muted" style={{ margin: "var(--sp-4) 0 0", font: "var(--type-body-sm)" }}>
            {count} total{user?.role === "STAFF" ? " · showing invoices you created" : ""}
          </p>
        </div>
        {canWrite && (
          <div className="row">
            <Link className="btn btn-secondary" to="/invoices/upload">Upload PDF</Link>
            <Link className="btn" to="/invoices/new">New invoice</Link>
          </div>
        )}
      </div>

      <div className="filters">
        <input
          className="grow"
          type="search"
          placeholder="Search invoice number or customer"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search invoices"
        />
        <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} aria-label="Filter by customer">
          <option value="">All customers</option>
          {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <input type="date" value={dueBefore} onChange={(e) => setDueBefore(e.target.value)} aria-label="Due date" />
        <label className="check">
          <input type="checkbox" checked={overdueOnly} onChange={(e) => setOverdueOnly(e.target.checked)} />
          Overdue only
        </label>
        {(search || customerId || dueBefore || overdueOnly) && (
          <button type="button" className="btn-ghost"
            onClick={() => { setSearch(""); setCustomerId(""); setDueBefore(""); setOverdueOnly(false); }}>
            Clear
          </button>
        )}
      </div>

      {error && <p role="alert" className="notice notice-danger" style={{ marginBottom: "var(--sp-16)" }}>{error}</p>}

      {!invoices ? (
        <p className="muted">Loading…</p>
      ) : invoices.length === 0 ? (
        <p className="notice notice-muted">No invoices match these filters.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Invoice</th><th>Customer</th><th>Issued</th><th>Due</th>
                <th className="right">Lines</th><th className="right">Total</th>
                {canWrite && <th className="right">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice) => {
                const late = daysLate(invoice.due_date);
                return (
                  <tr key={invoice.id}>
                    <td><Link className="cell-strong" to={`/invoices/${invoice.id}`}>{invoice.invoice_number}</Link></td>
                    <td>
                      {invoice.customer.name}
                      {invoice.customer.company_name && (
                        <span className="cell-sub">{invoice.customer.company_name}</span>
                      )}
                    </td>
                    <td className="num">{invoice.issue_date}</td>
                    <td className="num">
                      {invoice.due_date}
                      {late > 0 && <span className="badge badge-danger" style={{ marginLeft: "var(--sp-8)" }}>{late}d late</span>}
                    </td>
                    <td className="right num">{invoice.transactions.length}</td>
                    <td className="right num cell-strong">{invoice.total}</td>
                    {canWrite && (
                      <td className="right">
                        {confirming === invoice.id ? (
                          <span className="row" style={{ justifyContent: "flex-end", gap: "var(--sp-4)" }}>
                            <button type="button" className="btn btn-danger btn-sm" onClick={() => void handleDelete(invoice.id)}>Confirm</button>
                            <button type="button" className="btn-ghost btn-sm" onClick={() => setConfirming(null)}>Cancel</button>
                          </span>
                        ) : (
                          <span className="row" style={{ justifyContent: "flex-end", gap: "var(--sp-4)" }}>
                            <Link className="btn-ghost btn-sm" to={`/invoices/${invoice.id}/edit`}>Edit</Link>
                            <button type="button" className="btn-ghost btn-sm danger" onClick={() => setConfirming(invoice.id)}>Delete</button>
                          </span>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
