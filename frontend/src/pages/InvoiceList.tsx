import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { Invoice, Paginated } from "../types";

export default function InvoiceList() {
  const { user } = useAuth();
  const canWrite = user?.role === "ADMIN" || user?.role === "STAFF";

  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Two-step inline confirm rather than window.confirm: a native dialog blocks
  // the whole page and cannot be styled.
  const [confirming, setConfirming] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const page = await api.get<Paginated<Invoice>>("/invoices/");
      setInvoices(page.results);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load invoices.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleDelete(id: number) {
    setError(null);
    try {
      await api.delete(`/invoices/${id}/`);
      setConfirming(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Delete failed.");
    }
  }

  if (error && !invoices) return <p role="alert" className="error">{error}</p>;
  if (!invoices) return <p>Loading…</p>;

  return (
    <section>
      <div className="row-between">
        <h1>Invoices</h1>
        {canWrite && <Link className="button" to="/invoices/new">New invoice</Link>}
      </div>

      {user?.role === "STAFF" && (
        <p className="muted">Showing invoices you created.</p>
      )}
      {error && <p role="alert" className="error">{error}</p>}

      {invoices.length === 0 ? (
        <p className="muted">No invoices yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Invoice</th>
              <th>Customer</th>
              <th>Issued</th>
              <th>Due</th>
              <th className="right">Total</th>
              {canWrite && <th className="right">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {invoices.map((invoice) => (
              <tr key={invoice.id}>
                <td><Link to={`/invoices/${invoice.id}/edit`}>{invoice.invoice_number}</Link></td>
                <td>{invoice.customer.name}</td>
                <td>{invoice.issue_date}</td>
                <td>{invoice.due_date}</td>
                {/* Rendered as the string the API returned — never reformatted. */}
                <td className="right">{invoice.total}</td>
                {canWrite && (
                  <td className="right">
                    {confirming === invoice.id ? (
                      <>
                        <button type="button" onClick={() => void handleDelete(invoice.id)}>
                          Confirm
                        </button>{" "}
                        <button type="button" className="link" onClick={() => setConfirming(null)}>
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button type="button" className="link" onClick={() => setConfirming(invoice.id)}>
                        Delete
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
