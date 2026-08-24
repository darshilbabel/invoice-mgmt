import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { customerLabel, fetchAllCustomers } from "../api/customers";
import { lineTotal, sumLines } from "../lib/money";
import type { Customer, Invoice, InvoiceInput, TransactionInput } from "../types";

const emptyLine = (): TransactionInput => ({ description: "", quantity: "1", unit_price: "0.00" });

/** Wireframe 1f — one form, line items inline, sticky running-total summary. */
export default function InvoiceForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isEdit = Boolean(id);

  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customer, setCustomer] = useState("");
  const [issueDate, setIssueDate] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<TransactionInput[]>([emptyLine()]);

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await fetchAllCustomers();
        if (cancelled) return;
        setCustomers(list);
        if (isEdit) {
          const invoice = await api.get<Invoice>(`/invoices/${id}/`);
          if (cancelled) return;
          setCustomer(String(invoice.customer.id));
          setIssueDate(invoice.issue_date);
          setDueDate(invoice.due_date);
          setNotes(invoice.notes);
          setLines(
            invoice.transactions.length
              ? invoice.transactions.map((t) => ({
                  description: t.description, quantity: t.quantity, unit_price: t.unit_price,
                }))
              : [emptyLine()],
          );
        } else if (list.length) {
          setCustomer(String(list[0].id));
        }
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Failed to load.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [id, isEdit]);

  function updateLine(index: number, patch: Partial<TransactionInput>) {
    setLines((current) => current.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSaving(true);
    const payload: InvoiceInput = {
      customer: Number(customer),
      due_date: dueDate,
      notes,
      // Rows with no description are dropped — an empty invoice is valid and totals 0.00.
      transactions: lines.filter((line) => line.description.trim() !== ""),
      ...(issueDate ? { issue_date: issueDate } : {}),
    };
    try {
      // PUT, not PATCH: update is replace-all, so this payload becomes the
      // complete set of line items (architecture.md section 5.2).
      const saved = isEdit
        ? await api.put<Invoice>(`/invoices/${id}/`, payload)
        : await api.post<Invoice>("/invoices/", payload);
      navigate(`/invoices/${saved.id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not save the invoice.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="muted">Loading…</p>;

  const counted = lines.filter((l) => l.description.trim() !== "");
  const runningTotal = sumLines(counted);

  return (
    <form onSubmit={handleSubmit}>
      <p className="crumb"><Link to="/invoices">Invoices</Link> / {isEdit ? "Edit" : "New"}</p>
      <div className="page-head">
        <h1>{isEdit ? "Edit invoice" : "New invoice"}</h1>
      </div>

      {error && <p role="alert" className="notice notice-danger" style={{ marginBottom: "var(--sp-16)" }}>{error}</p>}

      <section className="card card-pad" style={{ marginBottom: "var(--sp-24)" }}>
        <h2>Billing details</h2>
        <div className="form-grid" style={{ marginTop: "var(--sp-16)" }}>
          <label className="field">
            Customer
            <select value={customer} onChange={(e) => setCustomer(e.target.value)} required>
              {customers.map((c) => <option key={c.id} value={c.id}>{customerLabel(c)}</option>)}
            </select>
          </label>
          <label className="field">
            Issue date
            <input type="date" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} />
            <span className="hint">Defaults to today if left blank</span>
          </label>
          <label className="field">
            Due date
            <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} required />
          </label>
        </div>
        <label className="field" style={{ marginTop: "var(--sp-16)" }}>
          Notes
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          <span className="hint">Optional. Appears on the invoice.</span>
        </label>
      </section>

      <div className="row-between" style={{ marginBottom: "var(--sp-12)" }}>
        <h2>Line items</h2>
        <span className="hint">Quantity takes decimals — 2.5 hours is valid</span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Description</th><th className="right">Qty</th>
              <th className="right">Unit price</th><th className="right">Line total</th><th />
            </tr>
          </thead>
          <tbody>
            {lines.map((line, index) => (
              <tr key={index}>
                <td>
                  <input value={line.description} placeholder="Description"
                    onChange={(e) => updateLine(index, { description: e.target.value })} />
                </td>
                <td className="right">
                  <input className="num right" inputMode="decimal" value={line.quantity}
                    onChange={(e) => updateLine(index, { quantity: e.target.value })} style={{ textAlign: "right" }} />
                </td>
                <td className="right">
                  <input className="num right" inputMode="decimal" value={line.unit_price}
                    onChange={(e) => updateLine(index, { unit_price: e.target.value })} style={{ textAlign: "right" }} />
                </td>
                <td className="right num">{lineTotal(line.quantity, line.unit_price).toFixed(2)}</td>
                <td className="right">
                  <button type="button" className="btn-ghost btn-sm" aria-label="Remove line"
                    onClick={() => setLines((c) => (c.length === 1 ? [emptyLine()] : c.filter((_, i) => i !== index)))}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p style={{ marginTop: "var(--sp-12)" }}>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setLines((c) => [...c, emptyLine()])}>
          Add line
        </button>
      </p>

      <div className="summary-bar">
        <div>
          <span className="tile-label">Running total</span>
          <span className="summary-total">{runningTotal.toFixed(2)}</span>
          <p className="hint" style={{ margin: "var(--sp-4) 0 0" }}>
            Computed in the browser for feedback only. The server total is authoritative
            and replaces this on save. {counted.length} of {lines.length} rows counted —
            rows with no description are dropped.
          </p>
        </div>
        <div className="row">
          <button type="button" className="btn btn-secondary" onClick={() => navigate("/invoices")}>Cancel</button>
          <button type="submit" className="btn" disabled={saving}>
            {saving ? "Saving…" : isEdit ? "Save changes" : "Create invoice"}
          </button>
        </div>
      </div>
    </form>
  );
}
