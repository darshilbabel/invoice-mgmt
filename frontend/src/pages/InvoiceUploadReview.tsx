import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { customerLabel, fetchAllCustomers } from "../api/customers";
import { formatBytes } from "../api/extraction";
import { useUploadDraft } from "../components/UploadDraftRoute";
import { lineTotal, sumLines } from "../lib/money";
import type { Customer, ExtractionResult, Invoice, InvoiceInput, TransactionInput } from "../types";

/**
 * Wireframe 3c — check the extracted fields, then save.
 *
 * Two things this screen does NOT do, both deliberate:
 *
 *  - It never treats `printed_total` as the invoice's total. The figure it shows
 *    is always sumLines() over the rows below, mirroring the server's
 *    round-per-line-then-sum rule (domain.md). The printed figure sits beside it
 *    as a cross-check: if they disagree, the rows were misread.
 *  - It never reformats money. Values arrive as strings, are edited as strings,
 *    and are sent back as strings. Number() appears only inside lib/money.ts,
 *    for the preview total.
 *
 * Amber marks a field the extractor was unsure about. That is the one place in
 * this app the accent is used — see docs/design-tokens.md.
 */

type LineField = "description" | "quantity" | "unit_price";

type ReviewLine = TransactionInput & {
  key: number;
  flagged: Partial<Record<LineField, boolean>>;
  note?: string;
};

export default function InvoiceUploadReview() {
  const navigate = useNavigate();
  const { file, objectUrl, result, clear } = useUploadDraft();

  // UploadDraftRoute redirects when there is no draft, so this is only ever null
  // for the one frame before that redirect commits.
  const extraction = result;

  const [issueDate, setIssueDate] = useState(extraction?.issue_date ?? "");
  const [dueDate, setDueDate] = useState(extraction?.due_date ?? "");
  const [notes, setNotes] = useState(extraction?.notes ?? "");
  const [fieldFlags, setFieldFlags] = useState<Record<string, boolean>>(() => flagsFor(extraction));
  const [lines, setLines] = useState<ReviewLine[]>(() => linesFor(extraction));
  const nextKey = useRef(lines.length);

  const [customers, setCustomers] = useState<Customer[]>([]);
  const [pickedId, setPickedId] = useState<number | null>(extraction?.customer ?? null);
  const [picking, setPicking] = useState(false);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only needed to populate the "Change customer" picker — the linked customer
  // itself comes back resolved from the extract endpoint.
  useEffect(() => {
    let cancelled = false;
    void fetchAllCustomers()
      .then((all) => { if (!cancelled) setCustomers(all); })
      .catch(() => { if (!cancelled) setCustomers([]); });
    return () => { cancelled = true; };
  }, []);

  const linkedCustomer = useMemo(() => {
    if (pickedId === null) return null;
    if (pickedId === extraction?.customer && extraction?.customer_detail) {
      return extraction.customer_detail;
    }
    return customers.find((c) => c.id === pickedId) ?? null;
  }, [pickedId, customers, extraction]);

  const isCreatedCustomer = Boolean(
    extraction?.customer_created && pickedId === extraction?.customer,
  );

  const computedTotal = sumLines(lines);
  const printedTotal = extraction?.printed_total ?? null;
  const totalsAgree =
    printedTotal !== null && Math.abs(Number(printedTotal) - computedTotal) < 0.005;

  const remainingFlags =
    Object.values(fieldFlags).filter(Boolean).length +
    lines.reduce((n, l) => n + Object.values(l.flagged).filter(Boolean).length, 0);

  const canSave = pickedId !== null && Boolean(dueDate) && lines.length > 0 && !saving;

  if (!extraction) return null;

  function clearFlag(path: string) {
    setFieldFlags((prev) => (prev[path] ? { ...prev, [path]: false } : prev));
  }

  function updateLine(key: number, field: LineField, value: string) {
    setLines((prev) =>
      prev.map((l) =>
        l.key === key ? { ...l, [field]: value, flagged: { ...l.flagged, [field]: false } } : l,
      ),
    );
  }

  function addLine() {
    const key = nextKey.current;
    nextKey.current += 1;
    setLines((prev) => [...prev, { key, description: "", quantity: "1", unit_price: "0.00", flagged: {} }]);
  }

  async function save() {
    if (pickedId === null) return;
    setSaving(true);
    setError(null);
    // The ordinary create payload — no new write path exists for extraction, and
    // deliberately so (architecture.md, Invoice write shape). Money leaves as the
    // strings the form holds; the server's computed total is the answer.
    const payload: InvoiceInput = {
      customer: pickedId,
      issue_date: issueDate || undefined,
      due_date: dueDate,
      notes,
      transactions: lines.map(({ description, quantity, unit_price }) => ({
        description,
        quantity,
        unit_price,
      })),
    };
    try {
      const invoice = await api.post<Invoice>("/invoices/", payload);
      clear();
      navigate(`/invoices/${invoice.id}`, { replace: true });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save the invoice.");
      setSaving(false);
    }
  }

  return (
    <>
      <p className="crumb">
        <Link to="/invoices">Invoices</Link> / <Link to="/invoices/upload">Upload</Link> / Review
      </p>

      {error && (
        <p role="alert" className="notice notice-danger" style={{ marginBottom: "var(--sp-16)" }}>{error}</p>
      )}

      <div className="review-grid">
        {/* ---------------------------------------------------------------- */}
        <div className="stack" style={{ gap: "var(--sp-16)" }}>
          <div className="page-head" style={{ marginBottom: 0 }}>
            <div>
              <h1>Check the extracted fields</h1>
              <p className="muted" style={{ margin: "var(--sp-8) 0 0", font: "var(--type-body-sm)" }}>
                {remainingFlags > 0
                  ? `${remainingFlags} ${remainingFlags === 1 ? "field needs" : "fields need"} a look. Correct anything wrong, then save.`
                  : "Nothing is flagged. Correct anything wrong, then save."}
              </p>
            </div>
          </div>

          {remainingFlags > 0 && (
            <p className="notice notice-warning">
              Amber fields were read with low confidence. They are still editable and still saved —
              the marker only says where to look first.
            </p>
          )}

          <div className="card card-pad stack" style={{ gap: "var(--sp-16)" }}>
            <div className="row-between">
              <h2>Invoice</h2>
              <span className="hint">Read from the PDF</span>
            </div>

            <div className="form-grid">
              <label className="field">
                Invoice number
                {/* Not editable, and not saved: Invoice.invoice_number is derived
                    from the primary key (domain.md), so there is no column to
                    write this into. Kept in view because it is what a person
                    would look for when matching this against the paper copy. */}
                <input type="text" value={extraction.source_invoice_number ?? "—"} readOnly />
                <span className="hint">Printed on the PDF. This system numbers invoices itself on save.</span>
              </label>

              <label className={`field${fieldFlags.issue_date ? " is-flagged" : ""}`}>
                Issue date
                <input
                  type="date"
                  value={issueDate}
                  onChange={(e) => { setIssueDate(e.target.value); clearFlag("issue_date"); }}
                />
                {fieldFlags.issue_date && <span className="flag-note">{extraction.field_notes.issue_date}</span>}
              </label>

              <label className={`field${fieldFlags.due_date ? " is-flagged" : ""}`}>
                Due date
                <input
                  type="date"
                  value={dueDate}
                  onChange={(e) => { setDueDate(e.target.value); clearFlag("due_date"); }}
                />
                {fieldFlags.due_date && <span className="flag-note">{extraction.field_notes.due_date}</span>}
              </label>
            </div>

            <label className="field">
              Notes
              <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </label>
          </div>

          <div className="table-wrap">
            <div className="row-between" style={{ padding: "var(--sp-16)" }}>
              <h2>Line items</h2>
              <span className="hint">{lines.length} {lines.length === 1 ? "row" : "rows"} found</span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Description</th>
                  <th className="right">Qty</th>
                  <th className="right">Unit price</th>
                  <th className="right">Line total</th>
                  <th><span className="sr-only">Remove</span></th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line, index) => (
                  <tr key={line.key}>
                    <td>
                      <input
                        type="text"
                        aria-label={`Line ${index + 1} description`}
                        className={line.flagged.description ? "is-flagged" : undefined}
                        value={line.description}
                        onChange={(e) => updateLine(line.key, "description", e.target.value)}
                      />
                      {line.note && Object.values(line.flagged).some(Boolean) && (
                        <span className="flag-note">{line.note}</span>
                      )}
                    </td>
                    <td className="right">
                      <input
                        type="text"
                        inputMode="decimal"
                        aria-label={`Line ${index + 1} quantity`}
                        className={`num right${line.flagged.quantity ? " is-flagged" : ""}`}
                        value={line.quantity}
                        onChange={(e) => updateLine(line.key, "quantity", e.target.value)}
                      />
                    </td>
                    <td className="right">
                      <input
                        type="text"
                        inputMode="decimal"
                        aria-label={`Line ${index + 1} unit price`}
                        className={`num right${line.flagged.unit_price ? " is-flagged" : ""}`}
                        value={line.unit_price}
                        onChange={(e) => updateLine(line.key, "unit_price", e.target.value)}
                      />
                    </td>
                    <td className="right num cell-strong">{lineTotal(line.quantity, line.unit_price).toFixed(2)}</td>
                    <td className="right">
                      <button
                        type="button"
                        className="btn-ghost btn-sm danger"
                        onClick={() => setLines((prev) => prev.filter((l) => l.key !== line.key))}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={3} className="right muted" style={{ fontWeight: "var(--fw-regular)" }}>
                    Total printed on the PDF
                  </td>
                  <td className="right num muted">{printedTotal ?? "—"}</td>
                  <td />
                </tr>
                <tr>
                  <td colSpan={3} className="right">Total from these rows</td>
                  <td className="right num summary-total">{computedTotal.toFixed(2)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
            <div className="row-between" style={{ padding: "var(--sp-12) var(--sp-16)" }}>
              <button type="button" className="btn btn-secondary btn-sm" onClick={addLine}>Add line</button>
              {printedTotal !== null && (
                <span className={`total-check ${totalsAgree ? "agrees" : "disagrees"}`}>
                  {totalsAgree
                    ? "Both agree"
                    : "These disagree — a row was probably misread. The rows are what gets saved."}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* ---------------------------------------------------------------- */}
        <div className="stack" style={{ gap: "var(--sp-16)" }}>
          <div className="side-card stack">
            <span className="eyebrow">Customer</span>

            {picking ? (
              <>
                <label className="field">
                  Customer
                  <select
                    value={pickedId ?? ""}
                    onChange={(e) => {
                      setPickedId(e.target.value ? Number(e.target.value) : null);
                      setPicking(false);
                    }}
                  >
                    <option value="">Select a customer</option>
                    {customers.map((c) => (
                      <option key={c.id} value={c.id}>{customerLabel(c)}</option>
                    ))}
                  </select>
                </label>
                <button type="button" className="btn-ghost btn-sm" onClick={() => setPicking(false)}>Cancel</button>
              </>
            ) : linkedCustomer ? (
              <>
                <span className="cell-strong">{customerLabel(linkedCustomer)}</span>
                {linkedCustomer.email && <span className="hint">{linkedCustomer.email}</span>}
                <span>
                  <span className={`badge ${isCreatedCustomer ? "badge-warning" : "badge-success"}`}>
                    {isCreatedCustomer ? "Created" : "Matched"}
                  </span>
                </span>
                <p className="hint" style={{ margin: 0 }}>
                  {isCreatedCustomer
                    ? "Nothing on file matched this supplier, so a customer record was created and linked. Correct it on the customers page if the name was misread."
                    : "Linked to an existing customer. No new customer record was created."}
                </p>
                <button type="button" className="btn-ghost btn-sm" onClick={() => setPicking(true)}>
                  Change customer
                </button>
              </>
            ) : (
              <>
                <p className="hint" style={{ margin: 0 }}>
                  No customer could be read from this PDF. Pick one before saving.
                </p>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPicking(true)}>
                  Choose a customer
                </button>
              </>
            )}
          </div>

          <div className="side-card stack">
            <span className="eyebrow">Source file</span>
            <span className="row">
              <span className="file-thumb" aria-hidden="true">PDF</span>
              <span className="stack" style={{ gap: "var(--sp-2)" }}>
                <span className="cell-strong">{file?.name ?? "—"}</span>
                <span className="hint">
                  {file ? formatBytes(file.size) : "—"}
                  {extraction.page_count > 0 && ` · ${extraction.page_count} pages`}
                </span>
              </span>
            </span>
            {objectUrl && (
              <a href={objectUrl} target="_blank" rel="noreferrer">Open PDF in a new tab</a>
            )}
            <p className="hint" style={{ margin: 0 }}>
              Read and discarded. The file is not stored on the server and is not attached to the
              saved invoice.
            </p>
          </div>

          <div className="stack">
            <button type="button" className="btn" disabled={!canSave} onClick={() => void save()}>
              {saving ? "Saving…" : "Save invoice"}
            </button>
            <Link className="btn btn-secondary" to="/invoices" onClick={clear} style={{ justifyContent: "center" }}>
              Discard
            </Link>
            {pickedId === null ? (
              <p className="hint" style={{ margin: 0 }}>Pick a customer before saving.</p>
            ) : !dueDate ? (
              <p className="hint" style={{ margin: 0 }}>A due date is required before saving.</p>
            ) : (
              <p className="hint" style={{ margin: 0 }}>
                Saving writes the invoice and its line items.
              </p>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

/* -------------------------------------------------------------------------- */

/** Low-confidence paths that are not line items, as a flag map. */
function flagsFor(extraction: ExtractionResult | null): Record<string, boolean> {
  const flags: Record<string, boolean> = {};
  for (const path of extraction?.low_confidence ?? []) {
    if (!path.startsWith("transactions.")) flags[path] = true;
  }
  return flags;
}

/**
 * Line items with their flags resolved onto the row itself. Doing this once, up
 * front, means removing a row cannot leave a `transactions.2.quantity` flag
 * pointing at whatever slid into position 2.
 */
function linesFor(extraction: ExtractionResult | null): ReviewLine[] {
  const fields: LineField[] = ["description", "quantity", "unit_price"];
  return (extraction?.transactions ?? []).map((line, index) => {
    const flagged: ReviewLine["flagged"] = {};
    let note: string | undefined;
    for (const field of fields) {
      const path = `transactions.${index}.${field}`;
      if (extraction?.low_confidence.includes(path)) {
        flagged[field] = true;
        note = note ?? extraction.field_notes[path];
      }
    }
    return { key: index, ...line, flagged, note };
  });
}
