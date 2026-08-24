/**
 * Hand-maintained mirror of the DRF serializers. When a serializer field
 * changes, change it here too — that pairing is the reason this project uses
 * TypeScript at all (architecture.md section 7).
 *
 * MONEY IS ALWAYS A STRING. DRF serialises Decimal as a string and the values
 * are exact to the cent; parsing them into a JS number loses that. Convert only
 * for transient display arithmetic, never for anything sent back.
 */

export type Role = "ADMIN" | "STAFF" | "VIEWER";

/** accounts.serializers.UserSerializer */
export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
}

/** billing.serializers.CustomerSerializer */
export interface Customer {
  id: number;
  name: string;
  email: string;
  company_name: string;
  billing_address: string;
  created_at: string;
  updated_at: string;
}

/** billing.serializers.TransactionSerializer (nested inside an invoice) */
export interface Transaction {
  id: number;
  description: string;
  quantity: string;
  unit_price: string;
  line_total: string; // read-only, computed
}

/** What the invoice form sends for a line item — no id, no line_total. */
export interface TransactionInput {
  description: string;
  quantity: string;
  unit_price: string;
}

/**
 * billing.serializers.InvoiceSerializer, as READ.
 * `customer` and `created_by` are expanded on read but sent as ids on write —
 * see InvoiceInput below and architecture.md section 5.2.
 */
export interface Invoice {
  id: number;
  invoice_number: string; // read-only, derived from the pk
  customer: Customer;
  issue_date: string;
  due_date: string;
  notes: string;
  created_by: User;
  total: string; // read-only, computed from transactions
  transactions: Transaction[];
  created_at: string;
  updated_at: string;
}

/** What create/update send. Note `customer` is an id here, an object on read. */
export interface InvoiceInput {
  customer: number;
  issue_date?: string;
  due_date: string;
  notes?: string;
  transactions: TransactionInput[];
}

/** billing.views.DashboardView */
export interface Dashboard {
  invoice_count: number;
  grand_total: string;
  overdue_count: number;
  customer_count: number;
  recent_invoices: Invoice[];
}

/** DRF PageNumberPagination envelope (PAGE_SIZE = 20). */
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface LoginResponse {
  token: string;
  user: User;
}

/** billing.serializers.InvoiceExtractionSerializer — POST /api/invoices/extract/ */

/**
 * Where a value sits in an ExtractionResult, for flagging low confidence:
 * "due_date", or "transactions.2.quantity" for the third line's quantity.
 */
export type ExtractionFieldPath = string;

export interface ExtractionResult {
  /**
   * The customer this invoice was resolved to — a real row by the time this
   * arrives. `customer_created` says whether the backend had to make it, which
   * the review screen tells the user plainly.
   */
  customer: number | null;
  customer_created: boolean;
  customer_detail: Customer | null;
  /**
   * The number printed on the supplier's PDF. Displayed for reference and
   * discarded — Invoice.invoice_number is derived from the pk (domain.md) and
   * has no column to write this into.
   */
  source_invoice_number: string | null;
  issue_date: string | null;
  due_date: string | null;
  notes: string;
  transactions: TransactionInput[];
  /**
   * The total printed on the PDF, as a cross-check against the sum of the rows
   * above. NEVER authoritative and never sent anywhere: a disagreement means
   * the rows were misread. The app's total is always computed — domain.md's
   * one load-bearing rule.
   */
  printed_total: string | null;
  /** Field paths the extractor was unsure about. Still filled in, still saved. */
  low_confidence: ExtractionFieldPath[];
  /** Per-field explanation, keyed by the same paths. Only flagged paths appear. */
  field_notes: Record<ExtractionFieldPath, string>;
  page_count: number;
}

/** Not a serializer shape — the client's own union for a readable failure. */
export interface ExtractionFailure {
  reason: "no_text" | "too_large" | "not_pdf" | "timeout";
  /** Already human-readable — render it directly, like ApiError.message. */
  message: string;
}
