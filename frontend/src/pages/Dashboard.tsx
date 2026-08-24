import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { daysLate } from "../lib/money";
import type { Dashboard as DashboardData } from "../types";

/** Wireframe 1a — four tiles mapping 1:1 to the /api/dashboard/ payload, then
 *  the recent invoices. Nothing on this screen lacks an endpoint behind it. */
export default function Dashboard() {
  const { user } = useAuth();
  const canWrite = user?.role === "ADMIN" || user?.role === "STAFF";
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
    return () => { cancelled = true; };
  }, []);

  if (error) return <p role="alert" className="notice notice-danger">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          {user?.role === "STAFF" && (
            <p className="muted" style={{ margin: "var(--sp-4) 0 0", font: "var(--type-body-sm)" }}>
              Showing invoices you created.
            </p>
          )}
        </div>
        {canWrite && <Link className="btn" to="/invoices/new">New invoice</Link>}
      </div>

      <div className="tiles">
        <Tile label="Invoices" value={String(data.invoice_count)} />
        {/* Totals print the API string verbatim — never reformatted. */}
        <Tile label="Total billed" value={data.grand_total} />
        <Tile label="Overdue" value={String(data.overdue_count)} danger={data.overdue_count > 0} />
        <Tile label="Customers" value={String(data.customer_count)} />
      </div>

      <div className="row-between" style={{ marginBottom: "var(--sp-12)" }}>
        <h2>Recent invoices</h2>
        <Link to="/invoices" className="btn-ghost" style={{ font: "var(--type-label)" }}>View all</Link>
      </div>

      {data.recent_invoices.length === 0 ? (
        <p className="notice notice-muted">No invoices yet.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Invoice</th><th>Customer</th><th>Issued</th><th>Due</th><th className="right">Total</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_invoices.map((invoice) => {
                const late = daysLate(invoice.due_date);
                return (
                  <tr key={invoice.id}>
                    <td><Link className="cell-strong" to={`/invoices/${invoice.id}`}>{invoice.invoice_number}</Link></td>
                    <td>{invoice.customer.name}</td>
                    <td className="num">{invoice.issue_date}</td>
                    <td className="num">
                      {invoice.due_date}{" "}
                      {late > 0 && <span className="badge badge-danger">{late}d late</span>}
                    </td>
                    <td className="right num cell-strong">{invoice.total}</td>
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

function Tile({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className={`tile-value${danger ? " is-danger" : ""}`}>{value}</span>
    </div>
  );
}
