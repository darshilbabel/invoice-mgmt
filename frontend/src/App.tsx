import { Link, Navigate, Route, Routes } from "react-router-dom";

import ProtectedRoute from "./components/ProtectedRoute";
import { useAuth } from "./auth/AuthContext";
import Dashboard from "./pages/Dashboard";
import InvoiceForm from "./pages/InvoiceForm";
import InvoiceList from "./pages/InvoiceList";
import Login from "./pages/Login";

function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  return (
    <>
      <nav>
        <Link to="/">Dashboard</Link>
        <Link to="/invoices">Invoices</Link>
        {user && (
          <span className="spacer">
            {user.full_name} ({user.role}){" "}
            <button onClick={() => void logout()}>Sign out</button>
          </span>
        )}
      </nav>
      <main>{children}</main>
    </>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<Layout><Dashboard /></Layout>} />
        <Route path="/invoices" element={<Layout><InvoiceList /></Layout>} />
        <Route path="/invoices/new" element={<Layout><InvoiceForm /></Layout>} />
        <Route path="/invoices/:id/edit" element={<Layout><InvoiceForm /></Layout>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
