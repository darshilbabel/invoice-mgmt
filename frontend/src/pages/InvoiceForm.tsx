import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { Customer, Invoice, InvoiceInput, Paginated, TransactionInput } from "../types";

const emptyLine = (): TransactionInput => ({
  description: "",
  quantity: "1",
  unit_price: "0.00",
});

/**
 * Display-only line total.
 *
 * Mirrors the server's rule (round each line to cents, then sum) so the running
 * total does not disagree with what comes back. The server value is always
 * authoritative — this never leaves the browser.
 */
function lineTotal(quantity: string, unitPrice: string): number {
  const value = Number(quantity) * Number(unitPrice);
  if (!Number.isFinite(value)) return 0;
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

/** DRF paginates customers at 20; walk `next` so the picker lists them all. */
async function fetchAllCustomers(): Promise<Customer[]> {
  const all: Customer[] = [];
  let path: string | null = "/customers/";
  while (path) {
    const page: Paginated<Customer> = await api.get<Paginated<Customer>>(path);
    all.push(...page.results);
    path = page.next ? new URL(page.next).pathname.replace(/^\/api/, "") + new URL(page.next).search : null;
  }
  return all;
}

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

  const [serverTotal, setServerTotal] = useState<string | null>(null);
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
          setServerTotal(invoice.total);
          setLines(
            invoice.transactions.length
              ? invoice.transactions.map((t) => ({
                  description: t.description,
                  quantity: t.quantity,
                  unit_price: t.unit_price,
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
    return () => {
      cancelled = true;
    };
  }, [id, isEdit]);

  function updateLine(index: number, patch: Partial<TransactionInput>) {
    setLines((current) =>
      current.map((line, i) => (i === index ? { ...line, ...patch } : line)),
    );
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSaving(true);

    const payload: InvoiceInput = {
      customer: Number(customer),
      due_date: dueDate,
      notes,
      // Blank rows are dropped rather than rejected — an empty invoice is valid
      // and totals 0.00.
      transactions: lines.filter((line) => line.description.trim() !== ""),
      ...(issueDate ? { issue_date: issueDate } : {}),
    };

    try {
      // PUT, not PATCH: update is replace-all, so the payload's lines become the
      // complete set (architecture.md section 5.2).
      const saved = isEdit
        ? await api.put<Invoice>(`/invoices/${id}/`, payload)
        : await api.post<Invoice>("/invoices/", payload);
      setServerTotal(saved.total);
      navigate("/invoices");
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Could not save the invoice.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p>Loading…</p>;

  const runningTotal = lines
    .filter((line) => line.description.trim() !== "")
    .reduce((sum, line) => sum + lineTotal(line.quantity, line.unit_price), 0);

  return (
    <form onSubmit={handleSubmit}>
      <h1>{isEdit ? "Edit invoice" : "New invoice"}</h1>
      {error && <p role="alert" className="error">{error}</p>}

      <div className="fields">
        <label>
          Customer
          <select value={customer} onChange={(e) => setCustomer(e.target.value)} required>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.company_name ? `${c.name} (${c.company_name})` : c.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Issue date
          <input type="date" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} />
        </label>
        <label>
          Due date
          <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} required />
        </label>
      </div>

      <label>
        Notes
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
      </label>

      <h2>Line items</h2>
      <table>
        <thead>
          <tr>
            <th>Description</th>
            <th className="right">Qty</th>
            <th className="right">Unit price</th>
            <th className="right">Line total</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {lines.map((line, index) => (
            <tr key={index}>
              <td>
                <input
                  value={line.description}
                  onChange={(e) => updateLine(index, { description: e.target.value })}
                  placeholder="Description"
                />
              </td>
              <td className="right">
                <input
                  className="num"
                  inputMode="decimal"
                  value={line.quantity}
                  onChange={(e) => updateLine(index, { quantity: e.target.value })}
                />
              </td>
              <td className="right">
                <input
                  className="num"
                  inputMode="decimal"
                  value={line.unit_price}
                  onChange={(e) => updateLine(index, { unit_price: e.target.value })}
                />
              </td>
              <td className="right">{lineTotal(line.quantity, line.unit_price).toFixed(2)}</td>
              <td className="right">
                <button
                  type="button"
                  className="link"
                  onClick={() => setLines((c) => (c.length === 1 ? [emptyLine()] : c.filter((_, i) => i !== index)))}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={3} className="right"><strong>Total</strong></td>
            <td className="right"><strong>{runningTotal.toFixed(2)}</strong></td>
            <td />
          </tr>
        </tfoot>
      </table>

      <p>
        <button type="button" className="link" onClick={() => setLines((c) => [...c, emptyLine()])}>
          + Add line
        </button>
      </p>

      {serverTotal !== null && (
        <p className="muted">Server total: {serverTotal} (authoritative)</p>
      )}

      <p>
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : isEdit ? "Save changes" : "Create invoice"}
        </button>{" "}
        <button type="button" className="link" onClick={() => navigate("/invoices")}>
          Cancel
        </button>
      </p>
    </form>
  );
}
