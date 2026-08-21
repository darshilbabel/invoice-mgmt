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
