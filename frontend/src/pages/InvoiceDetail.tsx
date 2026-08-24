import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { daysLate } from "../lib/money";
import type { Invoice } from "../types";

/** Wireframe 1h — read-only invoice view. */
export default function InvoiceDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canWrite = user?.role === "ADMIN" || user?.role === "STAFF";

  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .get<Invoice>(`/invoices/${id}/`)
      .then((data) => !cancelled && setInvoice(data))
      .catch((e: unknown) =>
        !cancelled && setError(e instanceof Error ? e.message : "Failed to load."),
      );
    return () => { cancelled = true; };
  }, [id]);

  async function handleDelete() {
    try {
      await api.delete(`/invoices/${id}/`);
      navigate("/invoices");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Delete failed.");
      setConfirming(false);
    }
  }

  if (error) return <p role="alert" className="notice notice-danger">{error}</p>;
  if (!invoice) return <p className="muted">Loading…</p>;

  const late = daysLate(invoice.due_date);
  const customer = invoice.customer;

  return (
    <>
      <p className="crumb">
        <Link to="/invoices">Invoices</Link> / {invoice.invoice_number}
      </p>

      <div className="page-head">
        <div>
          <div className="row" style={{ gap: "var(--sp-12)" }}>
            <h1>{invoice.invoice_number}</h1>
            {late > 0 && <span className="badge badge-danger">{late} days overdue</span>}
          </div>
          <p className="muted" style={{ margin: "var(--sp-4) 0 0", font: "var(--type-body-sm)" }}>
            {customer.company_name || customer.name} · issued {invoice.issue_date} · due {invoice.due_date}
          </p>
        </div>
        {canWrite && (
          <div className="row">
            {confirming ? (
              <>
                <button type="button" className="btn btn-danger" onClick={() => void handleDelete()}>Confirm delete</button>
                <button type="button" className="btn btn-secondary" onClick={() => setConfirming(false)}>Cancel</button>
              </>
            ) : (
              <>
                <button type="button" className="btn btn-secondary" onClick={() => setConfirming(true)}>Delete</button>
                <Link className="btn" to={`/invoices/${invoice.id}/edit`}>Edit invoice</Link>
              </>
            )}
          </div>
        )}
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Description</th><th className="right">Qty</th>
              <th className="right">Unit price</th><th className="right">Line total</th>
            </tr>
          </thead>
          <tbody>
            {invoice.transactions.length === 0 ? (
              <tr><td colSpan={4} className="muted">No line items.</td></tr>
            ) : (
              invoice.transactions.map((line) => (
                <tr key={line.id}>
                  <td>{line.description}</td>
                  <td className="right num">{line.quantity}</td>
                  <td className="right num">{line.unit_price}</td>
                  <td className="right num">{line.line_total}</td>
                </tr>
              ))
            )}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={3} className="right">Total</td>
              <td className="right num cell-strong">{invoice.total}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="detail-grid">
        <section className="card card-pad">
          <h2>Notes</h2>
          <p className="muted" style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
            {invoice.notes || "No notes on this invoice."}
          </p>
        </section>

        <section className="card card-pad">
          <h2>Billed to</h2>
          <div className="stack" style={{ marginTop: "var(--sp-8)" }}>
            <span className="cell-strong">{customer.company_name || customer.name}</span>
            {customer.company_name && <span className="muted">{customer.name}</span>}
            {customer.email && <a href={`mailto:${customer.email}`}>{customer.email}</a>}
            {customer.billing_address && (
              <span className="muted" style={{ whiteSpace: "pre-wrap" }}>{customer.billing_address}</span>
            )}
          </div>
          <p className="hint" style={{ marginBottom: 0, marginTop: "var(--sp-16)" }}>
            Raised by {invoice.created_by.full_name}
          </p>
        </section>
      </div>
    </>
  );
}
