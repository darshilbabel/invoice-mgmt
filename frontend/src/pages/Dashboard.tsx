import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { Dashboard as DashboardData } from "../types";

export default function Dashboard() {
  const { user } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<DashboardData>("/dashboard/")
      .then((d) => !cancelled && setData(d))
      .catch((e: unknown) =>
        !cancelled && setError(e instanceof Error ? e.message : "Failed to load."),
      );
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <p role="alert">{error}</p>;
  if (!data) return <p>Loading…</p>;

  return (
    <section>
      <h1>Dashboard</h1>
      {user?.role === "STAFF" && (
        <p className="muted">Showing invoices you created.</p>
      )}

      <div className="tiles">
        <Tile label="Invoices" value={String(data.invoice_count)} />
        {/* grand_total is a string from the API and is rendered verbatim —
            never parsed into a number. See architecture.md section 7. */}
        <Tile label="Total billed" value={data.grand_total} />
        <Tile label="Overdue" value={String(data.overdue_count)} />
        <Tile label="Customers" value={String(data.customer_count)} />
      </div>

      <h2>Recent invoices</h2>
      {data.recent_invoices.length === 0 ? (
        <p className="muted">No invoices yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Invoice</th>
              <th>Customer</th>
              <th>Due</th>
              <th className="right">Total</th>
            </tr>
          </thead>
          <tbody>
            {data.recent_invoices.map((invoice) => (
              <tr key={invoice.id}>
                <td>
                  <Link to={`/invoices/${invoice.id}/edit`}>
                    {invoice.invoice_number}
                  </Link>
                </td>
                <td>{invoice.customer.name}</td>
                <td>{invoice.due_date}</td>
                <td className="right">{invoice.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <strong className="tile-value">{value}</strong>
    </div>
  );
}
